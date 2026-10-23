"""
Deterministic fraud-risk indicators.

Pure rules over data the pipeline already holds (declared profile, claims,
retrieved applicant evidence). No LLM call and no extra retrieval, so it
adds no tokens and ~milliseconds of latency.

The score is an *indicator for a human*, never an automatic decline: every
flag names the evidence behind it, and a high score routes the case to
human review.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

# keyword -> label. Matched against retrieved applicant evidence text to
# find conditions the applicant did not declare.
_CONDITION_TERMS: dict[str, str] = {
    "diabetes": "diabetes",
    "hypertension": "hypertension",
    "coronary": "coronary disease",
    "cardiac": "cardiac condition",
    "heart disease": "heart disease",
    "cancer": "cancer",
    "renal": "renal disease",
    "kidney": "kidney disease",
    "liver": "liver disease",
    "copd": "COPD",
    "asthma": "asthma",
    "rheumatoid": "rheumatoid arthritis",
    "hypothyroid": "hypothyroidism",
}

_NEGATION = re.compile(
    r"\b(no|not|without|denies|negative for|ruled out|family history of)\b"
    r"[^.\n]{0,40}$",
    re.IGNORECASE,
)

_WEIGHTS = {
    "undeclared_condition": 20,  # per condition, capped below
    "undeclared_smoker": 25,
    "claim_frequency": 15,
    "recent_claim_cluster": 15,
    "duplicate_claim": 25,
    "claim_to_sum_insured": 15,
    "sum_insured_outlier": 15,
}


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("content") or item.get("text") or "")
    return str(item or "")


def _mentions(text: str, term: str) -> bool:
    """True if `term` appears in an affirmative (non-negated) context."""
    for match in re.finditer(re.escape(term), text, re.IGNORECASE):
        before = text[max(0, match.start() - 60): match.start()]
        if not _NEGATION.search(before):
            return True
    return False


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def assess_fraud(
    applicant_profile: dict[str, Any],
    submission: dict[str, Any],
    features: dict[str, Any],
    high_sum_insured: float = 5_000_000.0,
) -> dict[str, Any]:
    flags: list[dict[str, Any]] = []

    def flag(code: str, points: int, detail: str) -> None:
        flags.append({"code": code, "points": points, "detail": detail})

    declared = " ".join(
        str(c).lower()
        for c in (
            list(features.get("conditions") or [])
            + list(features.get("medications") or [])
        )
    )

    # 1. Non-disclosure: conditions in the applicant's own documents/claims
    #    that are absent from the declared conditions.
    evidence_text = " ".join(
        _text_of(item)
        for key in ("medical_evidence", "claims_evidence")
        for item in (features.get(key) or [])
    )
    undeclared = [
        label
        for term, label in _CONDITION_TERMS.items()
        if term not in declared
        and label.lower() not in declared
        and _mentions(evidence_text, term)
    ]
    for label in undeclared[:3]:
        flag(
            "undeclared_condition",
            _WEIGHTS["undeclared_condition"],
            f"Applicant documents mention {label}, which was not declared.",
        )

    # 2. Smoking status contradicted by documents.
    smoker = applicant_profile.get("smoker")
    declared_non_smoker = smoker in (False, "False", "false", "no", "No", 0)
    if declared_non_smoker and re.search(
        r"\b(current smoker|smokes|tobacco use|cigarette)\b",
        evidence_text,
        re.IGNORECASE,
    ):
        if not _mentions(evidence_text, "non-smoker") and not re.search(
            r"\b(non[- ]?smoker|never smoked|quit)\b",
            evidence_text,
            re.IGNORECASE,
        ):
            flag(
                "undeclared_smoker",
                _WEIGHTS["undeclared_smoker"],
                "Applicant declared non-smoker but documents indicate "
                "tobacco use.",
            )

    # 3. Claim patterns.
    claims = [c for c in (features.get("claims") or []) if isinstance(c, dict)]
    claim_count = int(features.get("claim_count", len(claims)) or 0)

    if claim_count >= 4:
        flag(
            "claim_frequency",
            _WEIGHTS["claim_frequency"],
            f"{claim_count} prior claims is unusually frequent.",
        )

    dates = [
        str(c.get("claim_date") or c.get("date") or c.get("admission_date") or "")[:7]
        for c in claims
    ]
    month_counts = Counter(d for d in dates if d)
    if month_counts and max(month_counts.values()) >= 2:
        month = max(month_counts, key=month_counts.get)
        flag(
            "recent_claim_cluster",
            _WEIGHTS["recent_claim_cluster"],
            f"Multiple claims fall in the same month ({month}).",
        )

    signatures = Counter(
        (
            str(c.get("claim_date") or c.get("date") or ""),
            str(c.get("amount") or c.get("claim_amount") or ""),
        )
        for c in claims
        if c.get("amount") or c.get("claim_amount")
    )
    if any(count > 1 for count in signatures.values()):
        flag(
            "duplicate_claim",
            _WEIGHTS["duplicate_claim"],
            "Two claims share the same date and amount.",
        )

    sum_insured = _num(features.get("sum_insured"))
    claimed = sum(
        _num(c.get("amount") or c.get("claim_amount")) for c in claims
    )
    if sum_insured > 0 and claimed > 0.5 * sum_insured:
        flag(
            "claim_to_sum_insured",
            _WEIGHTS["claim_to_sum_insured"],
            "Prior claimed amounts exceed half of the requested sum insured.",
        )

    # 4. Large cover requested alongside heavy medical history.
    if sum_insured >= high_sum_insured and int(
        features.get("condition_count", 0) or 0
    ) >= 2:
        flag(
            "sum_insured_outlier",
            _WEIGHTS["sum_insured_outlier"],
            "High sum insured requested with multiple medical conditions.",
        )

    score = float(min(100, sum(f["points"] for f in flags)))
    level = "high" if score >= 60 else "medium" if score >= 30 else "low"

    return {
        "fraud_risk_score": score,
        "fraud_risk_level": level,
        "fraud_flags": flags,
    }