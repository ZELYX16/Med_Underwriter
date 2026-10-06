from datetime import datetime, timezone
from typing import Any, TypedDict

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UnderwritingState(TypedDict, total=False):
    # Case and submission
    case_id: str
    created_at: str
    updated_at: str
    applicant_profile: dict[str, Any]
    submission: dict[str, Any]
    raw_request: dict[str, Any]

    # Agent 1 - Submission Intelligence
    medical_evidence: list[dict[str, Any]]
    claims_evidence: list[dict[str, Any]]
    policy_evidence: list[dict[str, Any]]
    regulatory_evidence: list[dict[str, Any]]
    underwriting_evidence: list[dict[str, Any]]
    medical_knowledge: list[dict[str, Any]]
    coverage_gaps: list[dict[str, Any]]

    agent1_enrichment: dict[str, Any]
    agent1_completed: bool

    # Complexity routing
    complexity_level: str
    complexity_reasons: list[str]
    routing_strategy: str
    routing_completed: bool

    # Agent 2 - Risk Assessment and Pricing
    risk_assessment: dict[str, Any]
    medical_risk_score: float
    claims_risk_score: float
    overall_risk_score: float

    # Pricing
    pricing_result: dict[str, Any]
    base_premium: float
    loading_percentage: float
    final_premium: float

    # Agent 2 decision
    agent2_recommendation: str
    agent2_confidence: float
    agent2_reasoning: str
    agent2_completed: bool

    # Confidence gate
    confidence_gate: str
    reflection_required: bool

    # Agent 3 - Reflection
    reflection_type: str
    reflection_personas: list[str]
    reflection_round: int

    constitutional_medical_accuracy: dict[str, Any]
    constitutional_actuarial_soundness: dict[str, Any]
    constitutional_regulatory_compliance: dict[str, Any]
    constitutional_fairness: dict[str, Any]
    constitutional_explainability: dict[str, Any]

    reflection_findings: list[dict[str, Any]]
    reflection_verdict: str
    agent3_completed: bool

    # Human review
    require_human_escalation: bool
    human_review_reason: str
    human_review_status: str
    human_reviewed_by: str
    human_review_comments: str
    human_approved: bool

    # Final decision
    final_decision: str
    final_status: str
    final_recommendation: str
    final_confidence: float

    # Workflow and audit
    workflow_trace: list[dict[str, Any]]
    audit_trail: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    # Performance metrics
    timing: dict[str, float]
    token_usage: dict[str, int]


class UnderwriteInput(BaseModel):
    applicant_profile: dict[str, Any] = Field(default_factory=dict)
    submission: dict[str, Any] = Field(default_factory=dict)


class UnderwriteResult(BaseModel):
    case_id: str

    status: str = "completed"

    final_decision: str = ""
    final_recommendation: str = ""
    final_confidence: float = 0.0

    complexity_level: str = ""
    routing_strategy: str = ""

    overall_risk_score: float = 0.0
    medical_risk_score: float = 0.0
    claims_risk_score: float = 0.0

    base_premium: float = 0.0
    loading_percentage: float = 0.0
    final_premium: float = 0.0

    require_human_escalation: bool = False

    agent1_completed: bool = False
    agent2_completed: bool = False
    agent3_completed: bool = False

    errors: list[dict[str, Any]] = Field(default_factory=list)


class HumanReviewInput(BaseModel):
    approved: bool
    reviewer: str
    comments: str = ""