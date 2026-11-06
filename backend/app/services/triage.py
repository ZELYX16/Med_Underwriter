"""
Cheap upload triage: is this the right kind of document, and is it theirs?

Runs in well under a second on the first page only, before any extraction or
indexing, so a wrong or unreadable file is caught while the applicant is still
on the page. No LLM and no embedding is involved.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

_TYPE_RULES = [
    ("discharge", "medical", r"discharge summary"),
    ("medical_exam", "medical", r"medical examination|health check|pre-policy"),
    ("lab", "medical", r"laborator|lab report|hba1c|haemoglobin|hemoglobin|creatinine|investigation report"),
    ("specialist", "medical", r"specialist report|consultation|cardiolog|orthopaedic|urolog|gastroenterolog|radiolog|mri"),
    ("prescription", "medical", r"prescription|\brx\b"),
    ("claim", "claims", r"claim record|claim id|claim form|settlement"),
    ("policy", "policy", r"policy schedule|policy document|sum insured|policy holder|policyholder"),
    ("proposal", "underwriting", r"proposal|submission request|underwriting submission"),
]
_PREFIX = {"MR-": ("medical_exam", "medical"), "CLM-": ("claim", "claims"),
           "POL-": ("policy", "policy"), "UW-": ("proposal", "underwriting")}
_DATE = re.compile(r"\d{1,2}-[A-Za-z]{3}-\d{4}")
_IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def _norm(name: str) -> str:
    name = re.sub(r"\b(mr|mrs|ms|dr|shri|smt)\.?\s+", "", str(name or "").lower())
    return re.sub(r"[^a-z ]", "", name).strip()


def _first_page_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return (reader.pages[0].extract_text() or "") if reader.pages else ""
    except Exception:
        return ""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def triage(path: Path, filename: str, requested_type: str | None, form: dict[str, Any]) -> dict[str, Any]:
    """Return {status, detected_type, folder, issues, scanned, sha256, timing_sec}."""
    started = time.perf_counter()
    suffix = Path(filename).suffix.lower()
    issues: list[str] = []
    status = "accepted"

    data = path.read_bytes()
    digest = sha256(data)
    # Extension checks alone are insufficient: reject obvious type spoofing
    # before parsers or OCR engines inspect the upload.
    signatures = {
        ".pdf": data.startswith(b"%PDF-"),
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
        ".tif": data.startswith((b"II*\x00", b"MM\x00*")),
        ".tiff": data.startswith((b"II*\x00", b"MM\x00*")),
        ".bmp": data.startswith(b"BM"),
    }
    if suffix in signatures and not signatures[suffix]:
        return {"status": "rejected", "detected_type": "unknown", "folder": "other", "scanned": False,
                "issues": ["The file content does not match its file extension. Please upload the original document."],
                "sha256": digest, "timing_sec": round(time.perf_counter() - started, 3)}
    scanned = False
    text = ""
    if suffix == ".pdf":
        text = _first_page_text(path)
        scanned = len(text.strip()) < 40
    elif suffix in _IMAGES:
        scanned = True
    elif suffix in {".txt", ".json", ".csv"}:
        text = data[:4000].decode("utf-8", errors="ignore")
    else:
        return {"status": "rejected", "detected_type": "unknown", "folder": "other", "scanned": False,
                "issues": [f"We cannot read '{suffix or 'this'}' files. Please upload a PDF, photo or text file."],
                "sha256": digest, "timing_sec": round(time.perf_counter() - started, 3)}

    detected, folder = "unknown", "other"
    for prefix, (kind, fld) in _PREFIX.items():
        if filename.upper().startswith(prefix):
            detected, folder = kind, fld
    if detected == "unknown":
        lowered = re.sub(r"[_\-.]+", " ", (text + " " + filename).lower())
        for kind, fld, pattern in _TYPE_RULES:
            if re.search(pattern, lowered):
                detected, folder = kind, fld
                break

    if scanned:
        from app.services.ocr import ocr_available

        if not ocr_available():
            issues.append("This looks like a scan or photo and automatic reading of scans is not switched on, "
                          "so a reviewer will read it. A text PDF is processed faster.")
            status = "warning"

    # Whose document is it? Only compare what the page clearly states.
    if text:
        # Label-anchored; the policyholder is never compared (on a group policy
        # that is the employer), only the insured member.
        name_match = re.search(r"(?i:applicant name|patient name|insured member)\s*[:\-]?\s*"
                               r"([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){1,3})", text)
        if name_match and form.get("name"):
            found, expected = _norm(name_match.group(1)), _norm(form["name"])
            if found and expected and found not in expected and expected not in found:
                status = "rejected"
                issues.append(f"This document is for '{name_match.group(1).strip()}', not '{form['name']}'. "
                              "Please upload your own document.")
        dob_match = re.search(r"date of birth[^0-9]{0,20}(\d{1,2}-[A-Za-z]{3}-\d{4})", text, re.IGNORECASE)
        if dob_match and form.get("dob"):
            from app.rag.structured import parse_date

            raw_expected_dob = str(form.get("dob") or "").strip()
            expected_dob = parse_date(raw_expected_dob)
            if expected_dob is None:
                from datetime import date, datetime
                for dob_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
                    try:
                        expected_dob = datetime.strptime(raw_expected_dob[:10], dob_format).date().isoformat()
                        break
                    except ValueError:
                        continue
            actual_dob = parse_date(dob_match.group(1))
            if actual_dob and expected_dob and actual_dob != expected_dob:
                status = "rejected"
                issues.append(
                    f"The date of birth on this document ({actual_dob}) does not match "
                    f"the date entered ({expected_dob}). Please check the applicant details."
                )

    wanted = {"medical_exam": "medical", "medical": "medical", "claims": "claims", "policy": "policy"}.get(requested_type or "")
    if wanted and folder not in (wanted, "other") and status != "rejected":
        status = "warning"
        issues.append(f"You added this as a {requested_type.replace('_', ' ')} document, but it looks like a "
                      f"{detected.replace('_', ' ')} document. You can keep it or replace it.")

    return {"status": status, "detected_type": detected, "folder": folder, "scanned": scanned,
            "issues": issues, "sha256": digest, "timing_sec": round(time.perf_counter() - started, 3)}
