"""
Canonical Clinical Lab Unit Normalizer.

Standardizes clinical biomarkers into conventional actuarial baseline units:
- Glucose: mg/dL (converts mmol/L via factor 18.0182)
- HbA1c: % DCCT (converts IFCC mmol/mol via (IFCC / 10.929) + 2.15)
- Serum Creatinine: mg/dL (converts umol/L via / 88.4)
- Lipids (Cholesterol, Triglycerides, HDL, LDL): mg/dL (converts mmol/L via 38.67)

Handles bounded comparisons ('> 180', '< 0.05'), qualitative strings ('Negative', 'Trace'),
and enforces strict safety: unknown or unparseable units trip human review flags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
_OPERATOR = re.compile(r"([<>]=?|>=|<=)")
_BP = re.compile(r"(\d{2,3})\s*/\s*(\d{2,3})")

_BIOMARKER_PATTERNS: dict[str, str] = {
    "hba1c": r"hba1c|glycated\s*h|glycosylated\s*h|\ba1c\b",
    "fasting_glucose": r"fasting\s*(plasma\s*)?glucose|fasting\s*blood\s*(sugar|glucose)|\bfbs\b|\bfpg\b",
    "random_glucose": r"random\s*(blood\s*)?(glucose|sugar)|\brbs\b|post\s*prandial|\bppbs\b",
    "creatinine": r"serum\s*creatinine|creatinine(?!.*ratio)",
    "egfr": r"\begfr\b|estimated\s*gfr|glomerular\s*filtration",
    "uacr": r"albumin[- /]*creatinine|\buacr\b|\bacr\b|microalbumin",
    "total_cholesterol": r"total\s*cholesterol|\bcholesterol\b(?!.*(?:hdl|ldl|ratio|triglyceride))",
    "triglycerides": r"triglycerides?|\btg\b",
    "hdl_cholesterol": r"hdl(\s*cholesterol)?|high[- ]density",
    "ldl_cholesterol": r"ldl(\s*cholesterol)?|low[- ]density",
}

_KNOWN_UNITS: dict[str, set[str]] = {
    "hba1c": {"%", "dcct", "mmol/mol", "ifcc"},
    "fasting_glucose": {"mg/dl", "mg/100ml", "mg%", "mmol/l", "mmol"},
    "random_glucose": {"mg/dl", "mg/100ml", "mg%", "mmol/l", "mmol"},
    "creatinine": {"mg/dl", "mg/100ml", "umol/l", "µmol/l", "umol", "µmol"},
    "egfr": {"ml/min", "ml/min/1.73m2", "ml/min/1.73 m2", "ml/min/1.73m^2"},
    "uacr": {"mg/g", "mg/mmol", "mcg/mg", "µg/mg"},
    "total_cholesterol": {"mg/dl", "mg%", "mmol/l", "mmol"},
    "triglycerides": {"mg/dl", "mg%", "mmol/l", "mmol"},
    "hdl_cholesterol": {"mg/dl", "mg%", "mmol/l", "mmol"},
    "ldl_cholesterol": {"mg/dl", "mg%", "mmol/l", "mmol"},
}

_QUALITATIVE_PATTERNS = re.compile(
    r"\b(negative|non[- ]reactive|positive|reactive|trace|normal|nil|absent|detected|not\s*detected)\b",
    re.IGNORECASE,
)


@dataclass
class NormalizedLabResult:
    canonical_name: str
    original_name: str
    original_value: Any
    original_unit: str
    normalized_value: float | None
    normalized_unit: str
    operator: str
    status: str  # "NORMALIZED", "UNRECOGNIZED_UNIT", "QUALITATIVE", "PARSE_ERROR"
    qualitative_text: str = ""
    is_bounded: bool = False
    requires_human_review: bool = False
    review_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "name": self.original_name,
            "original_value": self.original_value,
            "original_unit": self.original_unit,
            "value": self.normalized_value,
            "unit": self.normalized_unit,
            "operator": self.operator,
            "status": self.status,
            "qualitative_text": self.qualitative_text,
            "is_bounded": self.is_bounded,
            "requires_human_review": self.requires_human_review,
            "review_reason": self.review_reason,
        }


def identify_canonical_biomarker(name: str) -> str | None:
    """Matches a freeform lab test name to its canonical biomarker key."""
    clean = str(name or "").strip().lower()
    for key, pattern in _BIOMARKER_PATTERNS.items():
        if re.search(pattern, clean, re.IGNORECASE):
            return key
    return None


def parse_blood_pressure(text: str) -> tuple[int, int] | None:
    """Parses systolic and diastolic values from strings like '120/80 mmHg'."""
    match = _BP.search(str(text or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def normalize_lab_entry(
    name: str,
    raw_value: Any,
    unit: str = "",
) -> NormalizedLabResult:
    """
    Standardizes a lab finding into standard canonical units with strict error handling.
    """
    canonical = identify_canonical_biomarker(name) or str(name or "").strip().lower()
    val_str = str(raw_value or "").strip()
    clean_unit = str(unit or "").strip().lower().replace(" ", "")

    # 1. Check for qualitative / categorical findings (e.g. 'Negative', 'Trace')
    qual_match = _QUALITATIVE_PATTERNS.search(val_str)
    num_match = _NUM.search(val_str)

    if not num_match and qual_match:
        return NormalizedLabResult(
            canonical_name=canonical,
            original_name=name,
            original_value=raw_value,
            original_unit=unit,
            normalized_value=None,
            normalized_unit="",
            operator="",
            status="QUALITATIVE",
            qualitative_text=qual_match.group(1).title(),
            is_bounded=False,
            requires_human_review=False,
        )

    if not num_match:
        return NormalizedLabResult(
            canonical_name=canonical,
            original_name=name,
            original_value=raw_value,
            original_unit=unit,
            normalized_value=None,
            normalized_unit="",
            operator="",
            status="PARSE_ERROR",
            requires_human_review=True,
            review_reason=f"Non-numeric and unparseable lab result: '{val_str}'",
        )

    # 2. Extract comparator operators (<, >, <=, >=)
    op_match = _OPERATOR.search(val_str[: num_match.start()]) or _OPERATOR.search(val_str)
    operator = op_match.group(1) if op_match else ""
    is_bounded = bool(operator)

    numeric_val = float(num_match.group())

    # If unit was not provided separately, check if trailing part has unit
    if not clean_unit and len(val_str) > num_match.end():
        trailing = val_str[num_match.end() :].strip(" ()").lower()
        if trailing:
            clean_unit = trailing.replace(" ", "")

    # 3. Unit validation & Normalization matrix
    known = _KNOWN_UNITS.get(canonical)
    norm_val = numeric_val
    norm_unit = clean_unit or "conventional"
    status = "NORMALIZED"
    requires_review = False
    review_reason = ""

    if known and clean_unit and not any(k in clean_unit for k in known):
        # Unrecognized unit for a known critical biomarker
        status = "UNRECOGNIZED_UNIT"
        requires_review = True
        review_reason = f"Unrecognized unit '{clean_unit}' for biomarker '{canonical}'"

    elif canonical == "hba1c":
        norm_unit = "% (DCCT)"
        if "mmol/mol" in clean_unit or "ifcc" in clean_unit or numeric_val > 20.0:
            # IFCC to DCCT conversion: DCCT = (IFCC / 10.929) + 2.15
            norm_val = round((numeric_val / 10.929) + 2.15, 2)
        else:
            norm_val = round(numeric_val, 2)

    elif canonical in {"fasting_glucose", "random_glucose"}:
        norm_unit = "mg/dL"
        if "mmol" in clean_unit or numeric_val < 30.0:
            # mmol/L to mg/dL: factor 18.0182
            norm_val = round(numeric_val * 18.0182, 1)
        else:
            norm_val = round(numeric_val, 1)

    elif canonical == "creatinine":
        norm_unit = "mg/dL"
        if "umol" in clean_unit or "µmol" in clean_unit or numeric_val > 30.0:
            # umol/L to mg/dL: factor / 88.4
            norm_val = round(numeric_val / 88.4, 2)
        else:
            norm_val = round(numeric_val, 2)

    elif canonical in {"total_cholesterol", "triglycerides", "hdl_cholesterol", "ldl_cholesterol"}:
        norm_unit = "mg/dL"
        if "mmol" in clean_unit or numeric_val < 25.0:
            # mmol/L to mg/dL: factor 38.67
            norm_val = round(numeric_val * 38.67, 1)
        else:
            norm_val = round(numeric_val, 1)

    elif canonical == "egfr":
        norm_unit = "mL/min/1.73m2"
        norm_val = round(numeric_val, 1)

    elif canonical == "uacr":
        norm_unit = "mg/g"
        if "mg/mmol" in clean_unit:
            norm_val = round(numeric_val * 8.84, 1)
        else:
            norm_val = round(numeric_val, 1)

    return NormalizedLabResult(
        canonical_name=canonical,
        original_name=name,
        original_value=raw_value,
        original_unit=unit,
        normalized_value=norm_val,
        normalized_unit=norm_unit,
        operator=operator,
        status=status,
        qualitative_text="",
        is_bounded=is_bounded,
        requires_human_review=requires_review,
        review_reason=review_reason,
    )


def normalize_lab_list(labs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalizes a list of lab dictionaries produced by structured table extraction.
    Updates the dictionaries in-place with normalized_value, normalized_unit, and canonical_name.
    """
    normalized_list: list[dict[str, Any]] = []
    for lab in labs or []:
        norm = normalize_lab_entry(
            name=str(lab.get("name") or ""),
            raw_value=lab.get("value") or lab.get("raw_value") or "",
            unit=str(lab.get("unit") or ""),
        )
        updated = dict(lab)
        updated["canonical_name"] = norm.canonical_name
        updated["normalized_value"] = norm.normalized_value
        updated["normalized_unit"] = norm.normalized_unit
        updated["operator"] = norm.operator or lab.get("operator", "")
        updated["normalization_status"] = norm.status
        updated["is_bounded"] = norm.is_bounded
        if norm.normalized_value is not None:
            # Update value to canonical normalized value for all downstream consumers
            updated["value"] = norm.normalized_value
            updated["unit"] = norm.normalized_unit
        if norm.requires_human_review:
            updated["requires_human_review"] = True
            updated["review_reason"] = norm.review_reason
        normalized_list.append(updated)
    return normalized_list
