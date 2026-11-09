import typing
import pytest
from app.models.state import UnderwritingState, HumanReviewInput


# ---------------------------------------------------------------------------
# ISSUE 1: State schema drops node outputs
# ---------------------------------------------------------------------------

def test_issue1_missing_state_keys():
    hints = typing.get_type_hints(UnderwritingState)
    expected_keys = [
        "reflection_consensus",
        "decision_basis",
        "underwriting_submission",
        "underwriting_knowledge_evidence",
        "agent1_metrics",
        "agent2_metrics",
        "agent3_metrics",
    ]
    for key in expected_keys:
        assert key in hints, f"UnderwritingState missing field: {key}"


def test_issue1_state_store_duplicates():
    from app.store.state_store import _STATE_DUPLICATES, slim_state
    assert "underwriting_submission" not in _STATE_DUPLICATES
    assert "actuarial_guidance" not in _STATE_DUPLICATES
    assert "scratchpad" in _STATE_DUPLICATES

    # slim_state retains top-level underwriting_submission
    sample_state = {
        "case_id": "test-123",
        "underwriting_submission": [{"doc": "sub1"}],
        "scratchpad": "drop_me",
    }
    slimmed = slim_state(sample_state)
    assert "underwriting_submission" in slimmed
    assert "scratchpad" not in slimmed


# ---------------------------------------------------------------------------
# ISSUE 2: Approve endpoint 422
# ---------------------------------------------------------------------------

def test_issue2_human_review_input_default_approved():
    inp = HumanReviewInput(reviewer="Dr. Smith", comments="Approved without conditions")
    assert inp.approved is True
    assert inp.reviewer == "Dr. Smith"


# ---------------------------------------------------------------------------
# ISSUE 3: Agent 1/router failure doesn't stop pipeline
# ---------------------------------------------------------------------------

def test_issue3_conditional_edges_routing():
    from app.orchestrator.graph import route_after_agent1, route_after_complexity

    # Agent 1 failure -> human review
    assert route_after_agent1({"final_status": "failed", "agent1_completed": False}) == "human_review"
    assert route_after_agent1({"final_status": "agent1", "agent1_completed": False}) == "human_review"
    assert route_after_agent1({"final_status": "agent1", "agent1_completed": True}) == "complexity_router"

    # Complexity router failure -> human review
    assert route_after_complexity({"final_status": "failed", "routing_completed": False}) == "human_review"
    assert route_after_complexity({"final_status": "agent2", "routing_completed": False}) == "human_review"
    assert route_after_complexity({"final_status": "agent2", "routing_completed": True}) == "agent2_risk"


# ---------------------------------------------------------------------------
# ISSUE 4: Rescore loop is a no-op
# ---------------------------------------------------------------------------

def test_issue4_agent2_accepts_reflection_findings():
    from app.agents.agent2_risk import RiskAssessmentAgent
    agent = RiskAssessmentAgent()
    findings = [{"persona": "actuary", "verdict": "flag", "finding": "Recalculate loading"}]
    res = agent.run(
        applicant_profile={"age": 35, "bmi": 23.0},
        submission={"sum_insured": 500000},
        enrichment_results={},
        routing_result={"complexity_level": "standard"},
        reflection_findings=findings,
        reflection_round=2,
    )
    assert res["reflection_round"] == 2
    assert res["reflection_findings"] == findings


def test_issue4_mar_personas_no_sticky_concerns():
    from app.agents.reflection.mar_personas import MARPersonas
    personas = MARPersonas()

    # Round 1: missing risk score raises concern
    r1 = personas._review_persona(
        persona="actuary",
        focus="actuarial soundness",
        applicant_profile={},
        risk_assessment={},
        pricing_result={"base_premium": 1000},
        recommendation="standard_acceptance",
        evidence={"sample": 1},
        previous_findings=[],
    )
    assert r1["verdict"] == "flag"
    assert "Concerns: " in r1["reasoning"]

    # Round 2: risk score is now provided -> concern should clear completely, not resurrect
    prev = [{"persona": "actuary", "verdict": "concern", "finding": r1["concerns"][0]}]
    r2 = personas._review_persona(
        persona="actuary",
        focus="actuarial soundness",
        applicant_profile={},
        risk_assessment={"overall_risk_score": 45.0},
        pricing_result={"base_premium": 1000},
        recommendation="standard_acceptance",
        evidence={"sample": 1},
        previous_findings=prev,
    )
    assert r2["verdict"] == "pass"
    assert r2["concerns"] == []
    assert r2["reasoning"] == "Review completed with no material concerns."


def test_issue4_post_reflection_router_finalizes_on_consensus():
    from app.orchestrator.graph import post_reflection_router

    # At max rounds, if consensus is reached and confidence is high, it should finalize
    state_consensus = {
        "reflection_round": 3,
        "reflection_consensus": True,
        "reflection_verdict": "pass",
        "reflection_requires_rescore": False,
        "agent2_confidence": 0.85,
    }
    assert post_reflection_router(state_consensus) == "finalize"

    # At max rounds without consensus, it should route to human_review
    state_no_consensus = {
        "reflection_round": 3,
        "reflection_consensus": False,
        "reflection_verdict": "review",
        "reflection_requires_rescore": False,
        "agent2_confidence": 0.85,
    }
    assert post_reflection_router(state_no_consensus) == "human_review"


# ---------------------------------------------------------------------------
# ISSUE 5: Declared conditions under-scored
# ---------------------------------------------------------------------------

def test_issue5_declared_condition_group_scoring():
    from app.agents.agent2_risk import RiskAssessmentAgent
    agent = RiskAssessmentAgent()

    # A declared respiratory condition with routine controlled tier vs serious tier
    features_routine = {
        "age": 35, "bmi": 22.0, "conditions": [{"condition": "Asthma", "group": "respiratory"}],
        "medications": [], "hospitalizations": [], "claims": [], "coverage_gaps": [],
        "tier_by_group": {"respiratory": {"tier": "routine", "control": "controlled", "label": "respiratory"}},
        "undeclared_conditions": [],
    }
    risk_routine = agent._calculate_risk(features_routine)

    features_serious = {
        "age": 35, "bmi": 22.0, "conditions": [{"condition": "Asthma", "group": "respiratory"}],
        "medications": [], "hospitalizations": [], "claims": [], "coverage_gaps": [],
        "tier_by_group": {"respiratory": {"tier": "serious", "control": "poor", "label": "respiratory", "reasons": ["Severe exacerbation"]}},
        "undeclared_conditions": [],
    }
    risk_serious = agent._calculate_risk(features_serious)

    # Serious tier must score significantly higher than routine tier (tier bonus applied)
    assert risk_serious["medical_risk_score"] > risk_routine["medical_risk_score"]
    assert risk_serious["medical_risk_score"] - risk_routine["medical_risk_score"] >= 10


# ---------------------------------------------------------------------------
# ISSUE 6: Retrieval returns empty/collapsed results
# ---------------------------------------------------------------------------

def test_issue6_deduplication_preserves_distinct_chunks():
    from app.rag.hybrid_rag import HybridRAG
    from app.rag.crag import CRAG

    # Multiple distinct chunks from the same document must NOT be collapsed
    chunks = [
        {"document_id": "DOC-101", "metadata": {"document_id": "DOC-101", "chunk_index": 0}, "content": "Chunk 0"},
        {"document_id": "DOC-101", "metadata": {"document_id": "DOC-101", "chunk_index": 1}, "content": "Chunk 1"},
        {"document_id": "DOC-101", "metadata": {"document_id": "DOC-101", "chunk_index": 2}, "content": "Chunk 2"},
    ]
    unique_hybrid = HybridRAG._deduplicate(chunks)
    assert len(unique_hybrid) == 3

    unique_crag = CRAG._deduplicate(chunks)
    assert len(unique_crag) == 3

    # Duplicate chunks with identical index should be deduplicated
    dup_chunks = [
        {"document_id": "DOC-101", "metadata": {"document_id": "DOC-101", "chunk_index": 0}, "content": "Chunk 0"},
        {"document_id": "DOC-101", "metadata": {"document_id": "DOC-101", "chunk_index": 0}, "content": "Chunk 0 copy"},
    ]
    assert len(HybridRAG._deduplicate(dup_chunks)) == 1


# ---------------------------------------------------------------------------
# ISSUE 7: Live submit race
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_issue7_live_submit_rejects_already_processing():
    from fastapi import HTTPException
    from app.api.live_routes import submit
    from unittest.mock import MagicMock, patch

    mock_session = {
        "status": "processing",
        "applicant_id": "APP-1",
        "case_id": "UW-1",
        "form": {},
        "documents": [],
    }

    with patch("app.api.live_routes._session", return_value=mock_session):
        with pytest.raises(HTTPException) as exc_info:
            await submit("token-123", background=MagicMock())
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# ISSUE 8: Live-intake conditions not recognised
# ---------------------------------------------------------------------------

def test_issue8_catalogue_conditions_mapped_and_declared():
    from app.services.intake import CONDITIONS, to_profile_submission
    from app.services.medical_groups import declared_groups, text_group

    # Verify text_group recognises all condition clinical terms
    for c in CONDITIONS:
        clinical = c["clinical"]
        grp = text_group(clinical)
        assert grp is not None, f"text_group failed to recognise clinical term '{clinical}'"

    # Verify to_profile_submission carries group id through
    sample_form = {
        "conditions": [
            {"key": "bp", "label": "High blood pressure", "group": "hypertension", "answers": {}},
            {"key": "asthma", "label": "Asthma or breathing problem", "group": "respiratory", "answers": {}},
        ],
        "name": "Jane Doe",
        "dob": "1990-05-15",
        "sex": "F",
        "product": "MedShield Essential",
        "sum_insured": 500000,
        "consent": True,
    }
    profile, submission = to_profile_submission("APP-99", sample_form)
    med_conds = profile["medical_conditions"]
    assert len(med_conds) == 2
    assert med_conds[0]["group"] == "hypertension"
    assert med_conds[1]["group"] == "respiratory"

    # declared_groups recovers the groups directly
    recovered = declared_groups(med_conds)
    assert "hypertension" in recovered
    assert "respiratory" in recovered
