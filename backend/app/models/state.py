from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UnderwritingState(TypedDict, total=False):
    # ------------------------------------------------------------------
    # Case and intake
    # ------------------------------------------------------------------
    case_id: str
    created_at: str
    updated_at: str

    applicant_profile: dict[str, Any]
    submission: dict[str, Any]
    raw_request: dict[str, Any]

    # ------------------------------------------------------------------
    # Agent 1 - Submission Intelligence
    # ------------------------------------------------------------------
    medical_evidence: list[dict[str, Any]]
    claims_evidence: list[dict[str, Any]]
    policy_evidence: list[dict[str, Any]]
    regulatory_evidence: list[dict[str, Any]]
    underwriting_evidence: list[dict[str, Any]]
    medical_knowledge: list[dict[str, Any]]
    coverage_gaps: list[dict[str, Any]]
    confirmed_coverage_gaps: list[dict[str, Any]]
    evidence_gaps: list[dict[str, Any]]
    evidence_completeness: float

    agent1_enrichment: dict[str, Any]
    agent1_completed: bool

    # ------------------------------------------------------------------
    # Complexity routing
    # ------------------------------------------------------------------
    complexity_level: str
    complexity_reasons: list[str]
    routing_strategy: str
    routing_completed: bool

    # ------------------------------------------------------------------
    # Agent 2 - Risk Assessment and Pricing
    # ------------------------------------------------------------------
    risk_assessment: dict[str, Any]

    medical_risk_score: float
    claims_risk_score: float
    coverage_gap_score: float
    overall_risk_score: float

    pricing_result: dict[str, Any]

    base_premium: float
    loading_percentage: float
    final_premium: float

    agent2_recommendation: str
    agent2_confidence: float
    agent2_reasoning: str
    agent2_completed: bool

    # ------------------------------------------------------------------
    # Confidence gate
    # ------------------------------------------------------------------
    confidence_gate: str
    reflection_required: bool
    reflection_type: str
    reflection_personas: list[str]

    # ------------------------------------------------------------------
    # Agent 3 - Constitutional AI and MAR
    # ------------------------------------------------------------------
    reflection_round: int
    reflection_findings: list[dict[str, Any]]
    reflection_verdict: str
    reflection_requires_rescore: bool
    agent3_completed: bool

    constitutional_medical_accuracy: dict[str, Any]
    constitutional_actuarial_soundness: dict[str, Any]
    constitutional_regulatory_compliance: dict[str, Any]
    constitutional_fairness: dict[str, Any]
    constitutional_explainability: dict[str, Any]

    # ------------------------------------------------------------------
    # Human-in-the-loop
    # ------------------------------------------------------------------
    require_human_escalation: bool
    require_human_review: bool
    human_review_reasons: list[str]
    business_gate_reasons: list[str]

    human_review_reason: str
    human_review_status: str
    human_reviewed_by: str
    human_review_comments: str
    human_approved: bool

    # ------------------------------------------------------------------
    # Final decision
    # ------------------------------------------------------------------
    final_decision: str
    final_status: str
    final_recommendation: str
    final_confidence: float

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    workflow_trace: list[dict[str, Any]]
    audit_trail: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    timing: dict[str, float]
    token_usage: dict[str, int]
    agent_metrics: dict[str, dict[str, Any]]
    workflow_metrics: dict[str, Any]


class UnderwriteInput(BaseModel):
    applicant_profile: dict[str, Any] = Field(
        default_factory=dict
    )

    submission: dict[str, Any] = Field(
        default_factory=dict
    )


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
    coverage_gap_score: float = 0.0
    confirmed_coverage_gaps: list[dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: list[dict[str, Any]] = Field(default_factory=list)
    evidence_completeness: float = 0.0

    base_premium: float = 0.0
    loading_percentage: float = 0.0
    final_premium: float = 0.0

    confidence_gate: str = ""
    reflection_type: str = ""
    reflection_round: int = 0
    reflection_verdict: str = ""

    require_human_escalation: bool = False
    require_human_review: bool = False

    human_review_status: str = ""
    human_review_reasons: list[str] = Field(default_factory=list)

    agent1_completed: bool = False
    agent2_completed: bool = False
    agent3_completed: bool = False

    errors: list[dict[str, Any]] = Field(
        default_factory=list
    )


class HumanReviewInput(BaseModel):
    approved: bool
    reviewer: str
    comments: str = ""


class HumanOverrideInput(BaseModel):
    decision: str
    reviewer: str
    comments: str = ""


class HumanSendBackInput(BaseModel):
    reviewer: str
    comments: str = ""


class HumanEscalationInput(BaseModel):
    reviewer: str
    comments: str = ""