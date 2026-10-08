from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.agent1_submission import submission_agent
from app.agents.agent2_risk import risk_agent
from app.agents.agent3_reflection import reflection_agent
from app.agents.routing.complexity_router import complexity_router
from app.models.state import UnderwritingState


MAX_REFLECTION_ROUNDS = 3


def _agent_metrics(result: dict[str, Any], agent: str) -> dict[str, Any]:
    metrics = result.get("metrics") or result.get(f"{agent}_metrics") or {}
    if not isinstance(metrics, dict):
        metrics = {}

    input_tokens = int(
        metrics.get("input_tokens")
        or metrics.get("prompt_tokens")
        or 0
    )
    output_tokens = int(
        metrics.get("output_tokens")
        or metrics.get("completion_tokens")
        or 0
    )
    total_tokens = int(
        metrics.get("total_tokens")
        or input_tokens + output_tokens
    )

    return {
        "agent": agent,
        "latency_sec": round(
            float(metrics.get("latency_sec", metrics.get("duration_sec", 0.0)) or 0.0),
            4,
        ),
        "llm_latency_sec": round(
            float(metrics.get("llm_latency_sec", 0.0) or 0.0),
            4,
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _workflow_metrics(
    started: float,
    agent_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    normalized = dict(agent_metrics)
    input_tokens = sum(
        int(item.get("input_tokens", 0) or 0)
        for item in normalized.values()
    )
    output_tokens = sum(
        int(item.get("output_tokens", 0) or 0)
        for item in normalized.values()
    )

    return {
        "workflow_latency_sec": round(time.perf_counter() - started, 4),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "agents": normalized,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _audit(
    state: UnderwritingState,
    node: str,
    details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    audit = list(
        state.get(
            "audit_trail",
            [],
        )
    )

    audit.append(
        {
            "node": node,
            "timestamp": _now(),
            "details": details or {},
        }
    )

    return audit


def _append_error(
    state: UnderwritingState,
    node: str,
    exc: Exception,
) -> list[dict[str, Any]]:
    errors = list(
        state.get(
            "errors",
            [],
        )
    )

    errors.append(
        {
            "node": node,
            "timestamp": _now(),
            "type": type(exc).__name__,
            "message": str(exc),
        }
    )

    return errors


def intake_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    return {
        "updated_at": _now(),
        "final_status": "processing",
        "workflow_trace": _trace(
            state,
            "intake",
            details={
                "case_id": state.get("case_id"),
                "applicant_id": (
                    state.get(
                        "applicant_profile",
                        {},
                    ).get("applicant_id")
                ),
            },
        ),
        "audit_trail": _audit(
            state,
            "intake",
        ),
    }


async def agent1_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    try:
        result = await submission_agent.run(
            applicant_profile=state.get(
                "applicant_profile",
                {},
            ),
            submission=state.get(
                "submission",
                {},
            ),
        )

        enrichment = result.get(
            "agent1_enrichment",
            {},
        )
        agent1_metrics = _agent_metrics(
            result,
            "agent1",
        )

        underwriting_submission = result.get(
            "underwriting_submission",
            [],
        )

        underwriting_knowledge = result.get(
            "underwriting_knowledge_evidence",
            result.get(
                "underwriting_evidence",
                [],
            ),
        )

        return {
            "updated_at": _now(),
            "final_status": "agent1",
            "medical_evidence": result.get(
                "medical_evidence",
                [],
            ),
            "claims_evidence": result.get(
                "claims_evidence",
                [],
            ),
            "policy_evidence": result.get(
                "policy_evidence",
                [],
            ),
            "regulatory_evidence": result.get(
                "regulatory_evidence",
                [],
            ),
            "underwriting_evidence": underwriting_knowledge,
            "underwriting_submission": underwriting_submission,
            "underwriting_knowledge_evidence": underwriting_knowledge,
            "medical_knowledge": result.get(
                "medical_knowledge",
                [],
            ),
            "coverage_gaps": result.get(
                "coverage_gaps",
                [],
            ),
            "agent1_enrichment": enrichment,
            "agent1_metrics": agent1_metrics,
            "agent_metrics": {
                "agent1": agent1_metrics,
            },
            "agent1_completed": True,
            "workflow_trace": _trace(
                state,
                "agent1_submission",
                details={
                    "medical_evidence": len(
                        result.get(
                            "medical_evidence",
                            [],
                        )
                    ),
                    "claims_evidence": len(
                        result.get(
                            "claims_evidence",
                            [],
                        )
                    ),
                    "policy_evidence": len(
                        result.get(
                            "policy_evidence",
                            [],
                        )
                    ),
                    "underwriting_submission": (
                        enrichment.get(
                            "evidence_summary",
                            {},
                        ).get(
                            "underwriting_submission_documents",
                            0,
                        )
                    ),
                    "underwriting_knowledge": (
                        enrichment.get(
                            "evidence_summary",
                            {},
                        ).get(
                            "underwriting_knowledge_documents",
                            0,
                        )
                    ),
                    "regulatory_evidence": len(
                        result.get(
                            "regulatory_evidence",
                            [],
                        )
                    ),
                    "coverage_gaps": len(
                        result.get(
                            "coverage_gaps",
                            [],
                        )
                    ),
                    "metrics": agent1_metrics,
                },
            ),
            "audit_trail": _audit(
                state,
                "agent1_submission",
            ),
        }

    except Exception as exc:
        return {
            "updated_at": _now(),
            "final_status": "failed",
            "errors": _append_error(
                state,
                "agent1_submission",
                exc,
            ),
            "workflow_trace": _trace(
                state,
                "agent1_submission",
                status="failed",
                details={
                    "error": str(exc),
                },
            ),
            "audit_trail": _audit(
                state,
                "agent1_submission",
                details={
                    "error": str(exc),
                },
            ),
        }


def complexity_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    try:
        result = complexity_router.route(
            applicant_profile=state.get(
                "applicant_profile",
                {},
            ),
            enrichment_results=state.get(
                "agent1_enrichment",
                {},
            ),
        )

        complexity_level = result.get(
            "complexity_level",
            "standard",
        )

        routing_strategy = result.get(
            "routing_strategy",
            "plan_and_execute",
        )

        return {
            "updated_at": _now(),
            "complexity_level": complexity_level,
            "complexity_reasons": result.get(
                "complexity_reasons",
                [],
            ),
            "routing_strategy": routing_strategy,
            "routing_completed": True,
            "final_status": "agent2",
            "workflow_trace": _trace(
                state,
                "complexity_router",
                details={
                    "complexity_level": complexity_level,
                    "routing_strategy": routing_strategy,
                    "condition_count": result.get(
                        "condition_count",
                        0,
                    ),
                    "red_flags": result.get(
                        "red_flags",
                        [],
                    ),
                },
            ),
            "audit_trail": _audit(
                state,
                "complexity_router",
            ),
        }

    except Exception as exc:
        return {
            "updated_at": _now(),
            "final_status": "failed",
            "errors": _append_error(
                state,
                "complexity_router",
                exc,
            ),
            "workflow_trace": _trace(
                state,
                "complexity_router",
                status="failed",
                details={
                    "error": str(exc),
                },
            ),
            "audit_trail": _audit(
                state,
                "complexity_router",
                details={
                    "error": str(exc),
                },
            ),
        }


def agent2_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    try:
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
            routing_result=routing_result,
        )

        risk_assessment = result.get(
            "risk_assessment",
            {},
        )
        agent2_metrics = _agent_metrics(
            result,
            "agent2",
        )

        pricing = result.get(
            "pricing_result",
            {},
        )

        recommendation = result.get(
            "agent2_recommendation",
            "human_review",
        )

        confidence = float(
            result.get(
                "agent2_confidence",
                0.0,
            )
            or 0.0
        )

        return {
            "updated_at": _now(),
            "final_status": "agent2",
            "risk_assessment": risk_assessment,
            "medical_risk_score": risk_assessment.get(
                "medical_risk_score",
                0.0,
            ),
            "claims_risk_score": risk_assessment.get(
                "claims_risk_score",
                0.0,
            ),
            "coverage_gap_score": risk_assessment.get(
                "coverage_gap_score",
                0.0,
            ),
            "overall_risk_score": risk_assessment.get(
                "overall_risk_score",
                0.0,
            ),
            "pricing_result": pricing,
            "base_premium": pricing.get(
                "base_premium",
                0.0,
            ),
            "loading_percentage": pricing.get(
                "loading_percentage",
                0.0,
            ),
            "final_premium": pricing.get(
                "final_premium",
                0.0,
            ),
            "agent2_recommendation": recommendation,
            "agent2_confidence": confidence,
            "agent2_reasoning": result.get(
                "agent2_reasoning",
                "",
            ),
            "decision_basis": result.get(
                "decision_basis",
                risk_assessment.get("decision_basis", {}),
            ),
            "agent2_metrics": agent2_metrics,
            "agent_metrics": {
                **state.get("agent_metrics", {}),
                "agent2": agent2_metrics,
            },
            "agent2_completed": True,
            "reflection_requires_rescore": False,
            "workflow_trace": _trace(
                state,
                "agent2_risk",
                details={
                    "risk_score": risk_assessment.get(
                        "overall_risk_score",
                        0.0,
                    ),
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "pricing": pricing,
                    "reflection_round": state.get(
                        "reflection_round",
                        0,
                    ),
                    "metrics": agent2_metrics,
                },
            ),
            "audit_trail": _audit(
                state,
                "agent2_risk",
            ),
        }

    except Exception as exc:
        return {
            "updated_at": _now(),
            "final_status": "failed",
            "errors": _append_error(
                state,
                "agent2_risk",
                exc,
            ),
            "workflow_trace": _trace(
                state,
                "agent2_risk",
                status="failed",
                details={
                    "error": str(exc),
                },
            ),
            "audit_trail": _audit(
                state,
                "agent2_risk",
                details={
                    "error": str(exc),
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

    complexity_level = state.get(
        "complexity_level",
        "standard",
    )

    if (
        confidence >= 0.85
        and risk_score < 70
        and complexity_level == "standard"
    ):
        confidence_gate = "high"
        reflection_required = False

    elif (
        complexity_level == "complex"
        or risk_score >= 70
        or confidence < 0.70
    ):
        confidence_gate = (
            "medium"
            if confidence >= 0.70
            else "low"
        )
        reflection_required = True

    else:
        confidence_gate = "medium"
        reflection_required = True

    return {
        "updated_at": _now(),
        "final_status": (
            "finalize"
            if not reflection_required
            else "agent3"
        ),
        "confidence_gate": confidence_gate,
        "reflection_required": reflection_required,

        # Agent3 is the single source of truth for the actual
        # reflection mode. The gate only decides whether reflection
        # is required.
        "reflection_type": (
            "pending"
            if reflection_required
            else "none"
        ),

        "workflow_trace": _trace(
            state,
            "confidence_gate",
            details={
                "confidence": confidence,
                "risk_score": risk_score,
                "complexity_level": complexity_level,
                "confidence_gate": confidence_gate,
                "reflection_required": reflection_required,
                "reflection_mode": (
                    "pending_agent3"
                    if reflection_required
                    else "none"
                ),
            },
        ),

        "audit_trail": _audit(
            state,
            "confidence_gate",
            details={
                "confidence": confidence,
                "risk_score": risk_score,
                "complexity_level": complexity_level,
                "confidence_gate": confidence_gate,
                "reflection_required": reflection_required,
            },
        ),
    }


def reflection_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    try:
        current_round = int(
            state.get(
                "reflection_round",
                0,
            )
            or 0
        )

        previous_findings = list(
            state.get(
                "reflection_findings",
                [],
            )
        )

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
                "agent2_recommendation": state.get(
                    "agent2_recommendation",
                    "",
                ),
                "agent2_confidence": state.get(
                    "agent2_confidence",
                    0.0,
                ),
            },
            previous_findings=previous_findings,
        )

        agent3_metrics = _agent_metrics(
            result,
            "agent3",
        )

        agent3_round = int(
            result.get(
                "reflection_round",
                1,
            )
            or 1
        )

        next_round = max(
            current_round + 1,
            agent3_round,
        )

        next_round = min(
            next_round,
            MAX_REFLECTION_ROUNDS,
        )

        new_findings = list(
            result.get(
                "reflection_findings",
                [],
            )
        )

        combined_findings = (
            previous_findings
            + new_findings
        )

        requires_rescore = bool(
            result.get(
                "requires_rescore",
                False,
            )
        )

        require_human = bool(
            result.get(
                "require_human_review",
                False,
            )
            or result.get(
                "require_human_escalation",
                False,
            )
        )

        if next_round >= MAX_REFLECTION_ROUNDS:
            requires_rescore = False

            if result.get(
                "reflection_verdict"
            ) in {
                "review",
                "escalate",
            }:
                require_human = True

        actual_reflection_type = result.get(
            "reflection_type",
            "targeted",
        )

        return {
            "updated_at": _now(),
            "final_status": (
                "human_review"
                if require_human
                else "agent3"
            ),

            "reflection_required": bool(
                result.get(
                    "reflection_required",
                    True,
                )
            ),

            # IMPORTANT:
            # Store the mode selected by Agent3, not the
            # preliminary mode from the confidence gate.
            "reflection_type": actual_reflection_type,

            "reflection_personas": result.get(
                "reflection_personas",
                [],
            ),

            "reflection_round": next_round,

            "reflection_findings": combined_findings,

            "constitutional_medical_accuracy": result.get(
                "constitutional_medical_accuracy",
                {},
            ),

            "constitutional_actuarial_soundness": result.get(
                "constitutional_actuarial_soundness",
                {},
            ),

            "constitutional_regulatory_compliance": result.get(
                "constitutional_regulatory_compliance",
                {},
            ),

            "constitutional_fairness": result.get(
                "constitutional_fairness",
                {},
            ),

            "constitutional_explainability": result.get(
                "constitutional_explainability",
                {},
            ),

            "reflection_verdict": result.get(
                "reflection_verdict",
                "pass",
            ),

            "reflection_requires_rescore": (
                requires_rescore
            ),

            "require_human_review": require_human,

            "require_human_escalation": require_human,

            "human_review_reason": result.get(
                "human_review_reason",
                "",
            ),

            "agent3_metrics": agent3_metrics,
            "agent_metrics": {
                **state.get("agent_metrics", {}),
                "agent3": agent3_metrics,
            },
            "agent3_completed": True,

            "workflow_trace": _trace(
                state,
                "agent3_reflection",
                details={
                    "reflection_type": actual_reflection_type,
                    "reflection_round": next_round,
                    "verdict": result.get(
                        "reflection_verdict"
                    ),
                    "requires_rescore": requires_rescore,
                    "human_review_required": require_human,
                    "confidence_gate": state.get(
                        "confidence_gate"
                    ),
                    "metrics": agent3_metrics,
                },
            ),

            "audit_trail": _audit(
                state,
                "agent3_reflection",
                details={
                    "reflection_type": actual_reflection_type,
                    "reflection_round": next_round,
                    "verdict": result.get(
                        "reflection_verdict"
                    ),
                },
            ),
        }

    except Exception as exc:
        return {
            "updated_at": _now(),
            "final_status": "human_review",
            "require_human_escalation": True,
            "human_review_reason": (
                "Agent 3 reflection failed and requires "
                "manual underwriting review."
            ),
            "errors": _append_error(
                state,
                "agent3_reflection",
                exc,
            ),
            "workflow_trace": _trace(
                state,
                "agent3_reflection",
                status="failed",
                details={
                    "error": str(exc),
                },
            ),
            "audit_trail": _audit(
                state,
                "agent3_reflection",
                details={
                    "error": str(exc),
                },
            ),
        }


def reflection_router(
    state: UnderwritingState,
) -> str:
    reflection_required = bool(
        state.get(
            "reflection_required",
            False,
        )
    )

    if reflection_required:
        return "reflection"

    return "finalize"


def post_reflection_router(
    state: UnderwritingState,
) -> str:
    if state.get(
        "require_human_escalation",
        False,
    ):
        return "human_review"

    # Progressive-autonomy policy: complex underwriting cases
    # require human review even when Agent 3 reflection passes.
    if state.get("complexity_level") == "complex":
        return "human_review"

    reflection_round = int(
        state.get(
            "reflection_round",
            0,
        )
        or 0
    )

    if reflection_round >= MAX_REFLECTION_ROUNDS:
        return "human_review"

    if state.get(
        "reflection_requires_rescore",
        False,
    ):
        return "rescore"

    verdict = state.get(
        "reflection_verdict",
        "pass",
    )

    if verdict in {
        "review",
        "escalate",
        "fail",
    }:
        return "human_review"

    return "finalize"


def human_review_node(
    state: UnderwritingState,
) -> dict[str, Any]:
    reason = state.get(
        "human_review_reason",
        "",
    )

    if not reason and state.get("complexity_level") == "complex":
        reason = (
            "Complex underwriting case requires human review "
            "under the progressive-autonomy policy."
        )

    if not reason:
        reason = "Manual underwriting review required."

    return {
        "updated_at": _now(),
        "final_status": "awaiting_human_review",
        "human_review_status": "awaiting_review",
        "require_human_escalation": True,
        "workflow_trace": _trace(
            state,
            "human_review",
            status="awaiting",
            details={
                "reason": reason,
            },
        ),
        "audit_trail": _audit(
            state,
            "human_review",
            details={
                "reason": reason,
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

    if state.get(
        "require_human_escalation",
        False,
    ):
        decision = "human_review_required"
        status = "awaiting_human_review"

    elif recommendation == "standard_acceptance":
        decision = "approved"
        status = "completed"

    elif recommendation == "accept_with_loading":
        decision = "approved_with_loading"
        status = "completed"

    elif recommendation == "accept_with_exclusion":
        decision = "approved_with_exclusion"
        status = "completed"

    elif recommendation == "postpone":
        decision = "postponed"
        status = "completed"

    elif recommendation == "decline":
        decision = "declined"
        status = "completed"

    elif recommendation == "human_review":
        decision = "human_review_required"
        status = "awaiting_human_review"

    else:
        decision = (
            recommendation
            or "pending"
        )
        status = "completed"

    return {
        "updated_at": _now(),
        "final_decision": decision,
        "final_status": status,
        "final_recommendation": recommendation,
        "final_confidence": confidence,
        "decision_basis": state.get("decision_basis", {}),
        "reasoning": state.get("agent2_reasoning", ""),
        "workflow_trace": _trace(
            state,
            "finalize",
            details={
                "decision": decision,
                "recommendation": recommendation,
                "confidence": confidence,
                "risk_score": risk_score,
                "premium": state.get(
                    "final_premium",
                    0.0,
                ),
                "loading_percentage": state.get(
                    "loading_percentage",
                    0.0,
                ),
            },
        ),
        "audit_trail": _audit(
            state,
            "finalize",
        ),
    }


def build_graph() -> StateGraph:
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
        "confidence_gate_node",
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
        "confidence_gate_node",
    )

    graph.add_conditional_edges(
        "confidence_gate_node",
        reflection_router,
        {
            "reflection": "agent3_reflection",
            "finalize": "finalize",
        },
    )

    graph.add_conditional_edges(
        "agent3_reflection",
        post_reflection_router,
        {
            "rescore": "agent2_risk",
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

    return graph


memory_saver = MemorySaver()


workflow = build_graph().compile(
    checkpointer=memory_saver,
    interrupt_before=[
        "human_review",
    ],
)


def create_async_graph():
    return workflow


async def run_workflow(
    initial_state: UnderwritingState,
    thread_id: str | None = None,
) -> dict[str, Any]:
    case_id = initial_state.get(
        "case_id",
        "unknown",
    )

    config = {
        "configurable": {
            "thread_id": (
                thread_id
                or case_id
            ),
        }
    }

    started = time.perf_counter()

    result = await workflow.ainvoke(
        initial_state,
        config=config,
    )

    agent_metrics = result.get(
        "agent_metrics",
        {},
    )
    result["workflow_metrics"] = _workflow_metrics(
        started=started,
        agent_metrics=agent_metrics,
    )
    result["timing"] = {
        **result.get("timing", {}),
        "workflow_latency_sec": result["workflow_metrics"][
            "workflow_latency_sec"
        ],
    }
    result["token_usage"] = {
        "input_tokens": result["workflow_metrics"]["input_tokens"],
        "output_tokens": result["workflow_metrics"]["output_tokens"],
        "total_tokens": result["workflow_metrics"]["total_tokens"],
    }

    return result
