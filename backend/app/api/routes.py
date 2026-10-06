from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    CaseResponse,
    HumanReviewRequest,
    HumanReviewResponse,
    UnderwriteRequest,
    UnderwriteResponse,
)
from app.models.state import UnderwritingState
from app.orchestrator.graph import underwriting_graph
from app.store.state_store import state_store


router = APIRouter(
    prefix="/api",
    tags=["Underwriting"],
)


def _create_case_id() -> str:
    return f"UW-{uuid4().hex[:10].upper()}"


@router.post(
    "/underwrite",
    response_model=UnderwriteResponse,
)
async def underwrite(
    request: UnderwriteRequest,
) -> UnderwriteResponse:

    case_id = (
        request.case_id
        or _create_case_id()
    )

    initial_state: UnderwritingState = {
        "case_id": case_id,
        "applicant_profile": (
            request.applicant_profile
        ),
        "submission": (
            request.submission
        ),
        "raw_request": request.model_dump(),
        "workflow_status": "starting",
        "workflow_trace": [],
        "audit_trail": [],
        "errors": [],
    }

    try:
        result = await underwriting_graph.ainvoke(
            initial_state
        )

    except Exception as exc:
        state_store.update_case_status(
            case_id=case_id,
            status="failed",
        )

        raise HTTPException(
            status_code=500,
            detail=f"Underwriting workflow failed: {exc}",
        ) from exc

    result["case_id"] = case_id

    state_store.save_case(
        case_id=case_id,
        state=result,
        status=result.get(
            "workflow_status",
            "completed",
        ),
    )

    status = result.get(
        "workflow_status",
        "completed",
    )

    if status == "awaiting_human_review":
        message = (
            "Case requires human underwriter review."
        )
    else:
        message = (
            "Underwriting workflow completed."
        )

    return UnderwriteResponse(
        case_id=case_id,
        status=status,
        message=message,
        decision=result.get(
            "final_decision"
        ),
        workflow_trace=result.get(
            "workflow_trace",
            [],
        ),
    )


@router.get(
    "/case/{case_id}",
    response_model=CaseResponse,
)
async def get_case(
    case_id: str,
) -> CaseResponse:

    case = state_store.get_case(
        case_id
    )

    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found.",
        )

    return CaseResponse(
        case_id=case_id,
        status=case.get(
            "status",
            "unknown",
        ),
        state=case.get(
            "state",
            {},
        ),
    )


@router.get(
    "/case/{case_id}/trace",
)
async def get_case_trace(
    case_id: str,
):
    case = state_store.get_case(
        case_id
    )

    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found.",
        )

    return {
        "case_id": case_id,
        "workflow_trace": case.get(
            "state",
            {},
        ).get(
            "workflow_trace",
            [],
        ),
    }


@router.post(
    "/case/{case_id}/human-review",
    response_model=HumanReviewResponse,
)
async def human_review(
    case_id: str,
    request: HumanReviewRequest,
) -> HumanReviewResponse:

    case = state_store.get_case(
        case_id
    )

    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found.",
        )

    state = case.get(
        "state",
        {},
    )

    if not state.get(
        "require_human_review",
        False,
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "This case is not currently "
                "waiting for human review."
            ),
        )

    review_status = (
        "human_approved"
        if request.approved
        else "human_rejected"
    )

    final_decision = (
        state.get(
            "final_decision",
            {},
        ).copy()
    )

    final_decision.update(
        {
            "status": review_status,
            "human_review": {
                "reviewer_id": request.reviewer_id,
                "approved": request.approved,
                "comments": request.comments,
                "decision": request.decision,
            },
        }
    )

    state["human_approved"] = (
        request.approved
    )

    state["human_reviewer_id"] = (
        request.reviewer_id
    )

    state["human_review_comments"] = (
        request.comments
    )

    state["human_review_decision"] = (
        request.decision
    )

    state["final_decision"] = (
        final_decision
    )

    state["decision_status"] = (
        review_status
    )

    state["workflow_status"] = (
        "completed"
    )

    state_store.save_human_review(
        case_id=case_id,
        reviewer=request.reviewer_id,
        approved=request.approved,
        notes=request.comments or (request.decision or ""),
    )

    state_store.save_case(
        case_id=case_id,
        state=state,
        status="completed",
    )

    return HumanReviewResponse(
        case_id=case_id,
        status="completed",
        approved=request.approved,
        message=(
            "Human review recorded successfully."
        ),
    )