import pytest
from datetime import date, timedelta
from app.services.intake import to_profile_submission, open_items
from app.rag.structured import evaluate_document_recency, parse_date
from app.agents.agent2_risk import RiskAssessmentAgent
from app.agents.reflection.constitutional import ConstitutionalChecker


def test_height_weight_bmi_profile_submission():
    form = {
        "name": "Jane Doe",
        "dob": "1990-05-15",
        "sex": "Female",
        "height": 165.0,
        "weight": 58.0,
        "product": "MedShield",
        "sum_insured": 500000,
        "hospital_stay": "no",
        "had_claims": "no",
        "has_other_insurance": "no",
        "smoker": "no",
        "consent": True,
    }
    profile, submission = to_profile_submission("APP-TEST-HW", form)
    assert profile["height"] == 165.0
    assert profile["weight"] == 58.0
    expected_bmi = round(58.0 / ((165.0 / 100) ** 2), 1)
    assert profile["bmi"] == expected_bmi
    assert profile["height_cm"] == 165.0
    assert profile["weight_kg"] == 58.0
    assert submission["submission_date"] == date.today().isoformat()


def test_agent2_calculates_bmi_from_height_weight():
    agent = RiskAssessmentAgent()
    features = agent._extract_features(
        applicant_profile={"height": 180.0, "weight": 75.0},
        submission={},
        enrichment_results={},
    )
    expected_bmi = round(75.0 / ((180.0 / 100) ** 2), 1)
    assert features["bmi"] == expected_bmi


def test_open_items_no_clarifications_and_no_docs_later():
    form = {
        "hospital_stay": "no",
        "had_claims": "no",
        "has_other_insurance": "no",
        "smoker": "no",
        "consent": True,
        "conditions": [],
        "docs_later": ["medical_exam"],
    }
    items = open_items(form, [])
    # Any open items must NOT have kind 'clarification'
    for item in items:
        assert item.get("kind") != "clarification"
        assert not item.get("later")


def test_evaluate_document_recency():
    today = date(2026, 11, 13)
    today_str = today.isoformat()

    # <= 90 days: recent
    recent_date = (today - timedelta(days=45)).isoformat()
    r_recent = evaluate_document_recency(recent_date, today_str)
    assert r_recent["recency_status"] == "recent"
    assert r_recent["recency_days"] == 45
    assert not r_recent["is_stale"]

    # 91 - 180 days: acceptable
    acc_date = (today - timedelta(days=120)).isoformat()
    r_acc = evaluate_document_recency(acc_date, today_str)
    assert r_acc["recency_status"] == "acceptable"
    assert r_acc["recency_days"] == 120
    assert not r_acc["is_stale"]

    # > 180 days: stale
    stale_date = (today - timedelta(days=200)).isoformat()
    r_stale = evaluate_document_recency(stale_date, today_str)
    assert r_stale["recency_status"] == "stale"
    assert r_stale["recency_days"] == 200
    assert r_stale["is_stale"]

    # Unknown date
    r_unknown = evaluate_document_recency(None, today_str)
    assert r_unknown["recency_status"] == "date_unknown"
    assert not r_unknown["is_stale"]


def test_parse_date_formats():
    assert parse_date("15-May-2024") == "2024-05-15"
    assert parse_date("2024-05-15") == "2024-05-15"
    assert parse_date("15/05/2024") == "2024-05-15"
    assert parse_date("15-05-2024") == "2024-05-15"


def test_constitutional_missing_data_grounded():
    checker = ConstitutionalChecker()
    factors = ["Data missing: applicant BMI is unknown", "No claims history"]
    res = checker._medical_accuracy(
        applicant_profile={"name": "Healthy Person", "age": 30},
        risk_assessment={"risk_factors": factors, "medical_risk_score": 10},
        evidence={},
    )
    # Missing data should not be flagged as unsupported hallucination
    assert "Data missing: applicant BMI is unknown" not in res.get("details", [])
    assert res["passed"]
