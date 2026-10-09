from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from app.models.state import (
    HumanEscalationInput,
    HumanOverrideInput,
    HumanReviewInput,
    HumanSendBackInput,
    UnderwriteInput,
    UnderwritingState,
)

from app.api.schemas import (
    ApplicantCreate,
    CaseCreate,
    DocumentUploadResponse,
)
from app.orchestrator.graph import run_workflow
from app.services.document_service import document_service
from app.store.state_store import state_store
from app.security.guardrails import guardrails


logger = logging.getLogger(__name__)

router = APIRouter()


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _case_id() -> str:
    return (
        f"UW-{datetime.now().strftime('%Y')}-"
        f"{uuid.uuid4().hex[:8].upper()}"
    )


def _validate_underwriting_guardrails(
    request: UnderwriteInput,
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    result = guardrails.validate_submission(
        request.applicant_profile,
        request.submission,
    )

    if not result.allowed:
        if case_id:
            state_store.add_workflow_event(
                case_id=case_id,
                event_type="security_guardrail",
                node="guardrails",
                status="blocked",
                message="Underwriting request blocked by security guardrails.",
                data=result.to_dict(),
            )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Underwriting request blocked by security guardrails.",
                "risk_level": result.risk_level,
                "reasons": result.reasons,
                "checks": result.checks,
            },
        )

    return result.to_dict()


def _record_guardrail_result(
    state: UnderwritingState,
    result: dict[str, Any],
) -> None:
    state.setdefault("audit_trail", []).append(
        {
            "node": "guardrails",
            "timestamp": _now(),
            "details": {
                "allowed": result.get("allowed", False),
                "risk_level": result.get("risk_level", "unknown"),
                "reasons": result.get("reasons", []),
                "checks": result.get("checks", {}),
            },
        }
    )


def _initial_state(
    case_id: str,
    request: UnderwriteInput,
) -> UnderwritingState:
    now = _now()

    return {
        "case_id": case_id,
        "created_at": now,
        "updated_at": now,

        "applicant_profile": (
            request.applicant_profile
        ),
        "submission": request.submission,
        "raw_request": request.model_dump(),

        # Agent 1
        "medical_evidence": [],
        "claims_evidence": [],
        "policy_evidence": [],
        "regulatory_evidence": [],
        "underwriting_evidence": [],
        "medical_knowledge": [],
        "coverage_gaps": [],

        "agent1_enrichment": {},
        "agent1_completed": False,

        # Complexity routing
        "complexity_level": "",
        "complexity_reasons": [],
        "routing_strategy": "",
        "routing_completed": False,

        # Agent 2
        "risk_assessment": {},

        "medical_risk_score": 0.0,
        "claims_risk_score": 0.0,
        "coverage_gap_score": 0.0,
        "overall_risk_score": 0.0,

        "pricing_result": {},
        "base_premium": 0.0,
        "loading_percentage": 0.0,
        "final_premium": 0.0,

        "agent2_recommendation": "",
        "agent2_confidence": 0.0,
        "agent2_reasoning": "",
        "agent2_completed": False,

        # Confidence gate
        "confidence_gate": "",
        "reflection_required": False,
        "reflection_type": "none",
        "reflection_personas": [],

        # Agent 3
        "reflection_round": 0,
        "reflection_findings": [],
        "reflection_verdict": "",
        "reflection_requires_rescore": False,

        "constitutional_medical_accuracy": {},
        "constitutional_actuarial_soundness": {},
        "constitutional_regulatory_compliance": {},
        "constitutional_fairness": {},
        "constitutional_explainability": {},

        "agent3_completed": False,

        # HITL
        "require_human_escalation": False,
        "require_human_review": False,

        "human_review_reason": "",
        "human_review_status": "",
        "human_reviewed_by": "",
        "human_review_comments": "",
        "human_approved": False,

        # Final
        "final_decision": "",
        "final_status": "pending",
        "final_recommendation": "",
        "final_confidence": 0.0,

        # Observability
        "workflow_trace": [],
        "audit_trail": [
            {
                "node": "case_created",
                "timestamp": now,
                "details": {
                    "case_id": case_id,
                },
            }
        ],
        "errors": [],
        "timing": {},
        "token_usage": {},
    }


def _save_state(
    case_id: str,
    state: UnderwritingState,
    status: str | None = None,
) -> None:
    state["updated_at"] = _now()

    state_store.save_case(
        case_id=case_id,
        state=dict(state),
        status=status,
    )


async def _persist_workflow_update(
    case_id: str,
    update: dict[str, Any],
) -> None:
    current = dict(update)
    current["updated_at"] = _now()

    trace = current.get("workflow_trace")
    latest = trace[-1] if isinstance(trace, list) and trace else {}
    if not isinstance(latest, dict):
        latest = {}

    node = str(
        latest.get("node")
        or latest.get("event_type")
        or "workflow"
    )
    node_status = str(latest.get("status") or "completed")
    message = latest.get("message") or ""

    final_status = str(
        current.get("final_status")
        or current.get("status")
        or "processing"
    )
    db_status = final_status.replace("_", "-")

    state_store.save_case(
        case_id=case_id,
        state=current,
        status=db_status,
    )

    state_store.add_workflow_event(
        case_id=case_id,
        event_type="workflow",
        node=node,
        status=node_status,
        message=message or f"Workflow reached {node}.",
        data={
            "final_status": final_status,
            "workflow_node": node,
            "details": latest.get("details", {}),
        },
    )


async def _run_case(
    case_id: str,
    state: UnderwritingState,
) -> None:
    try:
        current = dict(state)

        current["final_status"] = "processing"
        current["updated_at"] = _now()

        _save_state(
            case_id,
            current,
            status="processing",
        )

        state_store.add_workflow_event(
            case_id=case_id,
            event_type="workflow",
            node="workflow",
            status="started",
            message="Underwriting workflow started.",
            data={
                "message": "Underwriting workflow started.",
            },
        )

        result = await run_workflow(
            initial_state=current,
            thread_id=case_id,
            on_update=lambda update: _persist_workflow_update(
                case_id,
                update,
            ),
        )

        output_guardrail = guardrails.validate_output(
            result.get("final_decision", result),
        )
        output_guardrail_data = output_guardrail.to_dict()
        result.setdefault("audit_trail", []).append({
            "node": "guardrails",
            "timestamp": _now(),
            "details": {
                "phase": "output_validation",
                **output_guardrail_data,
            },
        })

        if not output_guardrail.allowed:
            result["final_status"] = "failed"
            result["require_human_review"] = True
            result["human_review_reason"] = (
                "Final underwriting output blocked by security guardrails."
            )
            result.setdefault("errors", []).append({
                "timestamp": _now(),
                "type": "OutputGuardrailBlocked",
                "message": output_guardrail.reasons,
            })
            state_store.add_workflow_event(
                case_id=case_id,
                event_type="security_guardrail",
                node="guardrails",
                status="blocked_output",
                message="Final underwriting output blocked by security guardrails.",
                data=output_guardrail.to_dict(),
            )

        result["updated_at"] = _now()

        final_status = result.get(
            "final_status",
            "completed",
        )

        # Defensive HITL gate: never expose a completed/final decision when
        # the workflow has explicitly requested human review.
        human_review_required = bool(
            result.get("require_human_review")
            or result.get("require_human_escalation")
            or result.get("human_review_reasons")
            or result.get("business_gate_reasons")
        )
        if human_review_required:
            final_status = "awaiting_human_review"
            result["final_status"] = final_status
            result["require_human_review"] = True
            result["require_human_escalation"] = True
            result["human_review_status"] = "awaiting_review"
            result["final_decision"] = "pending_human_review"

        _save_state(
            case_id,
            result,
            status=final_status,
        )

        state_store.add_workflow_event(
            case_id=case_id,
            event_type="workflow",
            node="workflow",
            status=final_status,
            data={
                "final_decision": result.get(
                    "final_decision",
                    "",
                ),
            },
        )
    except Exception as exc:
        logger.exception(
            "Underwriting workflow failed for %s",
            case_id,
        )

        current = (
            state_store.get_case(
                case_id
            )
            or dict(state)
        )

        errors = list(
            current.get(
                "errors",
                [],
            )
        )

        errors.append(
            {
                "timestamp": _now(),
                "type": type(exc).__name__,
                "message": str(exc),
            }
        )

        current["errors"] = errors
        current["final_status"] = "failed"
        current["updated_at"] = _now()

        _save_state(
            case_id,
            current,
            status="failed",
        )

        state_store.add_workflow_event(
            case_id=case_id,
            event_type="workflow",
            node="workflow",
            status="failed",
            data={
                "error": str(exc),
            },
        )

@router.get("/applicants")
async def list_applicants(
    limit: int = 100,
):
    applicants = state_store.list_applicants(
        limit=limit
    )

    return {
        "success": True,
        "data": applicants,
        "error": None,
    }


@router.get("/applicants/{applicant_id}")
async def get_applicant(
    applicant_id: str,
):
    applicant = state_store.get_applicant(
        applicant_id
    )

    if applicant is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Applicant {applicant_id} "
                "not found."
            ),
        )

    return {
        "success": True,
        "data": applicant,
        "error": None,
    }


@router.post("/applicants")
async def create_applicant(
    request: ApplicantCreate,
):
    existing = state_store.get_applicant(
        request.applicant_id
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Applicant {request.applicant_id} "
                "already exists."
            ),
        )

    applicant = state_store.create_applicant(
        applicant_id=request.applicant_id,
        applicant_profile={
            **request.profile,
            "name": request.name,
        },
        source=request.source,
    )
    return {
        "success": True,
        "data": applicant,
        "error": None,
    }

@router.get("/cases")
async def list_cases(
    limit: int = 100,
    applicant_id: str | None = None,
):
    cases = state_store.list_cases(
        limit=limit,
        applicant_id=applicant_id,
    )

    return {
        "success": True,
        "data": cases,
        "error": None,
    }

@router.post("/cases")
async def create_case(
    request: CaseCreate,
):
    applicant = state_store.get_applicant(
        request.applicant_id
    )

    if applicant is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Applicant {request.applicant_id} "
                "not found."
            ),
        )

    case_id = _case_id()

    applicant_profile = applicant.get(
        "applicant_profile",
        {},
    )

    validation_request = UnderwriteInput(
        applicant_profile={
            **applicant_profile,
            "applicant_id": request.applicant_id,
            "name": applicant.get(
                "name",
                applicant_profile.get(
                    "name",
                    "",
                ),
            ),
        },
        submission=request.submission,
    )

    guardrail_result = _validate_underwriting_guardrails(
        validation_request,
    )

    state: UnderwritingState = _initial_state(
        case_id=case_id,
        request=validation_request,
    )
    _record_guardrail_result(
        state,
        guardrail_result,
    )

    state_store.create_case(
        case_id=case_id,
        applicant_id=request.applicant_id,
        state=dict(state),
        status="draft",
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "applicant_id": request.applicant_id,
            "status": "draft",
            "created_at": state["created_at"],
        },
        "error": None,
    }

@router.post(
    "/case/{case_id}/start",
    status_code=202,
)
async def start_existing_case(
    case_id: str,
    background_tasks: BackgroundTasks,
):
    state = state_store.get_case(case_id)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Case {case_id} not found.",
        )

    current_status = str(
        state.get("final_status", "")
    ).strip().lower()

    if current_status in {
        "processing",
        "completed",
        "awaiting_human_review",
        "human_review",
        "escalated",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Case is already in status "
                f"'{current_status}'."
            ),
        )

    guardrail_result = guardrails.validate_submission(
        state.get("applicant_profile", {}),
        state.get("submission", {}),
    )

    if not guardrail_result.allowed:
        state_store.add_workflow_event(
            case_id=case_id,
            event_type="security_guardrail",
            node="guardrails",
            status="blocked",
            message="Underwriting request blocked by security guardrails.",
            data=guardrail_result.to_dict(),
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Underwriting request blocked by security guardrails.",
                "risk_level": guardrail_result.risk_level,
                "reasons": guardrail_result.reasons,
                "checks": guardrail_result.checks,
            },
        )

    _record_guardrail_result(
        state,
        guardrail_result.to_dict(),
    )

    state["final_status"] = "processing"
    state["final_decision"] = ""
    state["final_recommendation"] = ""
    state["updated_at"] = _now()

    _save_state(
        case_id=case_id,
        state=state,
        status="processing",
    )

    background_tasks.add_task(
        _run_case,
        case_id,
        state,
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "status": "processing",
            "message": (
                "Underwriting workflow started."
            ),
            "created_at": state.get(
                "created_at",
                _now(),
            ),
        },
        "error": None,
    }

@router.get(
    "/case/{case_id}/documents",
)
async def list_case_documents(
    case_id: str,
):
    state = state_store.get_case(case_id)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Case {case_id} not found.",
        )

    documents = state_store.list_case_documents(
        case_id=case_id,
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "documents": documents,
        },
        "error": None,
    }


@router.delete(
    "/case/{case_id}/documents/{document_id}",
)
async def delete_case_document(
    case_id: str,
    document_id: str,
):
    state = state_store.get_case(case_id)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Case {case_id} not found.",
        )

    applicant_id = str(
        state.get("applicant_profile", {}).get(
            "applicant_id",
            "",
        )
    ).strip()

    if not applicant_id:
        raise HTTPException(
            status_code=400,
            detail="Case does not contain a valid applicant_id.",
        )

    try:
        deleted = document_service.delete_document(
            applicant_id=applicant_id,
            case_id=case_id,
            document_id=document_id,
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Document {document_id} "
                    f"not found for case {case_id}."
                ),
            )

        return {
            "success": True,
            "data": {
                "case_id": case_id,
                "document_id": document_id,
                "deleted": True,
            },
            "error": None,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

@router.post(
    "/case/{case_id}/documents",
    response_model=DocumentUploadResponse,
)
async def upload_case_document(
    case_id: str,
    file: UploadFile = File(...),
    document_type: str = Form(...),
):
    state = state_store.get_case(case_id)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Case {case_id} not found.",
        )

    applicant_id = str(
        state.get("applicant_profile", {}).get(
            "applicant_id",
            "",
        )
    ).strip()

    if not applicant_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Case does not contain a valid "
                "applicant_id."
            ),
        )

    try:
        result = await document_service.upload_document(
            applicant_id=applicant_id,
            case_id=case_id,
            document_type=document_type,
            upload=file,
        )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Document upload failed for case %s",
            case_id,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Document upload failed. "
                f"{str(exc)}"
            ),
        ) from exc

@router.post(
    "/underwrite",
    status_code=202,
)
async def start_underwriting(
    request: UnderwriteInput,
    background_tasks: BackgroundTasks,
):
    case_id = _case_id()

    guardrail_result = _validate_underwriting_guardrails(
        request,
        case_id=case_id,
    )

    state = _initial_state(
        case_id=case_id,
        request=request,
    )
    _record_guardrail_result(
        state,
        guardrail_result,
    )

    _save_state(
        case_id=case_id,
        state=state,
        status="pending",
    )

    background_tasks.add_task(
        _run_case,
        case_id,
        state,
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "status": "processing",
            "message": (
                "Underwriting workflow started."
            ),
            "created_at": state[
                "created_at"
            ],
        },
        "error": None,
    }


@router.get(
    "/case/{case_id}",
)
async def get_case(
    case_id: str,
):
    state = state_store.get_case(
        case_id
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Case {case_id} not found."
            ),
        )

    return {
        "success": True,
        "data": state,
        "error": None,
    }


@router.get(
    "/case/{case_id}/events",
)
async def get_case_events(
    case_id: str,
):
    state = state_store.get_case(
        case_id
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Case {case_id} not found."
            ),
        )

    events = state_store.get_workflow_events(
        case_id
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "events": events,
        },
        "error": None,
    }


@router.get(
    "/case/{case_id}/reviews",
)
async def get_case_reviews(
    case_id: str,
):
    state = state_store.get_case(
        case_id
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Case {case_id} not found."
            ),
        )

    reviews = state_store.get_human_reviews(
        case_id
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "reviews": reviews,
        },
        "error": None,
    }


@router.post(
    "/case/{case_id}/approve",
)
async def approve_case(
    case_id: str,
    body: HumanReviewInput,
):
    state = state_store.get_case(
        case_id
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Case {case_id} not found."
            ),
        )

    if state.get(
        "final_status"
    ) not in {
        "awaiting_human_review",
        "human_review",
        "escalated",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Case is not currently waiting "
                "for human review."
            ),
        )

    state["human_approved"] = True
    state["require_human_escalation"] = False
    state["require_human_review"] = False

    state["human_review_status"] = (
        "approved"
    )
    state["human_reviewed_by"] = (
        body.reviewer
    )
    state["human_review_comments"] = (
        body.comments
    )

    state["final_decision"] = "approved"
    state["final_recommendation"] = (
        "human_approved"
    )
    state["final_status"] = "completed"

    state.setdefault(
        "audit_trail",
        [],
    ).append(
        {
            "node": "human_review",
            "timestamp": _now(),
            "details": {
                "action": "approve",
                "reviewer": body.reviewer,
                "comments": body.comments,
            },
        }
    )

    _save_state(
        case_id,
        state,
        status="completed",
    )

    state_store.add_human_review(
        case_id=case_id,
        action="approve",
        reviewer=body.reviewer,
        comment=body.comments,
    )

    state_store.add_workflow_event(
        case_id=case_id,
        event_type="human_review",
        node="human_review",
        status="approved",
        data={
            "reviewer": body.reviewer,
        },
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "status": "completed",
            "final_decision": "approved",
            "human_approved": True,
        },
        "error": None,
    }


@router.post(
    "/case/{case_id}/override",
)
async def override_case(
    case_id: str,
    body: HumanOverrideInput,
):
    state = state_store.get_case(
        case_id
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Case {case_id} not found."
            ),
        )

    if state.get(
        "final_status"
    ) not in {
        "awaiting_human_review",
        "human_review",
        "escalated",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Case is not currently waiting "
                "for human review."
            ),
        )

    state["human_approved"] = True
    state["require_human_escalation"] = False
    state["require_human_review"] = False

    state["human_review_status"] = (
        "overridden"
    )
    state["human_reviewed_by"] = (
        body.reviewer
    )
    state["human_review_comments"] = (
        body.comments
    )

    state["final_decision"] = (
        body.decision
    )
    state["final_recommendation"] = (
        "human_override"
    )
    state["final_status"] = "completed"

    state.setdefault(
        "audit_trail",
        [],
    ).append(
        {
            "node": "human_review",
            "timestamp": _now(),
            "details": {
                "action": "override",
                "decision": body.decision,
                "reviewer": body.reviewer,
                "comments": body.comments,
            },
        }
    )

    _save_state(
        case_id,
        state,
        status="completed",
    )

    state_store.add_human_review(
        case_id=case_id,
        action="override",
        reviewer=body.reviewer,
        comment=body.comments,
    )

    state_store.add_workflow_event(
        case_id=case_id,
        event_type="human_review",
        node="human_review",
        status="overridden",
        data={
            "decision": body.decision,
            "reviewer": body.reviewer,
        },
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "status": "completed",
            "decision": body.decision,
        },
        "error": None,
    }


@router.post(
    "/case/{case_id}/sendback",
)
async def sendback_case(
    case_id: str,
    body: HumanSendBackInput,
    background_tasks: BackgroundTasks,
):
    state = state_store.get_case(
        case_id
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Case {case_id} not found."
            ),
        )

    if state.get(
        "final_status"
    ) not in {
        "awaiting_human_review",
        "human_review",
        "escalated",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Case is not currently waiting "
                "for human review."
            ),
        )

    state["human_review_status"] = (
        "sent_back"
    )
    state["human_reviewed_by"] = (
        body.reviewer
    )
    state["human_review_comments"] = (
        body.comments
    )

    state["human_approved"] = False
    state["require_human_escalation"] = False
    state["require_human_review"] = False

    state["reflection_requires_rescore"] = True
    state["final_status"] = "processing"
    state["final_decision"] = ""
    state["final_recommendation"] = ""

    state.setdefault(
        "audit_trail",
        [],
    ).append(
        {
            "node": "human_review",
            "timestamp": _now(),
            "details": {
                "action": "sendback",
                "reviewer": body.reviewer,
                "comments": body.comments,
            },
        }
    )

    _save_state(
        case_id,
        state,
        status="processing",
    )

    state_store.add_human_review(
        case_id=case_id,
        action="sendback",
        reviewer=body.reviewer,
        comment=body.comments,
    )

    state_store.add_workflow_event(
        case_id=case_id,
        event_type="human_review",
        node="human_review",
        status="sent_back",
        data={
            "reviewer": body.reviewer,
            "comments": body.comments,
        },
    )

    background_tasks.add_task(
        _run_case,
        case_id,
        state,
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "status": "processing",
            "message": (
                "Case sent back for "
                "reassessment."
            ),
        },
        "error": None,
    }


@router.post(
    "/case/{case_id}/escalate",
)
async def escalate_case(
    case_id: str,
    body: HumanEscalationInput,
):
    state = state_store.get_case(
        case_id
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Case {case_id} not found."
            ),
        )

    state["require_human_escalation"] = True
    state["require_human_review"] = True

    state["human_review_status"] = (
        "escalated"
    )
    state["human_reviewed_by"] = (
        body.reviewer
    )
    state["human_review_comments"] = (
        body.comments
    )

    state["final_decision"] = (
        "human_escalation"
    )
    state["final_status"] = "escalated"

    state.setdefault(
        "audit_trail",
        [],
    ).append(
        {
            "node": "human_review",
            "timestamp": _now(),
            "details": {
                "action": "escalate",
                "reviewer": body.reviewer,
                "comments": body.comments,
            },
        }
    )

    _save_state(
        case_id,
        state,
        status="escalated",
    )

    state_store.add_human_review(
        case_id=case_id,
        action="escalate",
        reviewer=body.reviewer,
        comment=body.comments,
    )

    state_store.add_workflow_event(
        case_id=case_id,
        event_type="human_review",
        node="human_review",
        status="escalated",
        data={
            "reviewer": body.reviewer,
            "comment": body.comments,
        },
    )

    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "status": "escalated",
        },
        "error": None,
    }


@router.websocket(
    "/ws/status/{case_id}",
)
async def websocket_status(
    websocket: WebSocket,
    case_id: str,
):
    await websocket.accept()

    try:
        while True:
            state = state_store.get_case(
                case_id
            )

            if state is None:
                await websocket.send_json(
                    {
                        "success": False,
                        "error": (
                            f"Case {case_id} "
                            "not found."
                        ),
                    }
                )
                break

            await websocket.send_json(
                {
                    "success": True,
                    "data": {
                        "case_id": case_id,
                        "status": state.get(
                            "final_status",
                            "processing",
                        ),
                        "workflow_trace": state.get(
                            "workflow_trace",
                            [],
                        ),
                        "final_decision": state.get(
                            "final_decision",
                            "",
                        ),
                        "final_recommendation": state.get(
                            "final_recommendation",
                            "",
                        ),
                        "overall_risk_score": state.get(
                            "overall_risk_score",
                            0.0,
                        ),
                        "medical_risk_score": state.get(
                            "medical_risk_score",
                            0.0,
                        ),
                        "claims_risk_score": state.get(
                            "claims_risk_score",
                            0.0,
                        ),
                        "coverage_gap_score": state.get(
                            "coverage_gap_score",
                            0.0,
                        ),
                        "agent2_confidence": state.get(
                            "agent2_confidence",
                            0.0,
                        ),
                        "reflection_round": state.get(
                            "reflection_round",
                            0,
                        ),
                        "reflection_verdict": state.get(
                            "reflection_verdict",
                            "",
                        ),
                        "require_human_escalation": state.get(
                            "require_human_escalation",
                            False,
                        ),
                    },
                    "error": None,
                }
            )

            if state.get(
                "final_status"
            ) in {
                "completed",
                "awaiting_human_review",
                "escalated",
                "failed",
            }:
                break

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected for %s",
            case_id,
        )