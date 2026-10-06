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

    model_config = {
        "json_schema_extra": {
            "example": {
                "case_id": "UW-TEST-001",
                "applicant_profile": {
                    "applicant_id": "APP-TEST-001",
                    "name": "Priya Menon",
                    "age": 31,
                    "gender": "F",
                    "occupation": "Software Engineer",
                    "bmi": 22.4,
                    "medical_conditions": [],
                    "medications": [],
                    "lifestyle": {
                        "smoker": False,
                        "alcohol": "occasional"
                    }
                },
                "submission": {
                    "product": "Comprehensive Health Plan",
                    "sum_insured": 500000,
                    "policy_term_years": 1,
                    "declared_pre_existing_conditions": []
                }
            }
        }
    }


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