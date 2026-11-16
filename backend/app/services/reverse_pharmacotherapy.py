"""
Reverse Pharmacotherapy Service: Infers underlying clinical pathology from
prescribed medications, detects undeclared chronic ailments, and evaluates
contextual exceptions (e.g. Metformin in females for PCOS/insulin resistance).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.models.state import MedicationVerificationItem
from app.services.medical_groups import declared_groups, text_group

_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "medication_inference_map.json"
_MED_MAP: dict[str, Any] | None = None


def get_medication_map() -> dict[str, Any]:
    global _MED_MAP
    if _MED_MAP is None:
        if _MAP_PATH.exists():
            with open(_MAP_PATH, "r", encoding="utf-8") as f:
                _MED_MAP = json.load(f)
        else:
            _MED_MAP = {"drugs": {}}
    return _MED_MAP


def normalize_drug_name(name: str) -> str:
    """Normalize drug name by stripping dosage, units, and non-alphanumeric chars."""
    clean = name.lower().strip()
    clean = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|g|ml|iu)\b", "", clean)
    clean = re.sub(r"[^a-z0-9\s]", " ", clean)
    return " ".join(clean.split())


def find_drug_entry(raw_name: str, drug_dict: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    norm = normalize_drug_name(raw_name)
    tokens = norm.split()

    # Direct match on normalized name or generic_name
    for key, data in drug_dict.items():
        if key == norm or key in tokens or norm in key:
            return key, data
        generic = data.get("generic_name", "").lower()
        if generic and (generic == norm or generic in tokens):
            return key, data

    # Check if any token matches a drug key of length >= 4
    for t in tokens:
        if len(t) >= 4 and t in drug_dict:
            return t, drug_dict[t]

    return None


def verify_medications(
    prescriptions: list[Any],
    declared_conditions: list[Any],
    applicant_sex: str = "",
    questionnaire: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """
    Verifies prescribed pharmaceutical agents against declared medical conditions.
    Returns a list of dicts serialized from MedicationVerificationItem.
    """
    data = get_medication_map()
    drug_db = data.get("drugs", {})

    dec_groups = declared_groups(declared_conditions, questionnaire)

    declared_texts: list[str] = []
    for c in declared_conditions or []:
        if isinstance(c, dict):
            declared_texts.append(" ".join(str(v) for v in c.values() if v).lower())
        else:
            declared_texts.append(str(c).lower())

    is_female = str(applicant_sex or "").strip().lower() in {"f", "female", "woman"}

    results: list[dict[str, Any]] = []
    seen_drugs: set[str] = set()

    for item in prescriptions or []:
        raw_name = ""
        if isinstance(item, dict):
            raw_name = (
                item.get("drug_name")
                or item.get("name")
                or item.get("medication")
                or item.get("prescription")
                or ""
            )
        else:
            raw_name = str(item)

        if not raw_name or raw_name.lower() in seen_drugs:
            continue

        match = find_drug_entry(raw_name, drug_db)
        if not match:
            continue

        key, drug_info = match
        seen_drugs.add(raw_name.lower())
        seen_drugs.add(key)

        inferred_group = drug_info.get("clinical_group", "")
        base_group = inferred_group.split("_")[0] if inferred_group else ""
        discrepancy_weight = int(drug_info.get("discrepancy_weight", 20))
        context_exceptions = drug_info.get("context_exceptions", [])

        is_declared = (inferred_group in dec_groups) or (base_group in dec_groups)

        context_applied = False
        context_tag = None

        if not is_declared and context_exceptions:
            pcos_keywords = {"pcos", "polycystic", "infertility", "insulin resistance", "prediabetes"}
            has_pcos_declared = any(
                any(kw in d_text for kw in pcos_keywords)
                for d_text in declared_texts
            )
            if key == "metformin" and is_female and has_pcos_declared:
                context_applied = True
                context_tag = "Metformin prescribed for PCOS/insulin resistance without declared T2D"
                is_declared = True
                discrepancy_weight = 0
            elif any(
                any(exc in d_text for exc in context_exceptions)
                for d_text in declared_texts
            ):
                context_applied = True
                context_tag = f"Context exception matched: {', '.join(context_exceptions)}"
                is_declared = True
                discrepancy_weight = 0

        score = 0 if is_declared else discrepancy_weight

        rec = MedicationVerificationItem(
            drug_name=raw_name,
            inferred_condition=inferred_group or key,
            is_declared=is_declared,
            discrepancy_score=score,
            context_exception_applied=context_applied,
            context_exception_tag=context_tag,
        )
        results.append(rec.model_dump())

    return results
