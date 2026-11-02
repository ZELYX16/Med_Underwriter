"""
Case similarity signals shared by batch grouping and the knowledge cache.

Everything here uses only what is known *before* Agent 1 runs (the declared
profile and the submission), so groups can be proposed and approved without
spending any retrieval or LLM work.
"""
from __future__ import annotations

from typing import Any

# Coarse condition categories (substring match on the declared condition).
CATEGORIES = {
    "diabet": "metabolic",
    "thyroid": "metabolic",
    "obes": "metabolic",
    "hypertens": "cardio",
    "blood pressure": "cardio",
    "cardi": "cardio",
    "coronary": "cardio",
    "heart": "cardio",
    "cancer": "oncology",
    "tumor": "oncology",
    "renal": "renal",
    "kidney": "renal",
    "liver": "hepatic",
    "copd": "respiratory",
    "asthma": "respiratory",
    "arthritis": "musculoskeletal",
    "rheumat": "musculoskeletal",
}

AGE_BANDS = ((35, "under 35"), (50, "35-49"), (65, "50-64"))


def condition_text(condition: Any) -> str:
    if isinstance(condition, dict):
        return str(
            condition.get("condition") or condition.get("name") or ""
        ).strip()
    return str(condition or "").strip()


def condition_categories(conditions: list[Any] | None) -> tuple[str, ...]:
    found = {
        category
        for condition in conditions or []
        for term, category in CATEGORIES.items()
        if term in condition_text(condition).lower()
    }
    return tuple(sorted(found))


def age_band(age: Any) -> str:
    try:
        value = float(age)
    except (TypeError, ValueError):
        return "unknown"
    for limit, label in AGE_BANDS:
        if value < limit:
            return label
    return "65+"


def signature(
    applicant_profile: dict[str, Any],
    submission: dict[str, Any],
) -> dict[str, Any]:
    conditions = applicant_profile.get("medical_conditions") or []
    return {
        "product": str(submission.get("product") or "").strip().lower(),
        "categories": condition_categories(conditions),
        "has_conditions": bool(conditions),
        "age_band": age_band(
            applicant_profile.get("age") or submission.get("age")
        ),
    }


def group_key(
    applicant_profile: dict[str, Any],
    submission: dict[str, Any],
) -> tuple[str, tuple[str, ...], str]:
    sig = signature(applicant_profile, submission)
    return sig["product"], sig["categories"], sig["age_band"]


def describe_group(
    keys: list[tuple[str, tuple[str, ...], str]],
) -> str:
    """Plain-language reason a set of cases was grouped together."""
    product, categories, band = keys[0]
    parts = [f"same product ({product or 'unspecified'})"]
    if categories:
        parts.append("same condition categories (" + ", ".join(categories) + ")")
    else:
        parts.append("no declared conditions")
    parts.append(f"same age band ({band})")
    return "; ".join(parts)


def knowledge_key(
    kind: str,
    conditions: list[Any] | None,
    product: str | None,
) -> tuple:
    """
    Cache key for non-applicant knowledge lookups (regulatory, guidance).

    Keyed on condition *categories* so "high blood pressure" and
    "Hypertension" share one retrieval. Conditions outside every category
    fall back to their normalized names so unrelated conditions never share.
    """
    categories = condition_categories(conditions)
    uncategorized = tuple(
        sorted(
            {
                condition_text(c).lower()
                for c in conditions or []
                if condition_text(c)
                and not any(
                    term in condition_text(c).lower() for term in CATEGORIES
                )
            }
        )
    )
    return (kind, str(product or "").strip().lower(), categories, uncategorized)