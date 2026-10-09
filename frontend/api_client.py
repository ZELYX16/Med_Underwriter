from __future__ import annotations

from typing import Any

import requests

from config import settings


class APIError(RuntimeError):
    """Raised when the backend request fails."""


class APIClient:
    def __init__(self) -> None:
        self.base_url = settings.backend_url.rstrip("/")
        self.timeout = settings.request_timeout

    # ========================================================
    # CORE REQUEST
    # ========================================================

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise APIError(
                f"Unable to connect to backend: {exc}"
            ) from exc

        if not response.ok:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text

            raise APIError(
                f"Backend returned "
                f"{response.status_code}: {detail}"
            )

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError:
            return response.text

    # ========================================================
    # HEALTH
    # ========================================================

    def health(self) -> Any:
        for path in (
            "/health",
            "/api/health",
        ):
            try:
                return self._request(
                    "GET",
                    path,
                )
            except APIError:
                continue

        raise APIError(
            "Backend health endpoint is unavailable."
        )

    # ========================================================
    # APPLICANTS
    # ========================================================

    def list_applicants(
        self,
        limit: int = 100,
        search: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {
            "limit": limit,
        }

        if search:
            params["search"] = search

        return self._request(
            "GET",
            "/api/applicants",
            params=params,
        )

    def get_applicant(
        self,
        applicant_id: str,
    ) -> Any:
        return self._request(
            "GET",
            f"/api/applicants/{applicant_id}",
        )

    def create_applicant(
        self,
        applicant_id: str,
        name: str,
        profile: dict[str, Any],
        source: str = "manual",
    ) -> Any:
        return self._request(
            "POST",
            "/api/applicants",
            json={
                "applicant_id": applicant_id,
                "name": name,
                "profile": profile,
                "source": source,
            },
        )

    # ========================================================
    # CASES
    # ========================================================

    def list_cases(
        self,
        limit: int = 100,
        applicant_id: str | None = None,
        status: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {
            "limit": limit,
        }

        if applicant_id:
            params["applicant_id"] = applicant_id

        if status:
            params["status"] = status

        return self._request(
            "GET",
            "/api/cases",
            params=params,
        )

    def get_case(
        self,
        case_id: str,
    ) -> Any:
        return self._request(
            "GET",
            f"/api/case/{case_id}",
        )

    def create_case(
        self,
        applicant_id: str,
        submission: dict[str, Any],
    ) -> Any:
        return self._request(
            "POST",
            "/api/cases",
            json={
                "applicant_id": applicant_id,
                "submission": submission,
            },
        )

    def start_case(
        self,
        case_id: str,
    ) -> Any:
        return self._request(
            "POST",
            f"/api/case/{case_id}/start",
        )

    # ========================================================
    # DOCUMENTS
    # ========================================================

    def list_case_documents(
        self,
        case_id: str,
    ) -> Any:
        return self._request(
            "GET",
            f"/api/case/{case_id}/documents",
        )

    def upload_document(
        self,
        case_id: str,
        document_type: str,
        file: Any,
    ) -> Any:
        files = {
            "file": (
                file.name,
                file.getvalue(),
                file.type
                or "application/octet-stream",
            )
        }

        data = {
            "document_type": document_type,
        }

        return self._request(
            "POST",
            f"/api/case/{case_id}/documents",
            files=files,
            data=data,
        )

    def delete_document(
        self,
        case_id: str,
        document_id: str,
    ) -> Any:
        return self._request(
            "DELETE",
            f"/api/case/{case_id}/documents/{document_id}",
        )

    # ========================================================
    # WORKFLOW
    # ========================================================

    def get_events(
        self,
        case_id: str,
    ) -> Any:
        return self._request(
            "GET",
            f"/api/case/{case_id}/events",
        )

    def get_reviews(
        self,
        case_id: str,
    ) -> Any:
        return self._request(
            "GET",
            f"/api/case/{case_id}/reviews",
        )

    # ========================================================
    # HUMAN REVIEW
    # ========================================================

    def _review(
        self,
        case_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> Any:
        """Record an explicit human-review lifecycle action."""
        paths = {
            "approve": f"/api/case/{case_id}/approve",
            "override": f"/api/case/{case_id}/override",
            "sendback": f"/api/case/{case_id}/sendback",
            "escalate": f"/api/case/{case_id}/escalate",
        }
        path = paths.get(action)
        if not path:
            raise APIError(f"Unsupported human review action: {action}")
        return self._request(
            "POST",
            path,
            json=payload,
        )

    def approve(
        self,
        case_id: str,
        reviewer: str,
        comments: str = "",
    ) -> Any:
        return self._review(
            case_id,
            "approve",
            {"reviewer": reviewer, "comments": comments},
        )

    def override(
        self,
        case_id: str,
        reviewer: str,
        decision: str,
        comments: str = "",
    ) -> Any:
        return self._review(
            case_id,
            "override",
            {
                "reviewer": reviewer,
                "decision": decision,
                "comments": comments,
            },
        )

    def sendback(
        self,
        case_id: str,
        reviewer: str,
        comments: str,
    ) -> Any:
        return self._review(
            case_id,
            "sendback",
            {"reviewer": reviewer, "comments": comments},
        )

    def escalate(
        self,
        case_id: str,
        reviewer: str,
        comments: str = "",
    ) -> Any:
        return self._review(
            case_id,
            "escalate",
            {"reviewer": reviewer, "comments": comments},
        )


api = APIClient()