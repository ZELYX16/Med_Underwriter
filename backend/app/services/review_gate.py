"""
Centralized Underwriting Review Gate Service.
Single Source of Truth for determining whether an underwriting case requires human review.
Evaluates risk thresholds, fraud flags, security quarantine, constitutional flags, and reflection verdicts.
"""
from __future__ import annotations

from typing import Any
from app.config import settings

HUMAN_REVIEW_MEDICAL_RISK_THRESHOLD = 80.0
HUMAN_REVIEW_OVERALL_RISK_THRESHOLD = 70.0
HUMAN_REVIEW_CONFIDENCE_THRESHOLD = 0.70


def evaluate_review_gate(state: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluates all review gating rules across medical risk, overall risk, confidence,
    fraud/discrepancies, security, and compliance.
    
    Returns:
        {
            "requires_human_review": bool,
            "reasons": list[str],
            "review_level": "straight_through" | "assisted_review" | "full_review",
            "blocking_reasons": list[str],
        }
    """
    reasons: list[str] = []
    blocking_reasons: list[str] = []

    medical_risk = float(state.get("medical_risk_score", 0.0) or 0.0)
    overall_risk = float(state.get("overall_risk_score", 0.0) or 0.0)
    confidence = float(state.get("agent2_confidence", 0.0) or 0.0)

    # 1. Risk thresholds
    if medical_risk >= HUMAN_REVIEW_MEDICAL_RISK_THRESHOLD:
        msg = f"Medical risk score {medical_risk:.2f} is at or above {HUMAN_REVIEW_MEDICAL_RISK_THRESHOLD:.0f}."
        reasons.append(msg)
        blocking_reasons.append(msg)

    if overall_risk >= HUMAN_REVIEW_OVERALL_RISK_THRESHOLD:
        msg = f"Overall risk score {overall_risk:.2f} is at or above {HUMAN_REVIEW_OVERALL_RISK_THRESHOLD:.0f}."
        reasons.append(msg)
        blocking_reasons.append(msg)

    if 0 < confidence < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        msg = f"Agent 2 confidence {confidence:.2f} is below {HUMAN_REVIEW_CONFIDENCE_THRESHOLD:.2f}."
        reasons.append(msg)

    # 2. Fraud & discrepancy thresholds
    fraud_score = float(state.get("fraud_risk_score", 0.0) or 0.0)
    fraud_thresh = getattr(settings, "fraud_review_threshold", 50.0)
    if fraud_score >= fraud_thresh:
        msg = f"Discrepancy score {fraud_score:.0f} is at or above {fraud_thresh:.0f}; verify the flagged items."
        reasons.append(msg)
        blocking_reasons.append(msg)

    # 3. Mandatory & security reasons
    for reason in state.get("mandatory_review_reasons") or []:
        r_str = str(reason)
        if r_str not in reasons:
            reasons.append(r_str)
            blocking_reasons.append(r_str)

    for reason in state.get("security_review_reasons") or []:
        r_str = f"Security review: {reason}"
        if r_str not in reasons:
            reasons.append(r_str)
            blocking_reasons.append(r_str)

    # 4. Constitutional / fairness checks
    for key, value in state.items():
        if key.startswith("constitutional_") and isinstance(value, dict):
            if str(value.get("status", "")).lower() == "flag":
                msg = f"Constitutional flag: {value.get('detail', key)}"
                if msg not in reasons:
                    reasons.append(msg)
                    blocking_reasons.append(msg)

    # 5. Reflection verdict & consensus
    verdict = str(state.get("reflection_verdict", "")).strip().lower()
    if verdict in {"fail", "failed", "review", "escalate"}:
        msg = f"Agent 3 reflection verdict '{verdict}' requires manual review."
        if msg not in reasons:
            reasons.append(msg)

    max_rounds = getattr(settings, "max_reflection_rounds", 3)
    if state.get("reflection_round", 0) >= max_rounds and not state.get("reflection_consensus", False):
        msg = "Agent 3 did not reach consensus within maximum reflection rounds."
        if msg not in reasons:
            reasons.append(msg)

    # 6. Document defects & unparsed files
    defects = state.get("document_defects") or []
    unparsed = state.get("unparsed_files") or []
    if defects or unparsed:
        defect_names = [d["file_name"] if isinstance(d, dict) else str(d) for d in defects] or [str(u) for u in unparsed]
        msg = f"Document defect: Unreadable or scanned document detected ({', '.join(defect_names)}). Manual verification required."
        if msg not in reasons:
            reasons.append(msg)
            blocking_reasons.append(msg)

    # 7. Explicit human review requests from upstream agents
    if state.get("require_human_escalation") or state.get("require_human_review"):
        for r in state.get("human_review_reasons") or []:
            r_str = str(r)
            if r_str not in reasons:
                reasons.append(r_str)

    requires_review = bool(reasons or blocking_reasons)

    if blocking_reasons:
        level = "full_review"
    elif requires_review:
        level = "assisted_review"
    else:
        level = "straight_through"

    return {
        "requires_human_review": requires_review,
        "reasons": reasons,
        "review_level": level,
        "blocking_reasons": blocking_reasons,
    }
