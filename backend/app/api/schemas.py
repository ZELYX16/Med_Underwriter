from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UnderwriteRequest(BaseModel):
    case_id: str | None = None

    applicant_profile: dict[str, Any] = Field(
        default_factory=dict
    )

    submission: dict[str, Any] = Field(
        default_factory=dict
    )


class UnderwriteResponse(BaseModel):
    case_id: str
    status: str
    message: str

    decision: dict[str, Any] | None = None

    workflow_trace: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )


class CaseResponse(BaseModel):
    case_id: str
    status: str
    state: dict[str, Any]


class HumanReviewRequest(BaseModel):
    approved: bool

    reviewer_id: str

    comments: str = ""

    decision: str | None = None


class HumanReviewResponse(BaseModel):
    case_id: str
    status: str
    approved: bool
    message: str