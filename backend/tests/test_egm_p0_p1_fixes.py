import pytest
from app.services.text_match import has_affirmed_term, has_term
from app.agents.fraud import assess_fraud
from app.agents.agent2_risk import RiskAssessmentAgent
from app.services.intake import selected_conditions


def test_text_match_non_smoker_negation():
    # 1. Hyphenated non-smoker
    assert not has_affirmed_term(
        "Patient is a non-smoker with no history of tobacco use.",
        ["current smoker", "smoker", "tobacco use"],
        negations=["non-smoker", "nonsmoker", "never smoked", "quit"],
    )

    # 2. Spaced non smoker
    assert not has_affirmed_term(
        "Patient non smoker, denies tobacco.",
        ["current smoker", "smoker", "tobacco use"],
        negations=["non-smoker", "nonsmoker", "never smoked", "quit"],
    )

    # 3. Confirmed active smoker returns True
    assert has_affirmed_term(
        "Patient is a current smoker, 1 pack per day.",
        ["current smoker", "smoker", "tobacco use"],
        negations=["non-smoker", "nonsmoker", "never smoked", "quit"],
    )


def test_duplicate_claim_distinct_ids():
    records = [
        {"claim_id": "CLM-001", "provider": "Apollo Hospital", "event_date": "2024-05-10", "approved": 25000.0},
        {"claim_id": "CLM-002", "provider": "Apollo Hospital", "event_date": "2024-05-10", "approved": 25000.0},
    ]
    features = {"structured": {"available": True, "claim_records": records, "claims": records}}
    result = assess_fraud(
        applicant_profile={"name": "Test"},
        submission={"sum_insured": 500000},
        features=features,
    )
    flag_codes = [f["code"] for f in result.get("fraud_flags", [])]
    assert "duplicate_claim" in flag_codes, f"Expected duplicate_claim in {flag_codes}"


def test_kidney_stones_precedence_weight():
    agent = RiskAssessmentAgent()
    features = {
        "age": 25,
        "bmi": 22.0,
        "conditions": [{"condition": "Kidney stones", "group": "urinary_calculi"}],
        "medications": [],
        "hospitalizations": [],
        "claims": [],
        "coverage_gaps": [],
        "evidence_gaps": [],
        "tier_by_group": {"urinary_calculi": {"tier": "routine", "control": "controlled", "label": "Kidney Stones"}},
    }
    risk = agent._calculate_risk(features)
    # Baseline age (3.0) + urinary_calculi (6.0 * 0.5 controlled = 3.0) = 6.0
    # Prior to fix, substring 'kidney' (18.0 * 0.5 = 9.0) yielded 12.0
    assert risk["medical_risk_score"] == 6.0, f"Expected 6.0 medical score for controlled urinary calculi, got {risk['medical_risk_score']}"


def test_intake_kidney_disease_mapping():
    form_stones = {
        "conditions": [{"key": "kidney", "answers": {"kind": "Kidney stones"}}]
    }
    conds_stones = selected_conditions(form_stones)
    assert conds_stones[0]["group"] == "urinary_calculi"

    form_disease = {
        "conditions": [{"key": "kidney", "answers": {"kind": "Kidney disease"}}]
    }
    conds_disease = selected_conditions(form_disease)
    assert conds_disease[0]["group"] == "renal"
    assert conds_disease[0]["clinical"] == "Chronic kidney disease"
