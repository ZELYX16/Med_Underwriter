"""
Structure-aware reading of the underwriting PDFs.

pypdf's plain extraction puts every table cell on its own line, which loses
which value belongs to which column. Its *layout* mode keeps columns aligned
on one line, so tables can be rebuilt from the column offsets. From that this
module produces:

  * sections with their tables / key-value blocks / text (used for chunking,
    so every chunk knows its section and table rows keep their headers),
  * structured facts per document type (diagnoses with ICD codes, vitals,
    claim records, policy terms, the submission's declarations), and
  * applicant-level aggregation used for non-disclosure and consistency
    checks.

Everything is deterministic and pure Python (pypdf only). If a document does
not follow the expected layout the functions return what they could read and
callers fall back to the older text-based behaviour.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services.medical_groups import diagnosis_group, text_group

logger = logging.getLogger(__name__)

_CELL = re.compile(r"\S+(?: \S+)*")
_HEADING = re.compile(r"^(\d{1,2})\.\s+([A-Z].*)$")
# Bullet glyphs come through as control characters (e.g. DEL) or symbols.
_GLYPHS = re.compile("[\x00-\x08\x0b-\x1f\x7f\u2022\u25aa\u25cf\u25e6\u2023]")
_NOISE = (
    re.compile(r"\b[A-Z]{2,3}-\d{3,5}\s*\|\s*APP-\d+"),
    re.compile(r"^SYNTHETIC / DEMONSTRATION DATA"),
)

# Column titles that identify a table header row (lower case).
COLUMN_TITLES = {
    "condition", "year diagnosed", "status (as declared)",
    "medication", "medication (generic name)", "dose and frequency",
    "indication", "duration", "date(s)", "facility", "reason / procedure",
    "policy ref.", "insurer", "type", "sum insured (inr)", "status / period",
    "claims declared", "#", "question", "answer", "details", "document",
    "status", "document id", "document type", "document date", "source",
    "benefit", "scope", "limit", "item", "terms", "claim id", "event",
    "approved (inr)", "system", "finding", "investigation",
    "result / finding", "diagnosis", "icd-10-cm", "status / comment",
    "amount (inr) / detail",
    "test", "unit", "units", "reference range", "reference interval", "reference",
    "normal range", "flag", "interpretation", "parameter", "analyte", "result",
}

_FAMILY = re.compile(
    r"\b(father|mother|parents?|sister|brother|siblings?|grand(?:father|mother|parents?)"
    r"|family history|uncle|aunt)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Low-level text helpers
# ---------------------------------------------------------------------------

def cells(line: str) -> list[tuple[int, str]]:
    """Cells of a layout line: words joined by single spaces, split on gaps."""
    return [(m.start(), m.group()) for m in _CELL.finditer(line)]


def _is_header(cs: list[tuple[int, str]]) -> bool:
    return sum(1 for _, text in cs if text.strip().lower() in COLUMN_TITLES) >= 2


def parse_amount(value: Any) -> float | None:
    """'1,05,900' / 'INR 5,00,000' / '6,400 - Non-medical' -> number."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


def parse_date(value: Any) -> str | None:
    """First date in the text as ISO ('09-May-2023' -> '2023-05-09')."""
    match = re.search(r"\d{1,2}-[A-Za-z]{3}-\d{4}", str(value or ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def parse_period(value: Any) -> tuple[str | None, str | None]:
    dates = [
        d for d in (
            parse_date(m) for m in re.findall(r"\d{1,2}-[A-Za-z]{3}-\d{4}", str(value or ""))
        ) if d
    ]
    if not dates:
        return None, None
    return dates[0], dates[-1]


def age_on(dob_iso: str | None, on_iso: str | None = None) -> int | None:
    """Whole years between a date of birth and a date (today when omitted)."""
    try:
        born = date.fromisoformat(str(dob_iso))
        on = date.fromisoformat(str(on_iso)) if on_iso else date.today()
    except (TypeError, ValueError):
        return None
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _ref_range(text: str) -> tuple[float | None, float | None]:
    """'70-99', '< 5.7', '>= 60', 'up to 30' -> (low, high)."""
    text = str(text or "").replace("\u2013", "-").replace("\u2014", "-")
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r"(?:<|<=|up to|below|less than)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if match:
        return None, float(match.group(1))
    match = re.search(r"(?:>|>=|above|more than)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if match:
        return float(match.group(1)), None
    return None, None


def _lab_flag(value: float, low: float | None, high: float | None, flag_text: str) -> str:
    flag = str(flag_text or "").strip().lower()
    if flag in {"h", "high", "hh", "raised", "elevated"} or "high" in flag:
        return "high"
    if flag in {"l", "low", "ll"} or flag.startswith("low"):
        return "low"
    if flag in {"n", "normal", "within range"} or flag.startswith("normal"):
        return "normal"
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    if low is not None or high is not None:
        return "normal"
    return "unknown"


def _lab_rows(doc: dict[str, Any], document_id: str, document_date: str | None) -> list[dict[str, Any]]:
    """Numeric laboratory results with unit, reference range and flag."""
    labs: list[dict[str, Any]] = []
    for table in find_tables(doc, "result"):
        headers = " | ".join(h.lower() for h in table["headers"])
        if not any(k in headers for k in ("test", "investigation", "parameter", "analyte")):
            continue
        for row in _rows(table):
            name = _field(row, "test", "investigation", "parameter", "analyte")
            result = _field(row, "result")
            number = _NUM.search(result)
            if not name or not number:
                continue
            value = float(number.group())
            unit = _field(row, "unit") or result[number.end():].strip(" ()")
            reference = _field(row, "reference", "normal range", "range")
            low, high = _ref_range(reference)
            labs.append(
                {
                    "name": name,
                    "value": value,
                    "unit": unit,
                    "reference": reference,
                    "flag": _lab_flag(value, low, high, _field(row, "flag", "interpretation")),
                    "document_id": document_id,
                    "document_date": document_date,
                    "section": table.get("section", ""),
                }
            )
    return labs


_NEGATIVE_CUE = re.compile(r"\b(no|denies|negative for|without|nil|absent|not (seen|detected|reported))\b", re.IGNORECASE)


def _normalize_name(value: Any) -> str:
    text = re.sub(r"\b(mr|mrs|ms|dr|shri|smt)\.?\s+", "", str(value or "").lower())
    return re.sub(r"[^a-z ]", "", text).strip()


# ---------------------------------------------------------------------------
# Layout parsing
# ---------------------------------------------------------------------------

def layout_lines(path: str | Path) -> list[str]:
    """Layout-mode lines of every page, without repeating headers/footers."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout") or ""
        for raw in text.splitlines():
            raw = _GLYPHS.sub(" ", raw)
            stripped = raw.strip()
            if any(p.search(stripped) for p in _NOISE):
                continue
            lines.append(raw.rstrip())
        lines.append("")
    return lines


def _split_sections(lines: list[str]) -> list[dict[str, Any]]:
    sections = [{"number": 0, "title": "", "lines": []}]
    for line in lines:
        stripped = line.strip()
        match = _HEADING.match(stripped)
        if match and len(cells(line)) == 1:
            sections.append(
                {"number": int(match.group(1)), "title": match.group(2).strip(), "lines": []}
            )
        else:
            sections[-1]["lines"].append(line)
    return sections


def _near(offset: int, offsets: list[int], tolerance: int = 3) -> bool:
    return any(abs(offset - o) <= tolerance for o in offsets)


def _parse_kv(lines: list[str]) -> dict[str, str]:
    """Label/value pairs from two- or four-column key-value tables."""
    pairs: list[dict[str, Any]] = []
    last: list[dict[str, Any]] = []
    label_offsets: list[int] = []

    def pair(label: tuple[int, str], value: tuple[int, str] | None) -> dict[str, Any]:
        return {
            "label": label[1],
            "label_off": label[0],
            "value": value[1] if value else "",
            "value_off": value[0] if value else None,
        }

    for line in lines:
        cs = cells(line)
        if not cs:
            continue
        if not label_offsets:
            label_offsets = [cs[0][0]]
        if len(cs) >= 4 and not _near(cs[2][0], label_offsets):
            label_offsets.append(cs[2][0])

        first_off, first_text = cs[0]
        looks_like_continuation = (
            first_text.startswith("(") or first_text[:1].islower()
        )
        is_new = _near(first_off, label_offsets) and not (
            looks_like_continuation and last
        )

        if is_new:
            if len(cs) >= 4:
                new = [pair(cs[0], cs[1]), pair(cs[2], cs[3])]
            elif len(cs) == 3:
                new = [pair(cs[0], cs[1]), pair(cs[2], None)]
            elif len(cs) == 2:
                new = [pair(cs[0], cs[1])]
            else:
                new = [pair(cs[0], None)]
            pairs.extend(new)
            last = new
            continue

        for off, text in cs:
            if _near(off, label_offsets) and looks_like_continuation and last:
                target = min(last, key=lambda p: abs(p["label_off"] - off))
                target["label"] = f"{target['label']} {text}".strip()
                continue
            candidates = [
                p for p in last
                if p["value_off"] is not None and p["value_off"] <= off + 3
            ]
            target = (
                max(candidates, key=lambda p: p["value_off"])
                if candidates
                else (last[-1] if last else None)
            )
            if target is not None:
                if target["value_off"] is None:
                    target["value_off"] = off
                target["value"] = f"{target['value']} {text}".strip()

    result: dict[str, str] = {}
    for p in pairs:
        result.setdefault(p["label"], p["value"])
    return result


def _parse_table(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    header = cells(lines[start])
    headers = [text for _, text in header]
    starts = [off for off, _ in header]

    # Long titles wrap ("Policy" / "ref."): merge continuation lines made only
    # of lowercase or parenthesised cells into the header.
    first_row = start + 1
    while first_row < len(lines) and lines[first_row].strip():
        extra = cells(lines[first_row])
        if not extra or not all(t[:1].islower() or t.startswith("(") for _, t in extra):
            break
        for off, text in extra:
            eligible = [i for i, s in enumerate(starts) if s <= off + 3]
            idx = max(eligible) if eligible else 0
            headers[idx] = f"{headers[idx]} {text}".strip()
        first_row += 1
    signature = [h.lower() for h in headers]
    # Hospitalizations wrap their date and facility cells, so rows are
    # recognised by the Duration column instead of the first one.
    key_col = len(headers) - 1 if "facility" in signature and "date(s)" in signature else 0

    def column(offset: int) -> int:
        eligible = [i for i, s in enumerate(starts) if s <= offset + 3]
        return max(eligible) if eligible else 0

    rows: list[list[str]] = []
    i = first_row
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            break
        cs = cells(line)
        if _is_header(cs):
            break
        if _HEADING.match(line.strip()) and len(cs) == 1:
            break
        # A lone capitalised sentence at the first column ends the table
        # (e.g. "Treatment: ...", "Assessment summary: ...").
        if (
            len(cs) == 1
            and cs[0][0] <= starts[0] + 1
            and cs[0][1][:1].isupper()
            and (
                ":" in cs[0][1]
                or cs[0][1].rstrip().endswith(".")
                or len(cs[0][1]) > 70
            )
        ):
            break

        row_cells = [""] * len(headers)
        for off, text in cs:
            idx = column(off)
            row_cells[idx] = f"{row_cells[idx]} {text}".strip()

        if key_col == 0:
            first = row_cells[0]
            # Lab names such as "eGFR" or "pH" start in lower case but are
            # new rows; wrapped fragments ("hours or more)") are not.
            new_row = bool(first) and (
                first[0].isupper()
                or first[0].isdigit()
                or first[0] == "#"
                or bool(re.match(r"^[a-z]{1,3}[A-Z]", first))
            )
        else:
            new_row = bool(row_cells[key_col])
        if not rows:
            new_row = True

        if new_row:
            rows.append(row_cells)
        else:
            for idx, text in enumerate(row_cells):
                if text:
                    rows[-1][idx] = f"{rows[-1][idx]} {text}".strip()
        i += 1

    return {"type": "table", "headers": headers, "rows": rows}, i


def _merge_text(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        text = re.sub(r"^[^\w(\[#]+", "", line.strip()).strip()
        if not text:
            continue
        if items and not re.search(r"[.:;)]$", items[-1]) and (
            text[:1].islower() or text.startswith("(")
        ):
            items[-1] = f"{items[-1]} {text}"
        else:
            items.append(text)
    return items


def _classify(buf: list[str]) -> list[dict[str, Any]]:
    """Split a run of lines into a key-value block plus trailing text."""
    first = cells(buf[0])
    if len(first) >= 2:
        label_off = first[0][0]
        end = len(buf)
        for index, line in enumerate(buf[1:], start=1):
            cs = cells(line)
            if (
                len(cs) == 1
                and abs(cs[0][0] - label_off) <= 1
                and cs[0][1][:1].isupper()
                and (":" in cs[0][1] or cs[0][1].rstrip().endswith(".") or len(cs[0][1]) > 40)
            ):
                end = index
                break
        blocks = [{"type": "kv", "data": _parse_kv(buf[:end])}]
        if end < len(buf):
            blocks.append({"type": "text", "items": _merge_text(buf[end:])})
        return blocks
    return [{"type": "text", "items": _merge_text(buf)}]


def _blocks(lines: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            blocks.extend(_classify(list(buf)))
            buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if _is_header(cells(line)):
            flush()
            table, i = _parse_table(lines, i)
            blocks.append(table)
            continue
        buf.append(line)
        i += 1
    flush()
    return blocks


def _detect_title(lines: list[str]) -> str:
    title = ""
    for line in lines:
        text = line.strip()
        if (
            len(text) >= 12
            and re.fullmatch(r"[A-Z][A-Z /&-]+", text)
            and not text.startswith("SYNTHETIC")
        ):
            title = text
    return title.title()


_PARSE_CACHE: dict[tuple[str, float], dict[str, Any] | None] = {}


def parse_pdf(path: str | Path) -> dict[str, Any] | None:
    """Parse one PDF into sections and blocks; None if it can't be read."""
    path = Path(path)
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if key in _PARSE_CACHE:
        return _PARSE_CACHE[key]

    try:
        lines = layout_lines(path)
        sections = _split_sections(lines)
        preamble = sections[0]
        header: dict[str, str] = {}
        for block in _blocks(preamble["lines"]):
            if block["type"] == "kv":
                for label, value in block["data"].items():
                    header.setdefault(label, value)
        doc: dict[str, Any] = {
            "path": str(path),
            "file_name": path.name,
            "title": _detect_title(preamble["lines"]),
            "header": header,
            "sections": [
                {
                    "number": s["number"],
                    "title": s["title"],
                    "blocks": _blocks(s["lines"]),
                }
                for s in sections[1:]
            ],
        }
        doc["doc_id"] = kvget(header, "Document ID") or path.stem.split("_")[0]
        doc["doc_type"] = doc_type_of(doc["doc_id"], path)
        result: dict[str, Any] | None = doc
    except Exception as exc:  # unreadable / unexpected layout
        logger.warning("Structured parse failed for %s: %s", path.name, exc)
        result = None
    _PARSE_CACHE[key] = result
    return result


def doc_type_of(doc_id: str, path: str | Path | None = None) -> str:
    prefix = str(doc_id or "").upper()
    if prefix.startswith("UW-"):
        return "underwriting"
    if prefix.startswith("MR-"):
        return "medical"
    if prefix.startswith("CLM-"):
        return "claims"
    if prefix.startswith("POL-"):
        return "policy"
    folder = Path(path).parent.name.lower() if path else ""
    return folder if folder in {"medical", "claims", "policy", "underwriting"} else "other"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def kvget(kv: dict[str, str], *prefixes: str) -> str:
    """Value of the first label that starts with one of the prefixes."""
    for prefix in prefixes:
        wanted = prefix.lower()
        for label, value in kv.items():
            if label.lower() == wanted:
                return value
    for prefix in prefixes:
        wanted = prefix.lower()
        for label, value in kv.items():
            if label.lower().startswith(wanted):
                return value
    return ""


def all_kv(doc: dict[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = dict(doc.get("header") or {})
    for section in doc["sections"]:
        for block in section["blocks"]:
            if block["type"] == "kv":
                for label, value in block["data"].items():
                    merged.setdefault(label, value)
    return merged


def section_kv(doc: dict[str, Any], title_part: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for section in doc["sections"]:
        if title_part.lower() in section["title"].lower():
            for block in section["blocks"]:
                if block["type"] == "kv":
                    for label, value in block["data"].items():
                        merged.setdefault(label, value)
    return merged


def find_tables(doc: dict[str, Any], *words: str) -> list[dict[str, Any]]:
    found = []
    for section in doc["sections"]:
        for block in section["blocks"]:
            if block["type"] != "table":
                continue
            headers = " | ".join(h.lower() for h in block["headers"])
            if all(w.lower() in headers for w in words):
                found.append({**block, "section": section["title"]})
    return found


def section_text(doc: dict[str, Any], *title_parts: str) -> list[str]:
    items: list[str] = []
    for section in doc["sections"]:
        title = section["title"].lower()
        if any(p.lower() in title for p in title_parts):
            for block in section["blocks"]:
                if block["type"] == "text":
                    items.extend(block["items"])
    return items


def _rows(table: dict[str, Any]) -> list[dict[str, str]]:
    return [dict(zip(table["headers"], row)) for row in table["rows"]]


def _field(row: dict[str, str], *prefixes: str) -> str:
    for prefix in prefixes:
        for key, value in row.items():
            if key.lower().startswith(prefix.lower()):
                return value
    return ""


# ---------------------------------------------------------------------------
# Rendering (for chunks and reviewer-facing text)
# ---------------------------------------------------------------------------

def render_block(block: dict[str, Any]) -> list[str]:
    if block["type"] == "text":
        return list(block["items"])
    if block["type"] == "kv":
        return [f"{label}: {value}" for label, value in block["data"].items() if value]
    lines = []
    for row in block["rows"]:
        parts = [f"{h}: {v}" for h, v in zip(block["headers"], row) if v]
        if parts:
            lines.append("; ".join(parts))
    return lines


def doc_label(doc: dict[str, Any]) -> str:
    return " ".join(p for p in (doc.get("title"), doc.get("doc_id")) if p).strip()


def render_document(doc: dict[str, Any]) -> str:
    out: list[str] = [doc_label(doc)]
    out += [f"{k}: {v}" for k, v in doc["header"].items() if v]
    for section in doc["sections"]:
        out.append("")
        out.append(f"{section['number']}. {section['title']}")
        for block in section["blocks"]:
            out += render_block(block)
    return "\n".join(out).strip()


def section_chunks(doc: dict[str, Any], max_chars: int = 800) -> list[dict[str, Any]]:
    """One chunk per section (split on row/line boundaries when long)."""
    label = doc_label(doc)
    chunks: list[dict[str, Any]] = []

    def emit(section_title: str, lines: list[str]) -> None:
        prefix = f"[{label} | {section_title}]\n"
        buf: list[str] = []
        size = len(prefix)
        for line in lines:
            if buf and size + len(line) + 1 > max_chars:
                chunks.append({"text": prefix + "\n".join(buf), "section": section_title})
                buf, size = [], len(prefix)
            buf.append(line)
            size += len(line) + 1
        if buf:
            chunks.append({"text": prefix + "\n".join(buf), "section": section_title})

    header_lines = [f"{k}: {v}" for k, v in doc["header"].items() if v]
    if header_lines:
        emit("Document details", header_lines)
    for section in doc["sections"]:
        lines: list[str] = []
        for block in section["blocks"]:
            lines += render_block(block)
        if lines:
            emit(f"{section['number']}. {section['title']}", lines)
    return chunks


# ---------------------------------------------------------------------------
# Facts per document type
# ---------------------------------------------------------------------------

def _claim_ids(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"CLM-\d{5}", text, flags=re.IGNORECASE)))


def submission_facts(doc: dict[str, Any]) -> dict[str, Any]:
    kv = all_kv(doc)
    dob_age = kvget(kv, "Date of birth / age")
    match = re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{4})\s*/\s*(\d+)", dob_age)
    term = re.search(r"(\d+)\s*year", kvget(kv, "Policy term"), flags=re.IGNORECASE)

    conditions = []
    for table in find_tables(doc, "condition", "year diagnosed"):
        for row in _rows(table):
            name = _field(row, "condition")
            if not name:
                continue
            year = re.search(r"\d{4}", _field(row, "year"))
            conditions.append(
                {
                    "condition": name,
                    "year_diagnosed": int(year.group()) if year else None,
                    "status": _field(row, "status"),
                }
            )

    medications = []
    for table in find_tables(doc, "medication", "dose"):
        for row in _rows(table):
            name = _field(row, "medication")
            if name:
                medications.append(
                    {
                        "name": name,
                        "details": _field(row, "dose"),
                        "indication": _field(row, "indication"),
                        "duration": _field(row, "duration"),
                    }
                )

    hospitalizations = []
    for table in find_tables(doc, "facility", "reason"):
        for row in _rows(table):
            period = _field(row, "date")
            if not period:
                continue
            facility = _field(row, "facility")
            reason = _field(row, "reason")
            duration = _field(row, "duration")
            start, end = parse_period(period)
            hospitalizations.append(
                {
                    "period": period,
                    "start_date": start,
                    "end_date": end,
                    "facility": facility,
                    "reason": reason,
                    "duration": duration,
                    # keeps the older "date first" text layout for the UI
                    "details": f"{period} {facility}. {reason} ({duration})".strip(),
                }
            )

    insurance = []
    for table in find_tables(doc, "policy ref", "insurer"):
        for row in _rows(table):
            insurance.append(
                {
                    "policy_id": _field(row, "policy ref"),
                    "insurer": _field(row, "insurer"),
                    "type": _field(row, "type"),
                    "sum_insured": parse_amount(_field(row, "sum insured")),
                    "status": _field(row, "status"),
                    "claims_declared": _field(row, "claims declared"),
                }
            )

    questionnaire = [
        {
            "number": _field(row, "#"),
            "question": _field(row, "question"),
            "answer": _field(row, "answer"),
            "details": _field(row, "details"),
        }
        for table in find_tables(doc, "question", "answer")
        for row in _rows(table)
    ]

    supporting = [
        {"document": _field(row, "document"), "status": _field(row, "status")}
        for table in find_tables(doc, "document", "status")
        if "document type" not in " ".join(table["headers"]).lower()
        for row in _rows(table)
        if _field(row, "document")
    ]
    evidence_on_file = [
        {
            "document_id": _field(row, "document id"),
            "document_type": _field(row, "document type"),
            "document_date": parse_date(_field(row, "document date")),
            "source": _field(row, "source"),
        }
        for table in find_tables(doc, "document id", "document type")
        for row in _rows(table)
        if _field(row, "document id")
    ]

    insurance_text = " ".join(
        " ".join(render_block(b)) for s in doc["sections"]
        if "insurance" in s["title"].lower() for b in s["blocks"]
    )
    declaration = " ".join(section_text(doc, "declaration"))

    return {
        "name": kvget(kv, "Applicant"),
        "dob": parse_date(dob_age),
        "dob_text": match.group(1) if match else "",
        "age": int(match.group(2)) if match else None,
        "applicant_id": kvget(kv, "Applicant ID"),
        "proposal_reference": kvget(kv, "Proposal reference"),
        "submission_date": parse_date(kvget(kv, "Submission date")),
        "product": kvget(kv, "Requested product"),
        "policy_type": kvget(kv, "Policy type"),
        "sum_insured": parse_amount(kvget(kv, "Requested sum insured")),
        "term_years": int(term.group(1)) if term else 1,
        "requested_start_date": kvget(kv, "Requested start date"),
        "add_ons": kvget(kv, "Add-ons requested"),
        "remarks": kvget(kv, "Applicant remarks"),
        "members": kvget(kv, "Members to be covered"),
        "conditions": conditions,
        "medications": medications,
        "hospitalizations": hospitalizations,
        "insurance": insurance,
        "claim_ids": _claim_ids(insurance_text),
        "questionnaire": questionnaire,
        "supporting_documents": supporting,
        "evidence_on_file": evidence_on_file,
        "declaration": declaration,
    }


def _smoking_status(text: str) -> str | None:
    lowered = text.lower()
    if re.search(r"non[- ]?smoker|never smoked|does not smoke|no tobacco", lowered):
        return "non-smoker"
    if re.search(r"former smoker|ex-smoker|quit smoking|stopped smoking|gave up smoking", lowered):
        return "former"
    if re.search(r"current smoker|\bsmokes\b|smoking \d+|tobacco use|cigarettes? (a|per) day", lowered):
        return "smoker"
    return None


def _alcohol_status(text: str) -> str | None:
    lowered = text.lower()
    if re.search(r"\bno alcohol|does not (drink|consume alcohol)|teetotal", lowered):
        return "none"
    if re.search(r"occasional alcohol|social(ly)? drink", lowered):
        return "occasional"
    if re.search(r"(daily|regular|heavy) alcohol|alcohol (use )?disorder|drinks daily", lowered):
        return "regular"
    return None


def medical_facts(doc: dict[str, Any]) -> dict[str, Any]:
    kv = all_kv(doc)
    dob_text = kvget(kv, "Date of birth")

    vitals: dict[str, Any] = {}
    for section in doc["sections"]:
        if "vital" in section["title"].lower():
            for block in section["blocks"]:
                if block["type"] == "kv":
                    for label, value in block["data"].items():
                        vitals.setdefault(label, value)
    bmi = parse_amount(kvget(vitals, "BMI"))
    weight = parse_amount(kvget(vitals, "Weight"))
    height = parse_amount(kvget(vitals, "Height"))

    diagnoses = []
    for table in find_tables(doc, "diagnosis", "icd-10-cm"):
        for row in _rows(table):
            name = _field(row, "diagnosis")
            if not name:
                continue
            icd = _field(row, "icd-10-cm").strip()
            diagnoses.append(
                {
                    "diagnosis": name,
                    "icd": icd,
                    "comment": _field(row, "status"),
                    "group": diagnosis_group(name, icd),
                    "section": table["section"],
                    "document_id": doc["doc_id"],
                }
            )

    medications = []
    for table in find_tables(doc, "medication", "dose"):
        for row in _rows(table):
            name = _field(row, "medication")
            if name:
                medications.append(
                    {
                        "name": name,
                        "details": _field(row, "dose"),
                        "indication": _field(row, "indication"),
                        "duration": _field(row, "duration"),
                    }
                )

    narrative = section_text(
        doc, "history", "symptoms", "assessment", "presenting", "impression", "findings"
    )
    joined = " ".join(narrative)
    family = [
        sentence.strip()
        for item in narrative
        for sentence in re.split(r"(?<=[.;])\s+", item)
        if _FAMILY.search(sentence)
    ]

    document_date = parse_date(kvget(kv, "Document date"))
    dob_iso = parse_date(dob_text)
    stated_age = re.search(r"age\s+(\d+)", dob_text, re.IGNORECASE)
    investigations = [
        " ".join(f"{h}: {v}" for h, v in zip(t["headers"], r) if v)
        for t in find_tables(doc, "investigation")
        for r in t["rows"]
    ]
    negatives = [
        sentence.strip()
        for item in narrative + investigations
        for sentence in re.split(r"(?<=[.;])\s+", item)
        if _NEGATIVE_CUE.search(sentence)
    ][:10]

    return {
        "labs": _lab_rows(doc, doc["doc_id"], document_date),
        "negatives": negatives,
        "stated_age": int(stated_age.group(1)) if stated_age else None,
        "age_at_document": age_on(dob_iso, document_date),
        "document_id": doc["doc_id"],
        "title": doc["title"],
        "applicant_name": kvget(kv, "Applicant name"),
        "dob": parse_date(dob_text),
        "applicant_id": kvget(kv, "Applicant ID"),
        "document_date": parse_date(kvget(kv, "Document date")),
        "specialty": kvget(kv, "Specialty"),
        "facility": kvget(kv, "Healthcare facility"),
        "vitals": {
            "blood_pressure": kvget(vitals, "Blood pressure") or None,
            "pulse": kvget(vitals, "Pulse") or None,
            "bmi": bmi,
            "weight_kg": weight,
            "height_cm": height,
        },
        "smoking": _smoking_status(joined),
        "alcohol": _alcohol_status(joined),
        "family_history": family,
        "diagnoses": diagnoses,
        "medications": medications,
        "narrative": narrative,
        "is_examination": (
            "examination" in (doc["title"] or "").lower()
            or "exam" in str(doc.get("file_name", "")).lower()
        ),
    }


def claim_facts(doc: dict[str, Any]) -> dict[str, Any]:
    kv = all_kv(doc)
    diagnoses = []
    for table in find_tables(doc, "diagnosis", "icd-10-cm"):
        for row in _rows(table):
            name = _field(row, "diagnosis")
            if name:
                icd = _field(row, "icd-10-cm").strip()
                diagnoses.append(
                    {
                        "diagnosis": name,
                        "icd": icd,
                        "group": diagnosis_group(name, icd),
                        "document_id": doc["doc_id"],
                    }
                )
    money: dict[str, float | None] = {}
    for table in find_tables(doc, "item", "amount"):
        for row in _rows(table):
            label = _field(row, "item").lower()
            amount = parse_amount(_field(row, "amount"))
            for key, word in (
                ("billed", "billed"),
                ("claimed", "claimed"),
                ("non_payable", "non-payable"),
                ("approved", "approved"),
                ("settled", "settlement"),
            ):
                if word in label:
                    money.setdefault(key, amount)
    event_start, event_end = parse_period(
        f"{kvget(kv, 'Event / admission date')} to {kvget(kv, 'Discharge date')}"
    )
    return {
        "claim_id": kvget(kv, "Claim ID") or doc["doc_id"],
        "policy_id": kvget(kv, "Policy ID"),
        "applicant_id": kvget(kv, "Applicant ID"),
        "applicant_name": kvget(kv, "Applicant name"),
        "dob": parse_date(kvget(kv, "Date of birth")),
        "status": kvget(kv, "Claim status"),
        "claim_type": kvget(kv, "Claim type"),
        "submitted_date": parse_date(kvget(kv, "Claim submission date")),
        "settlement_date": parse_date(kvget(kv, "Settlement date")),
        "event_date": event_start or parse_date(kvget(kv, "Event / admission date")),
        "discharge_date": event_end,
        "reason": kvget(kv, "Reason for treatment"),
        "procedure": kvget(kv, "Procedure"),
        "facility": kvget(kv, "Healthcare facility"),
        "diagnoses": diagnoses,
        "billed": money.get("billed"),
        "claimed": money.get("claimed"),
        "approved": money.get("approved"),
        "settled": money.get("settled"),
        "coverage_applicability": kvget(kv, "Coverage applicability"),
        "applicable_section": kvget(kv, "Applicable policy"),
        "assessment": " ".join(section_text(doc, "assessment")),
    }


def _months(text: str) -> int | None:
    match = re.search(r"(\d+)\s*months?", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def policy_facts(doc: dict[str, Any]) -> dict[str, Any]:
    kv = all_kv(doc)
    terms: dict[str, str] = {}
    for table in find_tables(doc, "item", "terms"):
        for row in _rows(table):
            terms[_field(row, "item")] = _field(row, "terms")

    specific = terms.get("Specific-illness waiting period", "")
    listed = re.split(r"[,;]", specific.split(":", 1)[1]) if ":" in specific else []
    exclusions = [
        e.strip()
        for e in re.split(r";", terms.get("Exclusions (summary)", ""))
        if e.strip()
    ]

    policy_claims = []
    for table in find_tables(doc, "claim id", "event"):
        for row in _rows(table):
            claim_id = _field(row, "claim id")
            if re.match(r"^CLM-\d+", claim_id):
                start, end = parse_period(_field(row, "date"))
                policy_claims.append(
                    {
                        "claim_id": claim_id,
                        "event": _field(row, "event"),
                        "start_date": start,
                        "end_date": end,
                        "approved": parse_amount(_field(row, "approved")),
                        "status": _field(row, "status"),
                    }
                )

    policy_type = kvget(kv, "Policy type")
    holder = kvget(kv, "Policy holder")
    insured = re.sub(r"\s*\([^)]*\)", "", kvget(kv, "Insured member")).strip()
    is_group = bool(re.search(r"group|employer|corporate|floater", policy_type, re.IGNORECASE))
    # Identity for matching: the insured member. For an individual policy the
    # holder is the same person when no member is named; for a group /
    # employer policy the holder is the employer and is never compared.
    match_name = insured or ("" if is_group else holder)
    role_note = (
        f"Group / employer policy: compared the insured member ({insured or 'not stated'}), "
        f"not the policyholder ({holder})."
        if is_group
        else "Individual policy: compared the insured member / policyholder."
    )

    return {
        "match_name": match_name,
        "role_note": role_note,
        "is_group": is_group,
        "policy_id": kvget(kv, "Policy ID") or doc["doc_id"],
        "applicant_id": kvget(kv, "Applicant ID"),
        "insurer": kvget(kv, "Insurer"),
        "product": kvget(kv, "Product / plan"),
        "policy_type": policy_type,
        "holder": holder,
        "insured_member": insured,
        "dob": parse_date(kvget(kv, "Date of birth")),
        "inception_date": parse_date(kvget(kv, "Policy start date")),
        "period_start": parse_date(kvget(kv, "Current policy period start")),
        "period_end": parse_date(kvget(kv, "Current policy period end")),
        "sum_insured": parse_amount(kvget(kv, "Sum insured")),
        "status": kvget(kv, "Policy status"),
        "premium": parse_amount(kvget(kv, "Annual premium")),
        "terms": terms,
        "specific_illness_months": _months(specific),
        "specific_illness_conditions": [c.strip().lower() for c in listed if c.strip()],
        "pre_existing_months": _months(terms.get("Pre-existing diseases", "")),
        "exclusions": exclusions,
        "diagnostic_note": terms.get("Diagnostic / OPD procedures", ""),
        "claims": policy_claims,
    }


def document_facts(doc: dict[str, Any]) -> dict[str, Any]:
    kind = doc["doc_type"]
    if kind == "underwriting":
        return submission_facts(doc)
    if kind == "medical":
        return medical_facts(doc)
    if kind == "claims":
        return claim_facts(doc)
    if kind == "policy":
        return policy_facts(doc)
    return {}


# ---------------------------------------------------------------------------
# Applicant-level aggregation
# ---------------------------------------------------------------------------

def applicant_files(applicant_id: str, synthetic_root: Path, db_paths: list[str] | None = None) -> list[Path]:
    """PDF files for an applicant: seeded folders plus uploaded documents."""
    found: dict[str, Path] = {}
    base = Path(synthetic_root) / "applicants" / applicant_id
    if base.exists():
        for path in sorted(base.rglob("*.pdf")):
            found[str(path.resolve())] = path
    uploads = Path(synthetic_root) / "uploads" / applicant_id
    if uploads.exists():
        for path in sorted(uploads.rglob("*.pdf")):
            found[str(path.resolve())] = path
    for raw in db_paths or []:
        path = Path(raw)
        if path.suffix.lower() == ".pdf" and path.exists():
            found[str(path.resolve())] = path
    return list(found.values())


def identity_problems(entry: dict[str, Any], reference: dict[str, Any]) -> list[dict[str, Any]]:
    """How a document's identity differs from the proposal's (role-aware names)."""
    problems: list[dict[str, Any]] = []
    if (
        reference.get("applicant_id") and entry.get("applicant_id")
        and entry["applicant_id"] != reference["applicant_id"]
    ):
        problems.append({"field": "applicant ID", "found": entry["applicant_id"],
                         "expected": reference["applicant_id"], "material": True})
    if reference.get("dob") and entry.get("dob") and entry["dob"] != reference["dob"]:
        problems.append({"field": "date of birth", "found": entry["dob"],
                         "expected": reference["dob"], "material": True})
    name = entry.get("applicant_name")
    ref_name = reference.get("name")
    if name and ref_name:
        a, b = _normalize_name(name), _normalize_name(ref_name)
        if a and b and a != b and a not in b and b not in a:
            problems.append({"field": "name", "found": name, "expected": ref_name, "material": False})
    return problems


def build_applicant_facts(paths: list[Path]) -> dict[str, Any]:
    """
    Parse every readable document and aggregate the facts across them.

    Documents whose identity does not match the proposal are listed but their
    facts are held out of the aggregates, so a mismatched document is never
    silently associated with the applicant.
    """
    parsed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unparsed: list[str] = []
    submission: dict[str, Any] | None = None

    for path in paths:
        doc = parse_pdf(path)
        if not doc or not doc["sections"]:
            unparsed.append(path.name)
            continue
        facts = document_facts(doc)
        parsed.append((doc, facts))
        if doc["doc_type"] == "underwriting" and submission is None:
            submission = facts

    reference = {
        "name": (submission or {}).get("name"),
        "dob": (submission or {}).get("dob"),
        "applicant_id": (submission or {}).get("applicant_id"),
    }

    documents: list[dict[str, Any]] = []
    medical: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    excluded: list[str] = []

    for doc, facts in parsed:
        kind = doc["doc_type"]
        if kind == "policy":
            who = facts.get("match_name") or None
        else:
            who = facts.get("applicant_name") or facts.get("name")
        entry = {
            "document_id": doc["doc_id"],
            "doc_type": kind,
            "title": doc["title"],
            "file_name": doc["file_name"],
            "applicant_name": who,
            "dob": facts.get("dob"),
            "applicant_id": facts.get("applicant_id"),
            "document_date": facts.get("document_date") or facts.get("submitted_date"),
            "role_note": facts.get("role_note"),
        }
        problems = identity_problems(entry, reference) if kind != "underwriting" else []
        entry["identity_problems"] = problems
        entry["identity_verified"] = not problems
        documents.append(entry)
        if problems:
            excluded.append(doc["doc_id"])
            continue
        if kind == "medical":
            medical.append(facts)
        elif kind == "claims":
            claims.append(facts)
        elif kind == "policy":
            policies.append(facts)

    # Diagnoses across verified medical documents and claim records.
    diagnoses: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in medical + claims:
        for d in source.get("diagnoses", []):
            key = (d.get("icd") or d["diagnosis"].lower(), d["group"])
            if key in seen:
                continue
            seen.add(key)
            diagnoses.append(d)

    exams = sorted(
        (m for m in medical if m.get("vitals", {}).get("bmi") or m.get("vitals", {}).get("blood_pressure") or m.get("smoking")),
        key=lambda m: m.get("document_date") or "",
        reverse=True,
    )
    vitals: dict[str, Any] = {}
    for m in exams:  # newest first; keep the first value found for each vital
        for key, value in (m.get("vitals") or {}).items():
            if value not in (None, "") and key not in vitals:
                vitals[key] = value
    smoking = next((m["smoking"] for m in exams if m.get("smoking")), None)
    alcohol = next((m["alcohol"] for m in exams if m.get("alcohol")), None)

    age_issues: list[str] = []
    if submission and submission.get("age") and submission.get("dob"):
        computed = age_on(submission["dob"], submission.get("submission_date"))
        if computed is not None and abs(computed - submission["age"]) > 1:
            age_issues.append(
                f"The proposal states age {submission['age']} but its date of birth "
                f"({submission['dob']}) gives {computed}."
            )
    for m in medical:
        if m.get("stated_age") is not None and m.get("age_at_document") is not None:
            if abs(m["stated_age"] - m["age_at_document"]) > 1:
                age_issues.append(
                    f"{m['document_id']} states age {m['stated_age']} but its date of birth gives {m['age_at_document']}."
                )

    return {
        "documents": documents,
        "excluded_documents": excluded,
        "unparsed_files": unparsed,
        "submission": submission,
        "diagnoses": diagnoses,
        "vitals": vitals,
        "smoking": smoking,
        "alcohol": alcohol,
        "labs": [lab for m in medical for lab in m.get("labs", [])],
        "negatives": [
            {"text": t, "document_id": m["document_id"]}
            for m in medical for t in m.get("negatives", [])
        ],
        "medications": [med for m in medical for med in m.get("medications", [])],
        "narrative": " ".join(t for m in medical for t in m.get("narrative", [])),
        "age_issues": age_issues,
        "family_history": [
            {"text": t, "document_id": m["document_id"]}
            for m in medical
            for t in m.get("family_history", [])
        ],
        "claim_records": claims,
        "policy": policies[0] if policies else None,
        "has_medical_examination": any(m.get("is_examination") for m in medical),
    }


# ---------------------------------------------------------------------------
# Document requirements
# ---------------------------------------------------------------------------

def document_requirements(
    facts: dict[str, Any],
    profile: dict[str, Any],
    submission: dict[str, Any],
    age_threshold: int = 45,
    sum_insured_threshold: float = 1_000_000,
) -> dict[str, Any]:
    """
    Which documents are needed, which are on file, and which block a decision.

    Only the pre-policy medical examination blocks (when age, sum insured or
    declared conditions call for it). Everything else is reported as an
    outstanding item for the underwriter, never as a reason to stall.
    """
    sub = facts.get("submission") or {}
    age = profile.get("age") or sub.get("age") or 0
    sum_insured = submission.get("sum_insured") or sub.get("sum_insured") or 0
    conditions = profile.get("medical_conditions") or sub.get("conditions") or []

    reasons = []
    if age and age >= age_threshold:
        reasons.append(f"age {age} (threshold {age_threshold})")
    if sum_insured and sum_insured >= sum_insured_threshold:
        reasons.append(f"sum insured {sum_insured:,.0f}")
    if conditions:
        reasons.append("declared medical conditions")

    required: list[dict[str, Any]] = []
    medical_present = bool(facts.get("has_medical_examination")) or any(
        "exam" in name.lower() for name in facts.get("unparsed_files", [])
    )
    if reasons:
        required.append(
            {
                "document": "Pre-policy medical examination report",
                "reason": "Required for " + ", ".join(reasons),
                "present": medical_present,
                "blocking": True,
            }
        )

    declared_claims = sub.get("claim_ids") or [
        c.get("claim_id") for c in (profile.get("claims") or []) if isinstance(c, dict)
    ]
    on_file = {c.get("claim_id") for c in facts.get("claim_records", [])}
    for claim_id in declared_claims:
        if claim_id and claim_id not in on_file:
            required.append(
                {
                    "document": f"Claim record {claim_id}",
                    "reason": "Claim declared in the proposal",
                    "present": False,
                    "blocking": False,
                }
            )

    if (profile.get("existing_policy") or {}).get("policy_id") and not facts.get("policy"):
        required.append(
            {
                "document": "Existing policy schedule",
                "reason": "Existing policy declared",
                "present": False,
                "blocking": False,
            }
        )

    outstanding = [
        {
            "document": item["document"],
            "reason": f"Proposal lists this as: {item['status']}",
            "present": False,
            "blocking": False,
        }
        for item in sub.get("supporting_documents", [])
        if item.get("status") and not item["status"].lower().startswith("submitted")
    ]

    missing = [r for r in required if not r["present"]]
    return {
        "required": required,
        "outstanding": outstanding,
        "blocking_missing": [r for r in missing if r["blocking"]],
        "non_blocking_missing": [r for r in missing if not r["blocking"]] + outstanding,
    }