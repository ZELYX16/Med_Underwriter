"""
Layered confidence, graded outcomes, reason codes and the applicant-facing message.

Confidence is reported in layers (evidence, margin to a decision threshold,
consistency, extraction) instead of one number. The review gate itself stays
rule-based; the grade only says *how much* human attention a case needs:

  straight_through  completes automatically
  assisted_review   a person confirms a close call (one look, not a full review)
  full_review       a person reviews the blocking reasons
  senior_referral   mandatory-review reasons, security or a high discrepancy score
"""
from __future__ import annotations

import re
from typing import Any

_EDGES = (30.0, 45.0, 60.0, 70.0)  # pricing / recommendation band edges

_CODES = [
    (r"Security review|excluded from analysis|quarantine", "SECURITY_QUARANTINE", "Compliance",
     "Review the excluded input before relying on the case."),
    (r"Serious condition not declared|Mandatory review", "SERIOUS_UNDECLARED", "Medical officer",
     "Confirm the condition with the applicant and obtain records."),
    (r"does not match the proposal|identity", "IDENTITY_MISMATCH", "Underwriter",
     "Confirm identity and request the correct document."),
    (r"Verification required", "VERIFY_EVIDENCE", "Underwriter",
     "Request the missing items from the applicant (use Send back)."),
    (r"Discrepancy score", "DISCREPANCY_SCORE", "Senior underwriter", "Verify each listed discrepancy."),
    (r"confidence", "LOW_CONFIDENCE", "Underwriter", "Review the evidence gaps and request what is missing."),
    (r"risk score", "HIGH_RISK", "Senior underwriter", "Review risk drivers and pricing."),
    (r"constitutional|reflection|consensus|LLM critique", "REFLECTION_FLAG", "Underwriter", "Review the reflection findings."),
]


def layered_confidence(*, evidence: float, overall_risk: float, discrepancy_score: float, scanned_docs: int = 0) -> dict[str, float]:
    distance = min(abs(overall_risk - e) for e in _EDGES)
    margin = round(min(1.0, distance / 5.0), 2)
    consistency = round(max(0.0, 1.0 - discrepancy_score / 100.0), 2)
    extraction = 1.0 if not scanned_docs else 0.8
    return {
        "evidence": round(evidence, 2),
        "margin": margin,
        "consistency": consistency,
        "extraction": extraction,
        "overall": round(min(evidence, consistency, extraction, 0.5 + 0.5 * margin), 2),
    }


def reason_codes(reasons: list[str]) -> list[dict[str, str]]:
    out = []
    for reason in reasons:
        for pattern, code, owner, action in _CODES:
            if re.search(pattern, reason, re.IGNORECASE):
                out.append({"code": code, "text": reason, "owner": owner, "action": action})
                break
        else:
            out.append({"code": "OTHER", "text": reason, "owner": "Underwriter", "action": "Review the case."})
    return out


def grade(
    *,
    blocking: list[str],
    mandatory: list[str],
    security: list[str],
    discrepancy_score: float,
    layers: dict[str, float],
    sum_insured: Any,
    recommendation: str = "",
) -> str:
    from app.services.extraction import parse_number

    if mandatory or security or discrepancy_score >= 60:
        return "senior_referral"
    if blocking:
        return "full_review"
    rec = str(recommendation or "").strip().lower()
    if rec in {"decline", "postpone"}:
        return "full_review"
    if rec in {"accept_with_exclusion", "referred_to_underwriter", "manual_review"}:
        return "assisted_review"
    close = layers.get("margin", 1.0) < 0.4
    si_num = parse_number(sum_insured)
    if close and (si_num >= 1_000_000 or layers.get("evidence", 1.0) < 0.75):
        return "assisted_review"
    return "straight_through"


def customer_message(level: str, recommendation: str, loading: float, missing: list[str]) -> dict[str, Any]:
    """What the applicant is told. No scores, flags or internal reasons."""
    ask = [f"Please send: {m}" for m in missing]
    rec = str(recommendation or "").strip().lower()

    if rec == "decline":
        headline = "Application Declined"
        reason = "Based on our underwriting assessment and medical guidelines, we are unable to offer coverage at this time."
    elif rec == "postpone":
        headline = "Application Postponed"
        reason = "Coverage cannot be offered at this time. You may reapply following the waiting period or after medical status is stabilized."
    elif rec == "accept_with_exclusion":
        headline = "Application Approved with Specific Exclusions"
        reason = "Your application has been approved subject to specific policy exclusions based on your medical history."
    elif level == "straight_through" or rec in {"standard_acceptance", "accept_with_loading"}:
        if (loading and loading > 0) or rec == "accept_with_loading":
            headline = "Your application is approved with an additional charge"
            reason = (f"Based on the health details you gave us, your premium includes an additional "
                      f"charge of {loading:g}% over the standard rate.")
        else:
            headline = "Your application is approved"
            reason = "Based on the details you gave us, you qualify for the standard rate."
    else:
        headline = "Our underwriting team is reviewing your application"
        reason = ("A member of our team will look at your application personally. This is normal when "
                  "health details need a closer look and does not mean it has been declined.")
        if level == "assisted_review":
            reason = "A member of our team is confirming a final check before we send your decision."

    return {"headline": headline, "reason": reason, "next_steps": ask or ["Nothing is needed from you right now."]}


def build_decision_package(
    *,
    confidence_layers: dict[str, float],
    mandatory_reasons: list[str],
    security_reasons: list[str],
    verification_items: list[dict[str, Any]],
    compliance_report: dict[str, Any],
    discrepancy_score: float,
    sum_insured: float | None,
    recommendation: str,
    loading_percentage: float,
) -> dict[str, Any]:
    """Build a traceable review grade without changing the actuarial recommendation.

    This is a routing aid, not an autonomous acceptance/decline authority.
    Any mandatory/security issue or material evidence gap prevents straight-through.
    """
    mandatory = list(mandatory_reasons or [])
    security = list(security_reasons or [])
    material = [v for v in (verification_items or []) if v.get("material")]
    blocking = [str(v.get("action") or v.get("domain") or "Material evidence gap") for v in material]

    rules = (compliance_report or {}).get("rules") or []
    failed_rules = [
        str(r.get("title") or r.get("name") or r.get("code") or "Compliance check")
        for r in rules
        if str(r.get("status", "")).lower() in {"fail", "needs_info", "attention"}
    ]
    blocking.extend(f"Compliance: {name}" for name in failed_rules)

    level = grade(
        blocking=blocking,
        mandatory=mandatory,
        security=security,
        discrepancy_score=float(discrepancy_score or 0.0),
        layers=confidence_layers or {},
        sum_insured=sum_insured,
        recommendation=recommendation,
    )
    reasons = mandatory + security + blocking
    if float(discrepancy_score or 0.0) >= 60:
        reasons.append(f"Discrepancy score {float(discrepancy_score):.1f} requires senior review.")
    codes = reason_codes(reasons)
    customer = customer_message(
        level,
        recommendation,
        float(loading_percentage or 0.0),
        [str(v.get("action")) for v in material if v.get("action")],
    )
    return {
        "decision_level": level,
        "reason_codes": codes,
        "blocking_reasons": blocking,
        "mandatory_review_reasons": mandatory,
        "security_review_reasons": security,
        "material_verification_items": material,
        "compliance_attention": failed_rules,
        "customer_message": customer,
        "requires_human_review": level != "straight_through",
    }
