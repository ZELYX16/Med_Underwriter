"""
Shared extraction utilities for Agent 2 and Complexity Router.

Ensures that intake conditions, structured document diagnoses, and sum insured
are extracted uniformly across the pipeline.
"""
from __future__ import annotations

import re
from typing import Any


def parse_number(value: Any) -> float:
    """Tolerant numeric parser supporting currency prefixes, commas, and multipliers."""
    if value is None:
        return 0.0

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        return float(value)

    try:
        text = str(value).strip().lower()
        # Strip common currency prefixes and symbols
        text = re.sub(r"^(rs\.?|inr|usd|\$|eur|€|gbp|£)\s*", "", text, flags=re.I)
        text = text.replace(",", "").strip()

        multiplier = 1.0
        if re.search(r"\b(crore|crores|cr)\b", text, re.I):
            multiplier = 10_000_000.0
            text = re.sub(r"\b(crore|crores|cr)\b", "", text, flags=re.I)
        elif re.search(r"\b(lakh|lakhs|lac|lacs)\b", text, re.I):
            multiplier = 100_000.0
            text = re.sub(r"\b(lakh|lakhs|lac|lacs)\b", "", text, flags=re.I)
        elif re.search(r"\b(million|mn)\b", text, re.I):
            multiplier = 1_000_000.0
            text = re.sub(r"\b(million|mn)\b", "", text, flags=re.I)
        elif re.search(r"\bk\b", text, re.I):
            multiplier = 1_000.0
            text = re.sub(r"\bk\b", "", text, flags=re.I)

        match = re.search(r"[-+]?\d*\.?\d+", text)
        if match:
            return float(match.group()) * multiplier

        return 0.0

    except (TypeError, ValueError):
        return 0.0


def parse_term_years(value: Any) -> float:
    """Parse policy term in months or years into decimal years."""
    if value is None:
        return 1.0
    text = str(value).strip().lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(month|m\b|year|yr|y\b)", text)
    if match:
        num = float(match.group(1))
        unit = match.group(2)
        if "month" in unit or unit == "m":
            return max(1.0, round(num / 12.0, 2))
        return max(1.0, num)
    num = parse_number(value)
    return max(1.0, num if num > 0 else 1.0)


def condition_to_text(cond: Any) -> str:
    """Extract a clean textual condition name from a dict or primitive."""
    if not cond:
        return ""
    if isinstance(cond, dict):
        text = (
            cond.get("condition")
            or cond.get("name")
            or cond.get("diagnosis")
            or cond.get("clinical")
            or cond.get("label")
            or ""
        )
        if not text:
            text = " ".join(str(v) for v in cond.values() if v and isinstance(v, str))
        return str(text).strip()
    return str(cond).strip()


def extract_conditions(
    applicant_profile: dict[str, Any] | None,
    submission: dict[str, Any] | None = None,
    enrichment_results: dict[str, Any] | None = None,
) -> list[str]:
    """Uniform condition extraction across router and risk assessment."""
    applicant_profile = applicant_profile or {}
    submission = submission or {}
    enrichment_results = enrichment_results or {}

    raw_conditions: list[Any] = []

    # 1. Submission medical conditions
    sub_med = submission.get("medical")
    if isinstance(sub_med, dict):
        raw_conditions.extend(sub_med.get("conditions") or [])
    elif isinstance(sub_med, list):
        raw_conditions.extend(sub_med)

    raw_conditions.extend(submission.get("medical_conditions") or [])
    raw_conditions.extend(submission.get("conditions") or [])

    # 2. Profile medical conditions
    prof_med = applicant_profile.get("medical")
    if isinstance(prof_med, dict):
        raw_conditions.extend(prof_med.get("conditions") or [])
    elif isinstance(prof_med, list):
        raw_conditions.extend(prof_med)

    raw_conditions.extend(applicant_profile.get("medical_conditions") or [])
    raw_conditions.extend(applicant_profile.get("conditions") or [])

    # 3. Structured facts from enrichment
    structured = (
        enrichment_results.get("structured_facts")
        or applicant_profile.get("structured_facts")
        or {}
    )
    for d in structured.get("diagnoses") or []:
        if isinstance(d, dict) and d.get("diagnosis"):
            raw_conditions.append(d["diagnosis"])

    # 4. Medical evidence chunks
    for item in enrichment_results.get("medical_evidence") or []:
        if isinstance(item, dict) and item.get("conditions"):
            raw_conditions.extend(item["conditions"])

    # Clean and deduplicate (case-insensitive)
    cleaned: list[str] = []
    seen: set[str] = set()

    for item in raw_conditions:
        name = condition_to_text(item)
        if not name:
            continue
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(name)

    return cleaned


def extract_sum_insured(submission: dict[str, Any] | None) -> float:
    """Tolerantly extract requested sum insured from submission."""
    submission = submission or {}
    candidates = [
        submission.get("sum_insured"),
        submission.get("coverage_amount"),
        submission.get("sumInsured"),
        submission.get("requested_sum_insured"),
    ]
    for val in candidates:
        if val is not None:
            num = parse_number(val)
            if num > 0:
                return num
    return 0.0
