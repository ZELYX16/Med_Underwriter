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
    BatchPlanInput,
    BatchStartInput,
    CaseCreate,
    DocumentUploadResponse,
)
from app.cache.pattern_cache import pattern_cache
from app.config import settings
from app.orchestrator.graph import run_workflow
from app.services.batch import describe_plan, plan_groups, run_batch
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
        return_case=False,
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

    # SQLite is synchronous: keep it off the event loop so status polling
    # and /health stay responsive while a case runs.
    def _write() -> None:
        state_store.save_case(
            case_id=case_id,
            state=current,
            status=db_status,
            return_case=False,
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

    await asyncio.to_thread(_write)


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

        # Validate the decision and the generated narrative together.
        output_guardrail = guardrails.validate_output(
            f"{result.get('final_decision', '')} "
            f"{result.get('agent2_reasoning', '')}"
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
        if final_status == "failed":
            # A node failed internally: hand over to an underwriter with a
            # plain-language reason instead of a dead-end failed state.
            if not result.get("human_review_reason"):
                result["human_review_reason"] = (
                    "Automated processing could not be completed for "
                    "this case. Manual underwriting review is required."
                )
            result["require_human_review"] = True

        human_review_required = bool(
            result.get("require_human_review")
            or result.get("require_human_escalation")
            or result.get("human_review_reasons")
            or result.get("business_gate_reasons")
            or result.get("mandatory_review_reasons")
            or result.get("security_review_reasons")
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

        # Never leave the user on a dead-end "failed" page: hand the case
        # to an underwriter with a plain-language reason. The technical
        # error stays in `errors` / the event log for support.
        current["final_status"] = "awaiting_human_review"
        current["human_review_status"] = "awaiting_review"
        current["require_human_review"] = True
        current["require_human_escalation"] = True
        current["human_review_reason"] = (
            "Automated processing could not be completed for this case. "
            "Manual underwriting review is required."
        )
        current["final_decision"] = "pending_human_review"
        current["updated_at"] = _now()

        _save_state(
            case_id,
            current,
            status="awaiting-human-review",
        )

        state_store.add_workflow_event(
            case_id=case_id,
            event_type="workflow",
            node="workflow",
            status="routed_to_human_review",
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

class AwaitingDocuments(Exception):
    """Required documents are missing; the case waits instead of running."""

    def __init__(self, missing: list[dict[str, Any]]) -> None:
        super().__init__("Awaiting documents")
        self.missing = missing


def _document_check(state: dict[str, Any]) -> dict[str, Any] | None:
    """Which documents are required / missing for this case (None = can't tell)."""
    try:
        from app.rag.structured import (
            applicant_files,
            build_applicant_facts,
            document_requirements,
        )

        profile = state.get("applicant_profile") or {}
        applicant_id = profile.get("applicant_id") or state.get("applicant_id")
        if not applicant_id:
            return None
        db_paths = [
            d.get("file_path")
            for d in state_store.list_applicant_documents(applicant_id)
            if d.get("file_path")
        ]
        paths = applicant_files(
            applicant_id, settings.synthetic_data_directory, db_paths
        )
        if not paths:
            return None
        facts = build_applicant_facts(paths)
        return document_requirements(
            facts,
            profile,
            state.get("submission") or {},
            age_threshold=settings.doc_medical_age_threshold,
            sum_insured_threshold=settings.doc_medical_sum_insured_threshold,
        )
    except Exception:
        logger.exception("Document requirement check failed; continuing")
        return None


def _prepare_case_for_run(case_id: str, proceed: bool = False) -> dict[str, Any]:
    """Validate a case and mark it processing; shared by start and batch."""
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
        quarantine = guardrails.quarantine_submission(
            state.get("applicant_profile", {}),
            state.get("submission", {}),
        )

        if not quarantine["recoverable"]:
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

        # Keep the audit record of what was found, then continue on the
        # clean remainder with mandatory human review.
        _record_guardrail_result(state, guardrail_result.to_dict())
        state["applicant_profile"] = quarantine["profile"]
        state["submission"] = quarantine["submission"]
        state["quarantined_inputs"] = list(
            state.get("quarantined_inputs") or []
        ) + quarantine["items"]
        state["security_review_reasons"] = list(
            dict.fromkeys(
                list(state.get("security_review_reasons") or [])
                + [
                    f"'{item['field']}' was excluded from analysis "
                    f"({'; '.join(item['reasons'])})"
                    for item in quarantine["items"]
                ]
            )
        )
        state_store.add_workflow_event(
            case_id=case_id,
            event_type="security_guardrail",
            node="guardrails",
            status="quarantined",
            message=(
                f"{len(quarantine['items'])} input field(s) excluded from "
                "analysis by security guardrails; human review required."
            ),
            data={"items": quarantine["items"]},
        )
        guardrail_result = quarantine["recheck"]

    _record_guardrail_result(
        state,
        guardrail_result.to_dict(),
    )

    requirements = _document_check(state)
    if requirements and requirements["blocking_missing"] and not proceed:
        state["final_status"] = "awaiting_documents"
        state["missing_documents"] = (
            requirements["blocking_missing"] + requirements["non_blocking_missing"]
        )
        state["updated_at"] = _now()
        _save_state(
            case_id=case_id,
            state=state,
            status="awaiting_documents",
        )
        state_store.add_workflow_event(
            case_id=case_id,
            event_type="documents",
            node="documents",
            status="awaiting",
            message="Waiting for required documents: "
            + "; ".join(m["document"] for m in requirements["blocking_missing"]),
            data={"missing": state["missing_documents"]},
        )
        raise AwaitingDocuments(requirements["blocking_missing"])

    # A new run decides afresh; within the run the reasons only accumulate.
    state["mandatory_review_reasons"] = []
    state["missing_documents"] = (
        requirements["non_blocking_missing"] if requirements else []
    )
    if requirements and requirements["blocking_missing"] and proceed:
        state["document_override"] = (
            "Underwriter proceeded without: "
            + "; ".join(m["document"] for m in requirements["blocking_missing"])
        )
        state_store.add_workflow_event(
            case_id=case_id,
            event_type="documents",
            node="documents",
            status="override",
            message=state["document_override"],
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

    return state


@router.post(
    "/case/{case_id}/start",
    status_code=202,
)
async def start_existing_case(
    case_id: str,
    background_tasks: BackgroundTasks,
    proceed: bool = False,
):
    try:
        state = await asyncio.to_thread(_prepare_case_for_run, case_id, proceed)
    except AwaitingDocuments as waiting:
        return {
            "success": True,
            "data": {
                "case_id": case_id,
                "status": "awaiting_documents",
                "missing": waiting.missing,
                "message": (
                    "Required documents are missing. Upload them, or start "
                    "again with proceed=true to underwrite without them."
                ),
            },
            "error": None,
        }

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

@router.post("/cases/batch/plan")
async def plan_batch(body: BatchPlanInput):
    """Propose groups of similar cases, with reasons, without running anything."""
    if body.case_ids is None:
        listed = await asyncio.to_thread(state_store.list_cases, limit=1000)
        ids = [
            c["case_id"]
            for c in listed
            if str(c.get("status", "")).strip().lower() in {"draft", "pending"}
        ]
    else:
        ids = list(dict.fromkeys(body.case_ids))

    cases: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    for case_id in ids:
        state = await asyncio.to_thread(state_store.get_case, case_id)
        if state is None:
            skipped[case_id] = "Case not found."
            continue
        status = str(state.get("final_status", "")).strip().lower()
        if status in {
            "processing",
            "completed",
            "awaiting_human_review",
            "human_review",
            "escalated",
        }:
            skipped[case_id] = f"Already {status}."
            continue
        cases[case_id] = state

    return {
        "success": True,
        "data": {
            "groups": describe_plan(cases),
            "skipped": skipped,
        },
        "error": None,
    }


@router.post(
    "/cases/batch",
    status_code=202,
)
async def start_batch(
    body: BatchStartInput,
    background_tasks: BackgroundTasks,
):
    """Start several drafted cases; similar ones share retrieval work."""
    prepared: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}

    for case_id in dict.fromkeys(body.case_ids):
        try:
            prepared[case_id] = _prepare_case_for_run(case_id)
        except AwaitingDocuments as waiting:
            skipped[case_id] = "Awaiting documents: " + "; ".join(
                m["document"] for m in waiting.missing
            )
        except HTTPException as exc:
            skipped[case_id] = (
                exc.detail if isinstance(exc.detail, str) else "Not eligible."
            )

    if prepared:
        for group in describe_plan(prepared):
            for case_id in group["case_ids"]:
                size = len(group["case_ids"])
                state_store.add_workflow_event(
                    case_id=case_id,
                    event_type="batch",
                    node="batch",
                    status="grouped" if group["grouped"] else "single",
                    message=(
                        f"Run in batch group {group['group_id']} with "
                        f"{size - 1} other similar case(s): {group['reason']}"
                        if group["grouped"]
                        else "Run in a batch, on its own (no similar case in the selection)."
                    ),
                    data={
                        "group_id": group["group_id"],
                        "case_ids": group["case_ids"],
                        "shares": group["shares"],
                    },
                )
        background_tasks.add_task(run_batch, prepared, _run_case)

    return {
        "success": True,
        "data": {
            "accepted": list(prepared),
            "skipped": skipped,
            "groups": [len(g) for g in plan_groups(prepared)],
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


@router.get(
    "/case/{case_id}/status",
)
async def get_case_status(
    case_id: str,
):
    """Lightweight status for polling; avoids loading the full case."""
    data = await asyncio.to_thread(
        state_store.get_case_status,
        case_id,
    )

    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Case not found.",
        )

    return {
        "success": True,
        "data": data,
        "error": None,
    }


def _case_label(case_id: str) -> dict[str, Any]:
    """Short description of a cache source case for the UI."""
    case = state_store.get_case(case_id)
    if not case:
        return {"case_id": case_id, "exists": False}
    profile = case.get("applicant_profile") or {}
    submission = case.get("submission") or {}
    return {
        "case_id": case_id,
        "exists": True,
        "applicant": profile.get("name") or profile.get("applicant_id"),
        "product": submission.get("product"),
        "status": case.get("status") or case.get("final_status"),
    }


@router.get(
    "/case/{case_id}/cache",
)
async def get_case_cache(
    case_id: str,
):
    """Which cached patterns this case reused, and which case stored them."""
    case = await asyncio.to_thread(state_store.get_case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    agent_metrics = case.get("agent_metrics") or {}
    entries: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    for agent in ("agent1", "agent2"):
        metrics = agent_metrics.get(agent) or {}
        for event in metrics.get("cache_events") or []:
            entry = {**event, "agent": agent}
            source = event.get("source_case_id")
            if source and source != case_id:
                if source not in sources:
                    sources[source] = await asyncio.to_thread(
                        _case_label, source
                    )
                entry["source"] = sources[source]
            entries.append(entry)

    hits = sum(1 for e in entries if e.get("outcome") == "hit")
    return {
        "success": True,
        "data": {
            "case_id": case_id,
            "entries": entries,
            "summary": {
                "hits": hits,
                "misses": sum(1 for e in entries if e.get("outcome") == "miss"),
                "stored": sum(1 for e in entries if e.get("outcome") == "stored"),
                "skipped": sum(1 for e in entries if e.get("outcome") == "skipped"),
            },
            "cache_totals": pattern_cache.stats(),
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

    # A human disagreed with the automated outcome: don't reuse its
    # narrative for future similar cases.
    pattern_cache.invalidate("rationale", state.get("reasoning_cache_key"))

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

    pattern_cache.invalidate("rationale", state.get("reasoning_cache_key"))

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