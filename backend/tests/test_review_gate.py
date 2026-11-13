import pytest
from app.services.review_gate import (
    evaluate_review_gate,
    HUMAN_REVIEW_MEDICAL_RISK_THRESHOLD,
    HUMAN_REVIEW_OVERALL_RISK_THRESHOLD,
    HUMAN_REVIEW_CONFIDENCE_THRESHOLD,
)


def test_review_gate_clean_straight_through():
    state = {
        "medical_risk_score": 15.0,
        "overall_risk_score": 25.0,
        "agent2_confidence": 0.85,
        "fraud_risk_score": 0.0,
        "reflection_verdict": "pass",
        "reflection_consensus": True,
        "reflection_round": 1,
    }
    gate = evaluate_review_gate(state)
    assert not gate["requires_human_review"]
    assert gate["review_level"] == "straight_through"
    assert len(gate["reasons"]) == 0
    assert len(gate["blocking_reasons"]) == 0


def test_review_gate_high_medical_risk():
    state = {
        "medical_risk_score": 85.0,
        "overall_risk_score": 60.0,
        "agent2_confidence": 0.85,
    }
    gate = evaluate_review_gate(state)
    assert gate["requires_human_review"]
    assert gate["review_level"] == "full_review"
    assert any("Medical risk score" in r for r in gate["reasons"])
    assert any("Medical risk score" in r for r in gate["blocking_reasons"])


def test_review_gate_high_overall_risk():
    state = {
        "medical_risk_score": 65.0,
        "overall_risk_score": 75.0,
        "agent2_confidence": 0.85,
    }
    gate = evaluate_review_gate(state)
    assert gate["requires_human_review"]
    assert gate["review_level"] == "full_review"
    assert any("Overall risk score" in r for r in gate["reasons"])


def test_review_gate_low_confidence():
    state = {
        "medical_risk_score": 30.0,
        "overall_risk_score": 40.0,
        "agent2_confidence": 0.60,
    }
    gate = evaluate_review_gate(state)
    assert gate["requires_human_review"]
    assert gate["review_level"] == "assisted_review"
    assert any("confidence" in r.lower() for r in gate["reasons"])


def test_review_gate_fraud_discrepancy():
    state = {
        "medical_risk_score": 20.0,
        "overall_risk_score": 30.0,
        "agent2_confidence": 0.90,
        "fraud_risk_score": 65.0,
    }
    gate = evaluate_review_gate(state)
    assert gate["requires_human_review"]
    assert gate["review_level"] == "full_review"
    assert any("Discrepancy score" in r for r in gate["reasons"])


def test_review_gate_mandatory_and_security():
    state = {
        "medical_risk_score": 20.0,
        "overall_risk_score": 30.0,
        "mandatory_review_reasons": ["Unresolved hospital discharge summary"],
        "security_review_reasons": ["Aadhaar photo mismatch"],
    }
    gate = evaluate_review_gate(state)
    assert gate["requires_human_review"]
    assert gate["review_level"] == "full_review"
    assert "Unresolved hospital discharge summary" in gate["reasons"]
    assert any("Security review:" in r for r in gate["reasons"])


def test_review_gate_constitutional_flag():
    state = {
        "medical_risk_score": 20.0,
        "overall_risk_score": 30.0,
        "constitutional_fairness": {"status": "flag", "detail": "Disproportionate loading for age group"},
    }
    gate = evaluate_review_gate(state)
    assert gate["requires_human_review"]
    assert any("Constitutional flag" in r for r in gate["reasons"])


def test_review_gate_reflection_verdict_fail():
    state = {
        "medical_risk_score": 20.0,
        "overall_risk_score": 30.0,
        "reflection_verdict": "review",
    }
    gate = evaluate_review_gate(state)
    assert gate["requires_human_review"]
    assert any("reflection verdict 'review'" in r for r in gate["reasons"])
