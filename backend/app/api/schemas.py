from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UnderwriteInput(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "applicant_profile": {
                    "applicant_id": "APP-001",
                    "name": "Ananya Krishnan",
                    "age": 32,
                    "gender": "F",
                    "occupation": "Software QA Engineer",
                    "region": "Kochi",
                    "bmi": 21.3,
                    "smoker": False,
                    "alcohol_use": "occasional",
                    "medical_conditions": [],
                    "medications": [],
                    "hospitalizations": [],
                },
                "submission": {
                    "product": (
                        "MedShield Comprehensive "
                        "Individual DEMO"
                    ),
                    "sum_insured": 1000000,
                    "term_years": 1,
                    "requested_start_date": "2026-10-01",
                    "jurisdiction": "India",
                    "insurer": "DEMO_INSURER",
                },
            }
        }
    )

    applicant_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="Applicant and medical profile.",
    )

    submission: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Insurance submission and "
            "requested coverage."
        ),
    )

    @field_validator(
        "applicant_profile",
        "submission",
        mode="before",
    )
    @classmethod
    def validate_objects(
        cls,
        value: Any,
    ) -> dict[str, Any]:
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise ValueError(
                "Value must be a JSON object."
            )

        return value


class AgentMetrics(BaseModel):
    agent: str
    latency_sec: float = Field(default=0.0, ge=0.0)
    llm_latency_sec: float = Field(default=0.0, ge=0.0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class WorkflowMetrics(BaseModel):
    workflow_latency_sec: float = Field(default=0.0, ge=0.0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    agents: dict[str, AgentMetrics] = Field(default_factory=dict)


class DecisionBasis(BaseModel):
    medical_risk: dict[str, Any] = Field(default_factory=dict)
    claims_risk: dict[str, Any] = Field(default_factory=dict)
    coverage_assessment: dict[str, Any] = Field(default_factory=dict)
    overall_risk: dict[str, Any] = Field(default_factory=dict)
    recommendation: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pricing: dict[str, Any] = Field(default_factory=dict)


class UnderwritingDecision(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )

    case_id: str

    final_status: str = "pending"

    final_decision: str = ""

    final_recommendation: str = ""

    final_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    complexity_level: str = ""

    routing_strategy: str = ""

    confidence_gate: str = ""

    overall_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    medical_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    claims_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    coverage_gap_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    base_premium: float = Field(
        default=0.0,
        ge=0.0,
    )

    loading_percentage: float = Field(
        default=0.0,
        ge=0.0,
    )

    final_premium: float = Field(
        default=0.0,
        ge=0.0,
    )

    require_human_escalation: bool = False

    require_human_review: bool = False

    human_review_status: str = ""

    agent1_completed: bool = False

    agent2_completed: bool = False

    agent3_completed: bool = False

    reflection_required: bool = False

    reflection_type: str = "none"

    reflection_round: int = Field(
        default=0,
        ge=0,
        le=3,
    )

    reflection_verdict: str = ""

    reflection_requires_rescore: bool = False

    coverage_gaps: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    evidence_gaps: list[str] = Field(
        default_factory=list,
    )

    evidence_domains: dict[str, bool] = Field(
        default_factory=dict,
    )

    decision_basis: DecisionBasis = Field(
        default_factory=DecisionBasis,
    )

    reasoning: str = ""

    agent_metrics: dict[str, AgentMetrics] = Field(
        default_factory=dict,
    )

    workflow_metrics: WorkflowMetrics = Field(
        default_factory=WorkflowMetrics,
    )

    timing: dict[str, Any] = Field(
        default_factory=dict,
    )

    token_usage: dict[str, int] = Field(
        default_factory=dict,
    )

    reflection_findings: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    workflow_trace: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    audit_trail: list[dict[str, Any]] = Field(
        default_factory=list,
    )

    errors: list[dict[str, Any]] = Field(
        default_factory=list,
    )

class ApplicantCreate(BaseModel):
    applicant_id: str = Field(
        min_length=1,
        max_length=100,
    )
    name: str = Field(
        min_length=1,
        max_length=200,
    )
    profile: dict[str, Any] = Field(
        default_factory=dict,
    )
    source: str = Field(
        default="manual",
        max_length=50,
    )


class ApplicantSummary(BaseModel):
    applicant_id: str
    name: str
    source: str = "synthetic"
    created_at: str
    updated_at: str
    case_count: int = 0
    document_count: int = 0


class EvidenceStatus(BaseModel):
    medical: str = "NOT_PROVIDED"
    claims: str = "NOT_PROVIDED"
    policy: str = "NOT_PROVIDED"
    other: str = "NOT_PROVIDED"


class ApplicantDetail(BaseModel):
    applicant_id: str
    name: str
    profile: dict[str, Any] = Field(
        default_factory=dict,
    )
    source: str = "synthetic"
    created_at: str
    updated_at: str
    evidence_status: EvidenceStatus = Field(
        default_factory=EvidenceStatus,
    )
    documents: list[dict[str, Any]] = Field(
        default_factory=list,
    )
    cases: list[dict[str, Any]] = Field(
        default_factory=list,
    )


class CaseCreate(BaseModel):
    applicant_id: str = Field(
        min_length=1,
        max_length=100,
    )
    submission: dict[str, Any] = Field(
        default_factory=dict,
    )


class CaseSummary(BaseModel):
    case_id: str
    applicant_id: str
    applicant_name: str = ""
    status: str = "pending"
    final_decision: str = ""
    final_recommendation: str = ""
    overall_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    created_at: str
    updated_at: str


class CaseDetail(BaseModel):
    case_id: str
    applicant_id: str
    applicant_profile: dict[str, Any] = Field(
        default_factory=dict,
    )
    submission: dict[str, Any] = Field(
        default_factory=dict,
    )
    status: str = "pending"
    created_at: str
    updated_at: str
    documents: list[dict[str, Any]] = Field(
        default_factory=list,
    )


class DocumentMetadata(BaseModel):
    document_type: str = Field(
        min_length=1,
        max_length=100,
    )
    filename: str = Field(
        min_length=1,
        max_length=255,
    )
    evidence_status: str = "AVAILABLE"


class DocumentUploadResponse(BaseModel):
    document_id: str
    applicant_id: str
    case_id: str
    document_type: str
    filename: str
    evidence_status: str = "AVAILABLE"
    indexed: bool = False

class HumanReviewInput(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reviewer": "UW-SENIOR-001",
                "comments": (
                    "Reviewed the evidence and "
                    "approve the recommendation."
                ),
            }
        }
    )

    reviewer: str = Field(
        min_length=1,
        max_length=100,
    )

    comments: str = Field(
        default="",
        max_length=5000,
    )


class HumanOverrideInput(HumanReviewInput):
    decision: str = Field(
        min_length=1,
        max_length=100,
    )

    loading_percentage: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )

    reason: str = Field(
        default="",
        max_length=5000,
    )


class HumanSendBackInput(HumanReviewInput):
    reason: str = Field(
        default="",
        max_length=5000,
    )


class HumanEscalationInput(HumanReviewInput):
    reason: str = Field(
        default="",
        max_length=5000,
    )


class AgentStatusUpdate(BaseModel):
    type: Literal[
        "agent_started",
        "agent_completed",
        "reflection_triggered",
        "mar_round",
        "human_review_required",
        "complete",
        "failed",
    ]

    agent: str | None = None

    progress_pct: int = Field(
        default=0,
        ge=0,
        le=100,
    )

    duration_sec: float | None = Field(
        default=None,
        ge=0.0,
    )

    key_finding: str | None = None

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    mode: str | None = None

    round: int | None = Field(
        default=None,
        ge=0,
        le=3,
    )

    personas_responded: int | None = Field(
        default=None,
        ge=0,
    )

    consensus: bool | None = None

    message: str | None = None

    timestamp: str = Field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )


class APIResponse(BaseModel):
    success: bool = True

    data: Any = None

    error: str | None = None


class UnderwriteStartResponse(BaseModel):
    case_id: str

    status: str = "processing"

    message: str = (
        "Underwriting workflow started."
    )

    created_at: str


class CaseStatusResponse(BaseModel):
    case_id: str

    status: str

    final_decision: str = ""

    final_recommendation: str = ""

    final_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    overall_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    medical_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    claims_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    coverage_gap_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )

    confidence_gate: str = ""

    reflection_round: int = Field(
        default=0,
        ge=0,
        le=3,
    )

    reflection_verdict: str = ""

    require_human_escalation: bool = False

    require_human_review: bool = False


class HealthResponse(BaseModel):
    status: str

    environment: str

    chromadb: str