"""Deterministic document intelligence used before underwriting agents.

This module deliberately avoids LLM calls. It classifies documents and extracts
high-confidence, source-linked facts using lightweight rules. Ambiguous clinical
interpretation remains a later agent / human-review responsibility.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any


_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("discharge_summary", r"discharge summary|discharge card|discharge note"),
    ("lab_report", r"laboratory report|lab report|investigation report|hba1c|creatinine|lipid profile"),
    ("prescription", r"prescription|medication chart|drug chart|\brx\b"),
    ("consultation", r"consultation|specialist report|clinical notes|outpatient department|\bopd\b"),
    ("medical_exam", r"pre[- ]policy medical|medical examination|health check.?up|medical fitness"),
    ("claim_document", r"claim form|claim number|claim id|settlement letter|claim repudiat|claim rejection"),
    ("policy_document", r"policy schedule|policy number|sum insured|premium amount|policy wording"),
    ("identity_document", r"date of birth|passport no|aadhaar|national id|identity proof"),
)

_EVIDENCE_RULES: tuple[tuple[str, str], ...] = (
    ("diagnosis", r"diagnosis|impression|assessment|known case of|history of"),
    ("medication", r"medication|prescription|tablet|capsule|mg\b|\bml\b|dosage"),
    ("lab_result", r"hba1c|haemoglobin|hemoglobin|creatinine|glucose|cholesterol|triglyceride|\bsgot\b|\bsgpt\b|tsh|blood pressure"),
    ("hospitalization", r"admission|discharge|inpatient|hospital stay|hospitali[sz]ation|admitted on"),
    ("procedure", r"surgery|operation|procedure|angioplasty|bypass|implant|biopsy"),
    ("claim_history", r"claim|settlement|repudiat|reimbursement"),
    ("policy_terms", r"policy number|sum insured|premium|coverage|insured member|nominee"),
    ("identity", r"patient name|applicant name|insured member|date of birth|\bdob\b"),
)

_DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[- ,]+\d{2,4}|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
# Reports frequently wrap the BP label and value onto separate PDF text lines.
# Keep the search window bounded so a later unrelated number is not mistaken
# for a blood-pressure reading.
_BLOOD_PRESSURE = re.compile(
    r"\b(?:blood pressure|home BP|\bBP)\b[\s\S]{0,180}?(\d{2,3})\s*/\s*(\d{2,3})",
    re.I,
)

_LAB_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("hba1c", re.compile(r"\b(?:hba1c|glycated haemoglobin|glycated hemoglobin)\b[^\d\n]{0,30}(\d+(?:\.\d+)?)\s*(%|mmol/mol)?", re.I), "%"),
    ("glucose", re.compile(r"\b(?:fasting blood sugar|fasting glucose|blood glucose|glucose)\b[^\d\n]{0,30}(\d+(?:\.\d+)?)\s*(mg/dl|mmol/l)?", re.I), "mg/dL"),
    ("creatinine", re.compile(r"\bcreatinine\b(?![^\n]{0,25}\bratio\b)[^\d\n]{0,30}(\d+(?:\.\d+)?)\s*(mg/dl|umol/l|µmol/l)?", re.I), "mg/dL"),
    ("haemoglobin", re.compile(r"(?<!glycated\s)(?<!glycated)\b(?:haemoglobin|hemoglobin|hb)\b(?!\s*a1c|\s*a1)[^\d\n]{0,30}(\d+(?:\.\d+)?)\s*(g/dl)?", re.I), "g/dL"),
    ("total_cholesterol", re.compile(r"\btotal cholesterol\b[^\d\n]{0,30}(\d+(?:\.\d+)?)\s*(mg/dl)?", re.I), "mg/dL"),
)


def _normalise_date(value: str) -> str | None:
    value = value.strip().replace(",", " ")
    formats = (
        "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
        "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def classify_document(filename: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    text = "\n".join(str(p.get("text") or "") for p in pages)
    sample = text[:30000].lower()
    name = re.sub(r"[_\-.]+", " ", filename.lower())

    type_scores: dict[str, int] = defaultdict(int)
    for kind, pattern in _TYPE_RULES:
        body_count = len(re.findall(pattern, sample))
        name_count = len(re.findall(pattern, name))
        if body_count > 0 or name_count > 0:
            type_scores[kind] = body_count + name_count * 3

    matched = sorted(type_scores.keys(), key=lambda k: type_scores[k], reverse=True)

    evidence_types = [
        kind for kind, pattern in _EVIDENCE_RULES
        if re.search(pattern, sample)
    ]

    primary = matched[0] if matched else "unknown"

    if primary == "claim_document":
        broad = "claims"
    elif primary == "policy_document":
        broad = "policy"
    elif primary == "identity_document":
        broad = "applicant_profile"
    elif primary == "unknown":
        broad = "other"
    else:
        broad = "medical"

    confidence = 0.0 if not matched else min(0.98, 0.62 + 0.12 * (len(matched) - 1))

    return {
        "primary_type": primary,
        "document_types": matched or ["unknown"],
        "broad_type": broad,
        "evidence_types": evidence_types,
        "classification_confidence": round(confidence, 2),
    }


def extract_facts(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract only explicit facts and retain the exact page and excerpt."""
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int | None]] = set()

    def add(
        kind: str,
        value: str,
        page: int | None,
        excerpt: str,
        confidence: float = 0.9,
        extraction_method: str = "text",
    ) -> None:
        value = re.sub(r"\s+", " ", str(value)).strip(" .,:;\t")
        key = (kind, value.casefold(), page)

        if not value or key in seen:
            return

        seen.add(key)
        facts.append({
            "fact_type": kind,
            "value": value[:240],
            "page": page,
            "excerpt": re.sub(r"\s+", " ", excerpt).strip()[:320],
            "confidence": round(
                confidence * (0.78 if "ocr" in extraction_method.lower() else 1.0),
                2,
            ),
            "method": "deterministic_pattern",
            "extraction_method": extraction_method,
        })

    for page_item in pages:
        page = page_item.get("page_number")
        page = int(page) if isinstance(page, (int, float)) else None
        extraction_method = str(page_item.get("extraction_method") or "text")

        lines = [
            line.strip()
            for line in str(page_item.get("text") or "").splitlines()
            if line.strip()
        ]

        for line in lines:
            bp_match = _BLOOD_PRESSURE.search(line)
            if bp_match:
                try:
                    sys_val = int(bp_match.group(1))
                    dia_val = int(bp_match.group(2))
                    if 70 <= sys_val <= 260 and 40 <= dia_val <= 150:
                        add(
                            "blood_pressure",
                            f"{sys_val}/{dia_val} mmHg",
                            page, line, 0.92, extraction_method,
                        )
                except (ValueError, TypeError):
                    pass

            if re.search(r"(?i)\b(?:patient|applicant|insured member)\s+name\b", line):
                match = re.search(
                    r"(?i)\b(?:patient|applicant|insured member)\s+name\s*[:\-]?\s*(.{2,80})",
                    line,
                )
                if match:
                    add("patient_name", match.group(1), page, line, 0.94, extraction_method)

            if re.search(r"(?i)\b(?:date of birth|dob)\b", line):
                match = _DATE_RE.search(line)
                if match:
                    add(
                        "patient_dob",
                        _normalise_date(match.group(1)) or match.group(1),
                        page, line, 0.95, extraction_method,
                    )

            if re.search(r"(?i)\bdiagnosis\b|\bclinical impression\b", line):
                match = re.search(
                    r"(?i)(?:diagnosis|clinical impression)\s*[:\-]?\s*(.{3,180})",
                    line,
                )
                if match:
                    add("diagnosis_text", match.group(1), page, line, 0.82, extraction_method)

            if re.search(r"(?i)\b(?:medicine|medication|drug)\s*[:\-]", line):
                match = re.search(
                    r"(?i)\b(?:medicine|medication|drug)\s*[:\-]\s*(.{3,160})",
                    line,
                )
                if match:
                    add("medication_text", match.group(1), page, line, 0.82, extraction_method)

            for fact_type, pattern, default_unit in _LAB_PATTERNS:
                match = pattern.search(line)
                if match:
                    unit = (match.group(2) or default_unit).strip()
                    date_match = _DATE_RE.search(line)
                    date_value = _normalise_date(date_match.group(1)) if date_match else None
                    value = f"{match.group(1)} {unit}".strip()

                    if date_value:
                        value = f"{value} (date: {date_value})"

                    add(fact_type, value, page, line, 0.92, extraction_method)

            for label, pattern in (
                ("admission_date", r"(?:date of admission|admitted on)"),
                ("discharge_date", r"(?:date of discharge|discharged on)"),
            ):
                if re.search(pattern, line, re.I):
                    date_match = _DATE_RE.search(line)
                    if date_match:
                        add(
                            label,
                            _normalise_date(date_match.group(1)) or date_match.group(1),
                            page, line, 0.94, extraction_method,
                        )


        # Page-level pass catches wrapped table labels and values, e.g.
        # "Blood pressure (mean\nof 2 readings)\n128/80 mmHg".
        page_text = str(page_item.get("text") or "")
        for bp_match in _BLOOD_PRESSURE.finditer(page_text):
            try:
                sys_val = int(bp_match.group(1))
                dia_val = int(bp_match.group(2))
                if not (70 <= sys_val <= 260 and 40 <= dia_val <= 150):
                    continue
            except (ValueError, TypeError):
                continue
            start = max(0, bp_match.start() - 70)
            end = min(len(page_text), bp_match.end() + 35)
            excerpt = page_text[start:end]
            add(
                "blood_pressure",
                f"{bp_match.group(1)}/{bp_match.group(2)} mmHg",
                page,
                excerpt,
                0.92,
                extraction_method,
            )

    return facts[:250]


def reconcile_facts(
    facts: list[dict[str, Any]],
    existing_documents: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Flag only same-test/same-date lab conflicts; different dates are trends."""
    comparable = {
        "hba1c", "glucose", "creatinine",
        "haemoglobin", "total_cholesterol",
    }

    prior: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)

    for document in existing_documents or []:
        metadata = document.get("metadata") or {}

        for fact in metadata.get("extracted_facts", []):
            kind = fact.get("fact_type")

            if kind not in comparable:
                continue

            value = str(fact.get("value") or "")
            date_match = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", value)

            if date_match:
                prior[(kind, date_match.group(1))].append(
                    (value, str(document.get("filename") or "previous document"))
                )

    conflicts = []

    for fact in facts:
        kind = fact.get("fact_type")

        if kind not in comparable:
            continue

        value = str(fact.get("value") or "")
        date_match = re.search(r"date:\s*(\d{4}-\d{2}-\d{2})", value)

        if not date_match:
            continue

        key = (kind, date_match.group(1))

        for old_value, old_file in prior.get(key, []):
            old_number = re.search(r"(-?\d+(?:\.\d+)?)", old_value)
            new_number = re.search(r"(-?\d+(?:\.\d+)?)", value)

            values_differ = (
                old_number and new_number
                and abs(float(old_number.group(1)) - float(new_number.group(1))) > 1e-6
            )

            if values_differ:
                conflicts.append({
                    "fact_type": kind,
                    "date": key[1],
                    "current_value": value,
                    "previous_value": old_value,
                    "previous_document": old_file,
                    "status": "needs_verification",
                })

    return conflicts


def process_document(
    filename: str,
    pages: list[dict[str, Any]],
    existing_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    classification = classify_document(filename, pages)
    facts = extract_facts(pages)
    conflicts = reconcile_facts(facts, existing_documents)

    methods = sorted({
        str(p.get("extraction_method") or "text")
        for p in pages
    })

    return {
        **classification,
        "extracted_facts": facts,
        "fact_count": len(facts),
        "conflicts": conflicts,
        "extraction_methods": methods,
        "page_count": len(pages),
        "summary": (
            f"Identified {len(classification['evidence_types'])} evidence "
            f"categories and extracted {len(facts)} traceable facts."
        ),
    }