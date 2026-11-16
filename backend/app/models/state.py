from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# Domain Schemas & Value Objects
# ----------------------------------------------------------------------
class FamilyMemberRelation(str, Enum):
    FATHER = "father"
    MOTHER = "mother"
    SIBLING = "sibling"
    CHILD = "child"
    OTHER = "other"


class FamilyHistoryRecord(BaseModel):
    relation: FamilyMemberRelation
    condition: str
    age_at_onset: int | None = None
    cause_of_death: str | None = None


class OccupationHazardClass(int, Enum):
    CLASS_1 = 1  # Professional/Desk/Administrative (0 debits)
    CLASS_2 = 2  # Supervised manual/Retail/Travel (10 debits)
    CLASS_3 = 3  # Heavy manual/Industrial/Construction (25 debits)
    CLASS_4 = 4  # Extreme hazard/Mining/Offshore/Aviation (50 debits)


class OccupationHazardRecord(BaseModel):
    title: str
    hazard_class: OccupationHazardClass
    notes: str = ""


class MedicationVerificationItem(BaseModel):
    drug_name: str
    inferred_condition: str
    is_declared: bool
    discrepancy_score: int
    context_exception_applied: bool = False
    context_exception_tag: str | None = None


class PEDWaitingPeriod(BaseModel):
    condition: str
    waiting_period_months: int
    statutory_cap_months: int = 36
    permanent_exclusion: bool = False


class LabAnalyteRecord(BaseModel):
    analyte_name: str
    measured_value: float
    measured_unit: str
    normalized_value: float
    normalized_unit: str
    reference_low: float | None = None
    reference_high: float | None = None
    is_abnormal: bool


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

    family_medical_history: list[dict[str, Any]]
    occupation_profile: dict[str, Any]
    medication_records: list[dict[str, Any]]
    ped_waiting_periods: list[dict[str, Any]]
    lab_analyte_records: list[dict[str, Any]]

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
    document_defects: list[dict[str, Any]]
    unparsed_files: list[str]
    underwriting_submission: list[dict[str, Any]]
    underwriting_knowledge_evidence: list[dict[str, Any]]
    agent1_metrics: dict[str, Any]

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
    extra_mortality_percentage: float
    actuarial_debits: float
    copula_synergy_details: dict[str, Any]

    pricing_result: dict[str, Any]

    base_premium: float
    loading_percentage: float
    final_premium: float

    agent2_recommendation: str
    agent2_confidence: float
    agent2_reasoning: str
    reasoning_structured: dict[str, Any]
    agent2_completed: bool
    agent2_metrics: dict[str, Any]
    decision_basis: dict[str, Any]

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
    agent3_metrics: dict[str, Any]
    reflection_consensus: bool

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
    review_tier: str
    human_review_reasons: list[str]
    business_gate_reasons: list[str]

    human_review_reason: str
    reasoning_cache_key: str | None
    fraud_risk_score: float
    fraud_risk_level: str
    fraud_flags: list[dict[str, Any]]
    fraud_notes: list[dict[str, Any]]
    mandatory_review_reasons: list[str]
    compliance_report: dict[str, Any]
    confidence_layers: dict[str, float]
    decision_level: str
    reason_codes: list[dict[str, Any]]
    missing_documents: list[dict[str, Any]]
    document_override: str
    review_notes: list[dict[str, Any]]
    llm_advisory_notes: list[str]
    security_review_reasons: list[str]
    quarantined_inputs: list[dict[str, Any]]
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
    extra_mortality_percentage: float = 100.0
    actuarial_debits: float = 0.0
    ped_waiting_periods: list[dict[str, Any]] = Field(default_factory=list)

    confidence_gate: str = ""
    reflection_type: str = ""
    reflection_round: int = 0
    reflection_verdict: str = ""

    require_human_escalation: bool = False
    require_human_review: bool = False
    review_tier: str = "Tier 0"

    human_review_status: str = ""
    human_review_reasons: list[str] = Field(default_factory=list)

    agent1_completed: bool = False
    agent2_completed: bool = False
    agent3_completed: bool = False

    errors: list[dict[str, Any]] = Field(
        default_factory=list
    )


class HumanReviewInput(BaseModel):
    approved: bool = True
    reviewer: str
    comments: str = ""


class HumanOverrideInput(BaseModel):
    decision: str
    reviewer: str
    comments: str = ""
    loading_percentage: float | None = None


class HumanSendBackInput(BaseModel):
    reviewer: str
    comments: str = ""


class HumanEscalationInput(BaseModel):
    reviewer: str
    comments: str = ""
