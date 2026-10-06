from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.agent1_submission import submission_agent
from app.agents.agent2_risk import risk_agent
from app.agents.agent3_reflection import reflection_agent
from app.agents.routing.complexity_router import complexity_router
from app.models.state import UnderwritingState


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _trace(
    state: UnderwritingState,
    node: str,
    status: str = "completed",
    details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    trace = list(
        state.get(
            "workflow_trace",
            [],
        )
    )

    trace.append(
        {
            "node": node,
            "status": status,
            "timestamp": _now(),
            "details": details or {},
        }
    )

    return trace


def intake_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    return {
        "current_node": "intake",
        "workflow_status": "running",
        "started_at": state.get(
            "started_at"
        ) or _now(),
        "workflow_trace": _trace(
            state,
            "intake",
            details={
                "case_id": state.get(
                    "case_id"
                ),
            },
        ),
    }


async def agent1_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    applicant_profile = state.get(
        "applicant_profile",
        {},
    )

    submission = state.get(
        "submission",
        {},
    )

    result = await submission_agent.run(
        applicant_profile=applicant_profile,
        submission=submission,
    )

    return {
        "current_node": "agent1_submission",
        "agent1_enrichment": result,
        "agent1_completed": True,
        "medical_evidence": result.get(
            "medical_evidence",
            {},
        ),
        "claims_evidence": result.get(
            "claims_evidence",
            {},
        ),
        "policy_evidence": result.get(
            "policy_evidence",
            {},
        ),
        "regulatory_evidence": result.get(
            "regulatory_evidence",
            {},
        ),
        "underwriting_evidence": result.get(
            "underwriting_evidence",
            {},
        ),
        "medical_knowledge": result.get(
            "medical_knowledge",
            {},
        ),
        "coverage_gaps": result.get(
            "coverage_gaps",
            [],
        ),
        "workflow_trace": _trace(
            state,
            "agent1_submission",
            details={
                "evidence_summary": result.get(
                    "evidence_summary",
                    {},
                ),
            },
        ),
    }


def complexity_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    applicant_profile = state.get(
        "applicant_profile",
        {},
    )

    enrichment = state.get(
        "agent1_enrichment",
        {},
    )

    result = complexity_router.route(
        applicant_profile=applicant_profile,
        enrichment_results=enrichment,
    )

    return {
        "current_node": "complexity_router",
        "complexity_level": result.get(
            "complexity_level",
            "standard",
        ),
        "complexity_reasons": result.get(
            "complexity_reasons",
            [],
        ),
        "routing_strategy": result.get(
            "routing_strategy",
            "plan_and_execute",
        ),
        "routing_completed": True,
        "workflow_trace": _trace(
            state,
            "complexity_router",
            details={
                "complexity_level": result.get(
                    "complexity_level"
                ),
                "routing_strategy": result.get(
                    "routing_strategy"
                ),
            },
        ),
    }


def agent2_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    applicant_profile = state.get(
        "applicant_profile",
        {},
    )

    submission = state.get(
        "submission",
        {},
    )

    enrichment = state.get(
        "agent1_enrichment",
        {},
    )

    routing_result = {
        "complexity_level": state.get(
            "complexity_level",
            "standard",
        ),
        "complexity_reasons": state.get(
            "complexity_reasons",
            [],
        ),
        "routing_strategy": state.get(
            "routing_strategy",
            "plan_and_execute",
        ),
    }

    result = risk_agent.run(
        applicant_profile=applicant_profile,
        submission=submission,
        enrichment_results=enrichment,
        routing_result=routing_result,
    )

    risk_assessment = result.get(
        "risk_assessment",
        {},
    )

    pricing = result.get(
        "pricing_result",
        {},
    )

    return {
        "current_node": "agent2_risk",
        "risk_assessment": risk_assessment,
        "medical_risk_score": risk_assessment.get(
            "medical_risk_score"
        ),
        "claims_risk_score": risk_assessment.get(
            "claims_risk_score"
        ),
        "overall_risk_score": risk_assessment.get(
            "overall_risk_score"
        ),
        "pricing_result": pricing,
        "base_premium": pricing.get(
            "base_premium"
        ),
        "loading_percentage": pricing.get(
            "loading_percentage"
        ),
        "final_premium": pricing.get(
            "final_premium"
        ),
        "agent2_recommendation": result.get(
            "recommendation",
            "human_review",
        ),
        "agent2_confidence": result.get(
            "confidence"
        ),
        "agent2_reasoning": result.get(
            "reasoning",
            {},
        ).get(
            "reasoning",
            "",
        ),
        "agent2_completed": True,
        "workflow_trace": _trace(
            state,
            "agent2_risk",
            details={
                "risk_score": risk_assessment.get(
                    "overall_risk_score"
                ),
                "recommendation": result.get(
                    "recommendation"
                ),
                "confidence": result.get(
                    "confidence"
                ),
            },
        ),
    }


def confidence_gate_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    confidence = float(
        state.get(
            "agent2_confidence",
            0.0,
        )
        or 0.0
    )

    risk_score = float(
        state.get(
            "overall_risk_score",
            0.0,
        )
        or 0.0
    )

    recommendation = state.get(
        "agent2_recommendation",
        "",
    )

    if confidence < 0.60:
        gate = "human_review"

    elif confidence < 0.75:
        gate = "reflection"

    elif risk_score >= 75:
        gate = "reflection"

    elif recommendation == "human_review":
        gate = "reflection"

    else:
        gate = "standard"

    reflection_required = (
        gate == "reflection"
    )

    return {
        "current_node": "confidence_gate",
        "confidence_gate": gate,
        "reflection_required": reflection_required,
        "workflow_trace": _trace(
            state,
            "confidence_gate",
            details={
                "confidence": confidence,
                "risk_score": risk_score,
                "gate": gate,
            },
        ),
    }


def reflection_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    result = reflection_agent.run(
        applicant_profile=state.get(
            "applicant_profile",
            {},
        ),
        submission=state.get(
            "submission",
            {},
        ),
        enrichment_results=state.get(
            "agent1_enrichment",
            {},
        ),
        risk_result={
            "risk_assessment": state.get(
                "risk_assessment",
                {},
            ),
            "pricing_result": state.get(
                "pricing_result",
                {},
            ),
            "recommendation": state.get(
                "agent2_recommendation"
            ),
            "confidence": state.get(
                "agent2_confidence"
            ),
            "reasoning": state.get(
                "agent2_reasoning",
                "",
            ),
        },
    )

    return {
        "current_node": "agent3_reflection",
        "reflection_required": result.get(
            "reflection_required",
            False,
        ),
        "reflection_type": result.get(
            "reflection_type",
            "none",
        ),
        "reflection_personas": result.get(
            "reflection_personas",
            [],
        ),
        "reflection_round": result.get(
            "reflection_round",
            0,
        ),
        "reflection_findings": result.get(
            "reflection_findings",
            [],
        ),
        "medical_accuracy_check": result.get(
            "medical_accuracy_check",
            {},
        ),
        "actuarial_soundness_check": result.get(
            "actuarial_soundness_check",
            {},
        ),
        "regulatory_compliance_check": result.get(
            "regulatory_compliance_check",
            {},
        ),
        "fairness_check": result.get(
            "fairness_check",
            {},
        ),
        "explainability_check": result.get(
            "explainability_check",
            {},
        ),
        "reflection_verdict": result.get(
            "reflection_verdict",
            "not_required",
        ),
        "require_human_review": result.get(
            "require_human_review",
            False,
        ),
        "human_review_reason": result.get(
            "human_review_reason",
            "",
        ),
        "workflow_trace": _trace(
            state,
            "agent3_reflection",
            details={
                "verdict": result.get(
                    "reflection_verdict"
                ),
                "human_review_required": result.get(
                    "require_human_review"
                ),
            },
        ),
    }


def reflection_router(
    state: UnderwritingState,
) -> str:
    gate = state.get(
        "confidence_gate",
        "standard",
    )

    if gate == "human_review":
        return "human_review"

    if gate == "reflection":
        return "reflection"

    return "finalize"


def post_reflection_router(
    state: UnderwritingState,
) -> str:
    if state.get(
        "require_human_review",
        False,
    ):
        return "human_review"

    verdict = state.get(
        "reflection_verdict",
        "pass",
    )

    if verdict in {
        "fail",
        "escalate",
        "review",
    }:
        return "human_review"

    return "finalize"


def human_review_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    return {
        "current_node": "human_review",
        "workflow_status": "awaiting_human_review",
        "require_human_review": True,
        "decision_status": "pending_human_review",
        "workflow_trace": _trace(
            state,
            "human_review",
            status="awaiting",
            details={
                "reason": state.get(
                    "human_review_reason",
                    "Manual review required.",
                ),
            },
        ),
    }


def finalize_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    recommendation = state.get(
        "agent2_recommendation",
        "human_review",
    )

    confidence = state.get(
        "agent2_confidence"
    )

    premium = state.get(
        "final_premium"
    )

    loading = state.get(
        "loading_percentage"
    )

    reflection_verdict = state.get(
        "reflection_verdict",
        "not_required",
    )

    if state.get(
        "require_human_review",
        False,
    ):
        decision_status = "human_review_required"

    elif recommendation == "standard_acceptance":
        decision_status = "approved"

    elif recommendation == "accept_with_loading":
        decision_status = "approved_with_loading"

    else:
        decision_status = "pending"

    final_decision = {
        "status": decision_status,
        "recommendation": recommendation,
        "confidence": confidence,
        "premium": premium,
        "loading_percentage": loading,
        "risk_score": state.get(
            "overall_risk_score"
        ),
        "reflection_verdict": reflection_verdict,
        "human_review_required": state.get(
            "require_human_review",
            False,
        ),
    }

    completed_at = _now()

    started_at = state.get(
        "started_at"
    )

    processing_time_ms = None

    if started_at:
        try:
            start = datetime.fromisoformat(
                started_at
            )

            end = datetime.fromisoformat(
                completed_at
            )

            processing_time_ms = round(
                (
                    end - start
                ).total_seconds()
                * 1000,
                2,
            )
        except ValueError:
            processing_time_ms = None

    return {
        "current_node": "finalize",
        "workflow_status": (
            "completed"
            if decision_status != "human_review_required"
            else "awaiting_human_review"
        ),
        "decision_status": decision_status,
        "final_decision": final_decision,
        "final_recommendation": recommendation,
        "final_confidence": confidence,
        "completed_at": completed_at,
        "processing_time_ms": processing_time_ms,
        "workflow_trace": _trace(
            state,
            "finalize",
            details=final_decision,
        ),
    }


def build_graph():
    graph = StateGraph(
        UnderwritingState
    )

    graph.add_node(
        "intake",
        intake_node,
    )

    graph.add_node(
        "agent1_submission",
        agent1_node,
    )

    graph.add_node(
        "complexity_router",
        complexity_node,
    )

    graph.add_node(
        "agent2_risk",
        agent2_node,
    )

    graph.add_node(
        "evaluate_confidence",
        confidence_gate_node,
    )

    graph.add_node(
        "agent3_reflection",
        reflection_node,
    )

    graph.add_node(
        "human_review",
        human_review_node,
    )

    graph.add_node(
        "finalize",
        finalize_node,
    )

    graph.add_edge(
        START,
        "intake",
    )

    graph.add_edge(
        "intake",
        "agent1_submission",
    )

    graph.add_edge(
        "agent1_submission",
        "complexity_router",
    )

    graph.add_edge(
        "complexity_router",
        "agent2_risk",
    )

    graph.add_edge(
        "agent2_risk",
        "evaluate_confidence",
    )

    graph.add_conditional_edges(
        "evaluate_confidence",
        reflection_router,
        {
            "reflection": "agent3_reflection",
            "human_review": "human_review",
            "finalize": "finalize",
        },
    )

    graph.add_conditional_edges(
        "agent3_reflection",
        post_reflection_router,
        {
            "human_review": "human_review",
            "finalize": "finalize",
        },
    )

    graph.add_edge(
        "human_review",
        END,
    )

    graph.add_edge(
        "finalize",
        END,
    )

    return graph.compile()


underwriting_graph = build_graph()