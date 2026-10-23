from __future__ import annotations

from typing import Any

from app.config import settings
from app.rag.budget import current_budget
from app.rag.hybrid_rag import hybrid_rag
from app.rag.medgraph_rag import medgraph_rag


class CRAG:
    """
    Corrective Retrieval-Augmented Generation.

    Evaluates retrieved evidence quality and performs
    corrective or supplementary retrieval without
    crossing evidence boundaries.
    """

    SOURCE_SCOPES = {
        "applicant",
        "knowledge",
    }

    def __init__(self) -> None:
        self.default_top_k = 5

    async def retrieve(
        self,
        query: str,
        intent: str,
        context: dict[str, Any] | None = None,
        top_k: int | None = None,
        source_scope: str = "knowledge",
    ) -> dict[str, Any]:
        context = context or {}

        if source_scope not in self.SOURCE_SCOPES:
            source_scope = "knowledge"

        limit = max(
            1,
            min(
                top_k or self.default_top_k,
                20,
            ),
        )

        initial_results = self._initial_retrieval(
            query=query,
            intent=intent,
            context=context,
            top_k=limit,
            source_scope=source_scope,
        )

        initial_quality = self._evaluate_quality(
            query=query,
            results=initial_results,
        )

        corrective_results: list[dict[str, Any]] = []
        retrieval_mode = "initial"

        # Correction is optional: only when it is enabled and the case's
        # retrieval budget still has room.
        budget = current_budget()
        may_correct = (
            settings.crag_max_correction_rounds > 0
            and (budget is None or not budget.exhausted())
        )

        if not may_correct:
            pass

        elif initial_quality["score"] < 0.3:
            corrective_results = self._corrective_retrieval(
                query=query,
                intent=intent,
                context=context,
                top_k=limit,
                source_scope=source_scope,
            )
            retrieval_mode = "corrective"

        elif initial_quality["score"] < 0.7:
            corrective_results = self._supplement_retrieval(
                query=query,
                intent=intent,
                context=context,
                top_k=limit,
                source_scope=source_scope,
            )
            retrieval_mode = "supplement"

        final_results = self._deduplicate(
            initial_results + corrective_results
        )

        final_results = final_results[:limit]
        corrective_results = [
            r for r in corrective_results if r in final_results
        ]

        final_quality = self._evaluate_quality(
            query=query,
            results=final_results,
        )

        return {
            "query": query,
            "intent": intent,
            "source_scope": source_scope,
            "results": final_results,
            "total_results": len(final_results),
            "initial_quality_score": initial_quality["score"],
            "initial_quality_band": initial_quality["band"],
            "quality_score": final_quality["score"],
            "quality_band": final_quality["band"],
            "retrieval_mode": retrieval_mode,
            "corrective_retrieval": bool(
                corrective_results
            ),
        }

    def _initial_retrieval(
        self,
        query: str,
        intent: str,
        context: dict[str, Any],
        top_k: int,
        source_scope: str,
    ) -> list[dict[str, Any]]:
        if source_scope == "applicant":
            applicant_id = self._get_applicant_id(
                context
            )

            return self._search_applicant(
                query=query,
                intent=intent,
                applicant_id=applicant_id,
                top_k=top_k,
            )

        if source_scope == "knowledge":
            if intent == "medical":
                return self._safe_call(
                    lambda: medgraph_rag.search_medical_knowledge(
                        query=query,
                        top_k=top_k,
                    )
                )

            if intent == "regulatory":
                return self._safe_call(
                    lambda: hybrid_rag.search_regulatory(
                        query=query,
                        jurisdiction="India",
                        top_k=top_k,
                    )
                )

            if intent == "underwriting":
                return self._safe_call(
                    lambda: hybrid_rag.search_underwriting(
                        query=query,
                        product=self._get_product(
                            context
                        ),
                        top_k=top_k,
                    )
                )

        return []

    def _corrective_retrieval(
        self,
        query: str,
        intent: str,
        context: dict[str, Any],
        top_k: int,
        source_scope: str,
    ) -> list[dict[str, Any]]:
        broadened_query = self._broaden_query(
            query=query,
            intent=intent,
        )

        return self._initial_retrieval(
            query=broadened_query,
            intent=intent,
            context=context,
            top_k=top_k,
            source_scope=source_scope,
        )

    def _supplement_retrieval(
        self,
        query: str,
        intent: str,
        context: dict[str, Any],
        top_k: int,
        source_scope: str,
    ) -> list[dict[str, Any]]:
        broadened_query = self._broaden_query(
            query=query,
            intent=intent,
        )

        return self._initial_retrieval(
            query=broadened_query,
            intent=intent,
            context=context,
            top_k=max(
                1,
                top_k // 2,
            ),
            source_scope=source_scope,
        )

    def _search_applicant(
        self,
        query: str,
        intent: str,
        applicant_id: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not applicant_id:
            return []

        if intent == "medical":
            return self._safe_call(
                lambda: __import__(
                    "app.rag.retriever",
                    fromlist=["retriever"],
                ).retriever.retrieve_medical_evidence(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )
            )

        if intent == "claims":
            return self._safe_call(
                lambda: __import__(
                    "app.rag.retriever",
                    fromlist=["retriever"],
                ).retriever.retrieve_claims_evidence(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )
            )

        if intent == "policy":
            return self._safe_call(
                lambda: __import__(
                    "app.rag.retriever",
                    fromlist=["retriever"],
                ).retriever.retrieve_policy_evidence(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )
            )

        if intent == "underwriting":
            return self._safe_call(
                lambda: __import__(
                    "app.rag.retriever",
                    fromlist=["retriever"],
                ).retriever.retrieve_underwriting_submission(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )
            )

        return []

    @staticmethod
    def _get_applicant_id(
        context: dict[str, Any],
    ) -> str:
        applicant_id = (
            context.get("applicant_id")
            or context.get(
                "applicant_profile",
                {},
            ).get(
                "applicant_id",
                "",
            )
        )

        return str(
            applicant_id or ""
        ).strip()

    @staticmethod
    def _get_product(
        context: dict[str, Any],
    ) -> str | None:
        submission = context.get(
            "submission",
            {},
        )

        if not isinstance(
            submission,
            dict,
        ):
            return None

        product = submission.get(
            "product"
        )

        if product is None:
            return None

        return str(product)

    @staticmethod
    def _safe_call(
        function: Any,
    ) -> list[dict[str, Any]]:
        try:
            result = function()

            if isinstance(
                result,
                list,
            ):
                return result

        except Exception:
            pass

        return []

    @staticmethod
    def _broaden_query(
        query: str,
        intent: str,
    ) -> str:
        suffixes = {
            "medical": (
                "diagnosis condition treatment "
                "medication clinical history"
            ),
            "claims": (
                "claim hospitalization admission "
                "treatment utilization history"
            ),
            "policy": (
                "policy coverage sum insured "
                "deductible exclusion status"
            ),
            "coverage": (
                "coverage adequacy "
                "sum insured benefits exclusions "
                "limitations"
            ),
            "underwriting": (
                "underwriting risk assessment "
                "medical disclosure requirements"
            ),
            "regulatory": (
                "IRDAI health insurance regulation "
                "compliance requirement"
            ),
        }

        suffix = suffixes.get(
            intent,
            "relevant evidence",
        )

        return (
            f"{str(query or '').strip()} "
            f"{suffix}"
        ).strip()

    @classmethod
    def _evaluate_quality(
        cls,
        query: str,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not results:
            return {
                "score": 0.0,
                "band": "poor",
                "relevance": 0.0,
                "evidence_volume": 0.0,
                "usable_results": 0,
            }

        query_terms = cls._query_terms(
            query
        )

        usable_results = 0
        grounded_results = 0

        for result in results:
            content = cls._extract_content(
                result
            )

            if len(content.strip()) < 20:
                continue

            usable_results += 1

            if cls._has_query_match(
                query_terms,
                content,
            ):
                grounded_results += 1

        relevance = (
            grounded_results / usable_results
            if usable_results
            else 0.0
        )

        evidence_volume = min(
            usable_results / 5,
            1.0,
        )

        score = (
            relevance * 0.7
            + evidence_volume * 0.3
        )

        if score < 0.3:
            band = "poor"
        elif score < 0.7:
            band = "moderate"
        else:
            band = "good"

        return {
            "score": round(
                score,
                3,
            ),
            "band": band,
            "relevance": round(
                relevance,
                3,
            ),
            "evidence_volume": round(
                evidence_volume,
                3,
            ),
            "usable_results": usable_results,
        }

    @staticmethod
    def _query_terms(
        query: str,
    ) -> set[str]:
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "are",
            "was",
            "were",
            "has",
            "have",
            "had",
            "what",
            "which",
            "who",
            "how",
            "why",
            "into",
            "about",
            "patient",
            "applicant",
        }

        return {
            term.strip(
                ".,:;!?()[]{}\"'"
            ).lower()
            for term in str(
                query or ""
            ).split()
            if len(
                term.strip(
                    ".,:;!?()[]{}\"'"
                )
            ) > 2
            and term.strip(
                ".,:;!?()[]{}\"'"
            ).lower()
            not in stop_words
        }

    @staticmethod
    def _extract_content(
        result: dict[str, Any],
    ) -> str:
        content = result.get(
            "content"
        )

        if content:
            return str(content)

        text = result.get(
            "text"
        )

        if text:
            return str(text)

        document = result.get(
            "document"
        )

        if document:
            return str(document)

        return ""

    @staticmethod
    def _has_query_match(
        query_terms: set[str],
        content: str,
    ) -> bool:
        if not query_terms:
            return bool(
                content.strip()
            )

        normalized_content = (
            content.lower()
        )

        return any(
            term in normalized_content
            for term in query_terms
        )

    @staticmethod
    def _deduplicate(
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()

        for result in results:
            metadata = result.get(
                "metadata",
                {},
            )

            if not isinstance(
                metadata,
                dict,
            ):
                metadata = {}

            key = (
                result.get(
                    "document_id"
                )
                or metadata.get(
                    "document_id"
                )
                or result.get(
                    "file_name"
                )
                or metadata.get(
                    "file_name"
                )
                or result.get(
                    "id"
                )
                or metadata.get(
                    "id"
                )
                or result.get(
                    "content",
                    ""
                )[:150]
            )

            if not key:
                key = str(
                    len(unique)
                )

            key = str(key)

            if key in seen:
                continue

            seen.add(key)
            unique.append(result)

        return unique


crag = CRAG()