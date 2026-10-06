from __future__ import annotations

from typing import Any

from app.config import settings
from app.rag.agentic_rag import agentic_rag


class CorrectiveRAG:
    """
    Corrective RAG layer.

    It evaluates retrieval quality before evidence is used
    by downstream underwriting agents.

    The layer can:
    1. accept sufficient evidence,
    2. retry retrieval with a broader query,
    3. escalate when evidence remains insufficient.
    """

    def __init__(self) -> None:
        self.minimum_results = 1
        self.maximum_results = min(
            settings.top_k_results,
            10,
        )

    def retrieve(
        self,
        applicant_id: str,
        query: str,
        applicant_profile: dict[str, Any] | None = None,
        intent: str | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            return self._insufficient_result(
                query=query,
                reason="Empty retrieval query.",
            )

        profile = applicant_profile or {}

        initial = agentic_rag.search(
            applicant_id=applicant_id,
            query=query,
            applicant_profile=profile,
            intent=intent,
            top_k=self.maximum_results,
        )

        quality = self._evaluate_quality(
            initial
        )

        if quality["status"] == "sufficient":
            return {
                **initial,
                "crag": {
                    "status": "accepted",
                    "attempts": 1,
                    "quality": quality,
                    "correction_applied": False,
                    "human_review_required": False,
                },
            }

        corrected_query = self._build_corrected_query(
            query=query,
            profile=profile,
        )

        corrected = agentic_rag.search(
            applicant_id=applicant_id,
            query=corrected_query,
            applicant_profile=profile,
            intent=intent,
            top_k=self.maximum_results,
        )

        corrected_quality = (
            self._evaluate_quality(corrected)
        )

        if (
            corrected_quality["status"]
            == "sufficient"
        ):
            return {
                **corrected,
                "original_query": query,
                "corrected_query": corrected_query,
                "crag": {
                    "status": "corrected",
                    "attempts": 2,
                    "quality": corrected_quality,
                    "correction_applied": True,
                    "human_review_required": False,
                },
            }

        return {
            **corrected,
            "original_query": query,
            "corrected_query": corrected_query,
            "crag": {
                "status": "insufficient",
                "attempts": 2,
                "quality": corrected_quality,
                "correction_applied": True,
                "human_review_required": True,
            },
        }

    def _evaluate_quality(
        self,
        results: dict[str, Any],
    ) -> dict[str, Any]:
        total_results = int(
            results.get(
                "total_results",
                0,
            )
            or 0
        )

        sources = results.get(
            "sources_used",
            [],
        )

        if total_results < self.minimum_results:
            return {
                "status": "insufficient",
                "reason": "No usable retrieval results.",
                "result_count": total_results,
                "sources": sources,
            }

        evidence_count = self._count_evidence(
            results.get(
                "results",
                {},
            )
        )

        if evidence_count == 0:
            return {
                "status": "insufficient",
                "reason": "Retrieved sources contain no evidence.",
                "result_count": total_results,
                "sources": sources,
            }

        return {
            "status": "sufficient",
            "reason": "Retrieval returned usable evidence.",
            "result_count": total_results,
            "evidence_count": evidence_count,
            "sources": sources,
        }

    def _count_evidence(
        self,
        value: Any,
    ) -> int:
        if isinstance(value, list):
            return len(value)

        if isinstance(value, dict):
            count = 0

            if "results" in value:
                nested = value.get(
                    "results"
                )

                if isinstance(
                    nested,
                    list,
                ):
                    count += len(nested)
                elif isinstance(
                    nested,
                    dict,
                ):
                    count += self._count_evidence(
                        nested
                    )

            for key, item in value.items():
                if key == "results":
                    continue

                if isinstance(
                    item,
                    (dict, list),
                ):
                    count += self._count_evidence(
                        item
                    )

            return count

        return 0

    def _build_corrected_query(
        self,
        query: str,
        profile: dict[str, Any],
    ) -> str:
        conditions = profile.get(
            "medical_conditions",
            profile.get(
                "conditions",
                [],
            ),
        )

        medications = profile.get(
            "medications",
            [],
        )

        parts = [
            query.strip(),
        ]

        if conditions:
            if isinstance(
                conditions,
                list,
            ):
                parts.append(
                    "Relevant conditions: "
                    + ", ".join(
                        str(item)
                        for item in conditions
                    )
                )
            else:
                parts.append(
                    f"Relevant condition: {conditions}"
                )

        if medications:
            if isinstance(
                medications,
                list,
            ):
                parts.append(
                    "Relevant medications: "
                    + ", ".join(
                        str(item)
                        for item in medications
                    )
                )
            else:
                parts.append(
                    f"Relevant medication: {medications}"
                )

        return " ".join(parts)

    def _insufficient_result(
        self,
        query: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "intent": None,
            "sources_used": [],
            "results": {},
            "total_results": 0,
            "crag": {
                "status": "insufficient",
                "attempts": 0,
                "quality": {
                    "status": "insufficient",
                    "reason": reason,
                },
                "correction_applied": False,
                "human_review_required": True,
            },
        }


crag = CorrectiveRAG()