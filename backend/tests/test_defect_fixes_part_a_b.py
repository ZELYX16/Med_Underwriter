import pytest
from typing import Any


def test_a1_customer_message_and_grading():
    from app.services import outcome

    # Decline must never say approved
    msg_decline = outcome.customer_message("straight_through", "decline", 0.0, [])
    assert "Declined" in msg_decline["headline"]
    assert "approved" not in msg_decline["headline"].lower()

    # Postpone
    msg_postpone = outcome.customer_message("straight_through", "postpone", 0.0, [])
    assert "Postponed" in msg_postpone["headline"]

    # Accept with exclusion
    msg_excl = outcome.customer_message("straight_through", "accept_with_exclusion", 0.0, [])
    assert "Exclusion" in msg_excl["headline"]

    # Decline grades as full_review even with no blocking items
    grade = outcome.grade(
        blocking=[], mandatory=[], security=[], discrepancy_score=0.0,
        layers={"margin": 0.8}, sum_insured=500000, recommendation="decline"
    )
    assert grade == "full_review"

    # Security quarantine precedes identity in reason_codes
    codes = outcome.reason_codes(["Security review required for identity doc"])
    assert codes[0]["code"] == "SECURITY_QUARANTINE"


def test_a4_a5_extraction_and_risk_pricing():
    from app.services.extraction import parse_number, parse_term_years
    assert parse_number("5 Lakhs") == 500000.0
    assert parse_number("Rs. 10,500.50") == 10500.5
    assert parse_number("2.5 Crore") == 25000000.0
    assert parse_term_years("3 years") == 3

    # Risk Assessment Agent loading for 3+ routine conditions
    from app.agents.agent2_risk import RiskAssessmentAgent
    agent = RiskAssessmentAgent()
    pricing = agent._calculate_pricing(
        submission={"sum_insured": 500000},
        risk={"overall_risk_score": 15.0},
        features={"sum_insured": 500000, "term_years": 1, "condition_count": 3},
    )
    assert pricing["loading_percentage"] == 10.0


def test_a6_text_matching_boundary_and_negations():
    from app.services.text_match import has_term, has_affirmed_term

    assert not has_term("applicant broadcast was normal", "cad")
    assert has_term("history of cad noted", "cad")

    assert not has_affirmed_term("denies smoking, never smoked", ["smoking", "smoker"])
    assert has_affirmed_term("current smoker, 1 pack a day", ["smoking", "smoker"])

    # QueryClassifier priority on tie
    from app.rag.query_classifier import query_classifier
    res = query_classifier.classify("medical underwriting")
    # Medical prioritized over generic underwriting on a tie
    assert res["intent"] == "medical"
    assert "medical" in res["matched_keywords"]


def test_a7_llm_critic_and_corroboration():
    from app.agents.reflection.llm_critic import LLMCritic
    critic = LLMCritic()

    # Empty concerns with 'disagree' does not downgrade to 'agree'
    parsed = critic._parse('{"verdict": "disagree", "concerns": []}')
    assert parsed["verdict"] == "disagree"
    assert len(parsed["concerns"]) > 0

    # Key order independence in fallback parser
    loaded = critic._load_json('{"verdict": "concerns", "concerns": [{"issue": "High loading", "persona": "actuary"}]}')
    assert loaded["verdict"] == "concerns"
    assert len(loaded["concerns"]) == 1
    assert loaded["concerns"][0]["persona"] == "actuary"

    # Agent3 corroboration requires topic overlap
    from app.agents.agent3_reflection import ReflectionAgent
    rule_findings = [{"persona": "compliance", "verdict": "flag", "finding": "Missing KYC document", "action": "Request KYC"}]
    # LLM concern about pricing is NOT corroborated by KYC flag
    corrob_pricing = ReflectionAgent._corroborated(
        concerns=[{"issue": "Premium too low", "action": "Increase premium"}],
        rule_findings=rule_findings,
        flag_count=1,
        risk_assessment={"overall_risk_score": 25},
        pricing_result={"loading_percentage": 0},
        fraud_flags=[],
    )
    assert not corrob_pricing

    # LLM concern about KYC is corroborated
    corrob_kyc = ReflectionAgent._corroborated(
        concerns=[{"issue": "KYC document incomplete", "action": "Request KYC"}],
        rule_findings=rule_findings,
        flag_count=1,
        risk_assessment={"overall_risk_score": 25},
        pricing_result={"loading_percentage": 0},
        fraud_flags=[],
    )
    assert corrob_kyc


def test_a9_clarification_field_aliases():
    from app.services.clarification_engine import build_clarifications

    # If applicant answered condition under 'since', do not ask diagnosis_year
    form = {
        "conditions": [
            {
                "key": "diabetes",
                "label": "Diabetes",
                "answers": {"since": "2018", "reading": "6.8"},
            }
        ],
        "clarification_answers": {},
    }
    docs = []
    questions = build_clarifications(form, docs)
    qids = [q["id"] for q in questions]
    assert "condition:diabetes:diagnosis_year" not in qids
    assert "condition:diabetes:hba1c" not in qids


def test_a10_document_pipeline_regexes():
    from app.services.document_pipeline import extract_facts, _LAB_PATTERNS

    # BP validation rejects invalid numbers
    pages = [{"page_number": 1, "text": "Blood Pressure: 12/24\nBP: 130/85 mmHg"}]
    facts = extract_facts(pages)
    bp_facts = [f for f in facts if f["fact_type"] == "blood_pressure"]
    assert len(bp_facts) == 1
    assert bp_facts[0]["value"] == "130/85 mmHg"

    # Creatinine ignores ratio
    creat_pattern = next(p for t, p, u in _LAB_PATTERNS if t == "creatinine")
    assert not creat_pattern.search("Creatinine ratio: 45 mg/dl")
    assert creat_pattern.search("Creatinine: 1.1 mg/dl")


def test_a11_severity_unit_conversions_and_negation():
    from app.services.severity import lab_value, assess_group

    # HbA1c conversion from mmol/mol
    labs = [{"name": "HbA1c", "value": "48", "unit": "mmol/mol"}]
    val = lab_value(labs, "hba1c")
    assert 6.0 <= val <= 7.0  # 48 mmol/mol is ~6.5%

    # Glucose conversion from mmol/L
    glucose_labs = [{"name": "Fasting Glucose", "value": "7.0", "unit": "mmol/L"}]
    g_val = lab_value(glucose_labs, "fasting_glucose")
    assert 120 <= g_val <= 130  # 7.0 mmol/L is ~126 mg/dL

    # Renal stage negation
    entry = assess_group("renal", text="patient has no CKD stage 3 or renal failure", icd_codes=[])
    assert entry["tier"] != "serious"


def test_a12_structured_robustness():
    from app.rag.structured import parse_amount
    assert parse_amount("5 Lakh") == 500000.0
    assert parse_amount("INR 1,20,000") == 120000.0


def test_a14_api_models_and_reflection_reset():
    from app.models.state import HumanOverrideInput
    inp = HumanOverrideInput(decision="standard_acceptance", reviewer="underwriter_1", loading_percentage=15.0)
    assert inp.loading_percentage == 15.0


def test_a15_guardrails():
    from app.security.guardrails import guardrails

    # Negation on guarantee
    out = guardrails.validate_output("This does not mean guaranteed approval.")
    assert out.allowed

    # Private key pattern
    res = guardrails.validate_prompt("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----")
    assert not res.allowed


def test_a16_sessions_mutate_empty_list():
    from app.services.sessions import SessionStore
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_sessions.db"
        store = SessionStore(db_path)
        sess = store.create("APP-1", "CASE-1")
        token = sess["token"]

        # Mutate to empty list must succeed and not retain old docs
        store.mutate_documents(token, lambda docs: [{"id": "d1"}])
        docs1 = store.get(token)["documents"]
        assert len(docs1) == 1

        store.mutate_documents(token, lambda docs: [])
        docs2 = store.get(token)["documents"]
        assert len(docs2) == 0


def test_cleanup_config_sync_and_tracer():
    from app.config import settings
    from app.orchestrator.graph import MAX_REFLECTION_ROUNDS
    assert MAX_REFLECTION_ROUNDS == settings.max_reflection_rounds

    from app.observability.langfuse_tracer import trace_context
    # trace_context must exit cleanly without RuntimeError even when exception occurs inside
    with pytest.raises(ValueError):
        with trace_context("case-123"):
            raise ValueError("Test error inside context")
