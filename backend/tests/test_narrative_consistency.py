import pytest
from app.agents.agent2_risk import RiskAssessmentAgent

def test_narrative_consistency_rejects_contradictory_decision():
    agent = RiskAssessmentAgent()
    features = {"claim_count": 0}
    risk = {"coverage_gap_score": 0.0}
    pricing = {"loading_percentage": 0.0}

    # Deterministic recommendation is standard acceptance, but LLM text claims declined
    reasoning_contradiction = (
        "Based on the applicant's medical history, the application has been declined due to "
        "elevated risk factors."
    )
    is_valid = agent._reasoning_is_consistent(
        reasoning=reasoning_contradiction,
        features=features,
        risk=risk,
        recommendation="standard_acceptance",
        pricing=pricing,
    )
    assert is_valid is False

def test_narrative_consistency_rejects_contradictory_loading():
    agent = RiskAssessmentAgent()
    features = {"claim_count": 0}
    risk = {"coverage_gap_score": 0.0}
    
    # Zero loading in pricing, but LLM text claims 20% loading
    pricing_zero = {"loading_percentage": 0.0}
    reasoning_loading = "The applicant is approved with a 20% premium loading applied."
    assert agent._reasoning_is_consistent(
        reasoning=reasoning_loading,
        features=features,
        risk=risk,
        recommendation="standard_acceptance",
        pricing=pricing_zero,
    ) is False

def test_narrative_consistency_accepts_valid_explanation():
    agent = RiskAssessmentAgent()
    features = {"claim_count": 0}
    risk = {"coverage_gap_score": 0.0}
    pricing = {"loading_percentage": 15.0}

    valid_reasoning = (
        "The applicant is accepted with an appropriate 15% loading due to controlled hypertension. "
        "No prior hospitalizations were noted."
    )
    assert agent._reasoning_is_consistent(
        reasoning=valid_reasoning,
        features=features,
        risk=risk,
        recommendation="assisted_review",
        pricing=pricing,
    ) is True
