from __future__ import annotations

from typing import Any

from app.config import settings
from app.rag.hybrid_rag import hybrid_rag
from app.rag.medgraph_rag import medgraph_rag
from app.rag.query_classifier import query_classifier
from app.rag.retriever import retriever


class AgenticRAG:
    """
    Coordinates retrieval across the different knowledge domains.

    Retrieval domains:
        - applicant medical evidence
        - applicant claims
        - applicant policy
        - medical knowledge
        - regulatory knowledge
        - underwriting knowledge

    Query classification is delegated to QueryClassifier so
    routing rules are maintained in one place.
    """

    def __init__(self) -> None:
        self.top_k = settings.top_k_results

    def search(
        self,
        applicant_id: str,
        query: str,
        applicant_profile: dict[str, Any] | None = None,
        intent: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            return {
                "query": query,
                "intent": "broad",
                "intent_confidence": 0.0,
                "sources_used": [],
                "results": {},
                "total_results": 0,
            }

        profile = applicant_profile or {}
        limit = top_k or self.top_k

        if intent:
            classification = {
                "intent": intent,
                "confidence": 1.0,
                "matched_terms": [],
                "reason": (
                    "Intent supplied by caller."
                ),
            }
        else:
            classification = (
                query_classifier.classify(
                    query=query,
                    context={
                        "applicant_id": applicant_id,
                        "applicant_profile": profile,
                    },
                )
            )

        resolved_intent = classification[
            "intent"
        ]

        if resolved_intent == "medical":
            result = self._medical_search(
                applicant_id=applicant_id,
                query=query,
                top_k=limit,
            )

        elif resolved_intent == "regulatory":
            result = self._regulatory_search(
                query=query,
                top_k=limit,
            )

        elif resolved_intent == "underwriting":
            result = self._underwriting_search(
                query=query,
                profile=profile,
                top_k=limit,
            )

        elif resolved_intent == "claims":
            result = self._claims_search(
                applicant_id=applicant_id,
                query=query,
                top_k=limit,
            )

        elif resolved_intent == "policy":
            result = self._policy_search(
                applicant_id=applicant_id,
                query=query,
                top_k=limit,
            )

        else:
            result = self._broad_search(
                applicant_id=applicant_id,
                query=query,
                profile=profile,
                top_k=limit,
            )

        result["classification"] = classification
        result["intent"] = resolved_intent
        result["intent_confidence"] = classification.get(
            "confidence",
            0.0,
        )

        return result

    def _medical_search(
        self,
        applicant_id: str,
        query: str,
        top_k: int,
    ) -> dict[str, Any]:
        applicant_evidence = (
            medgraph_rag.search_applicant_evidence(
                applicant_id=applicant_id,
                query=query,
                top_k=top_k,
            )
        )

        medical_knowledge = (
            medgraph_rag.search_medical_knowledge(
                query=query,
                top_k=top_k,
            )
        )

        return self._build_response(
            query=query,
            intent="medical",
            sources={
                "applicant_medical_evidence": (
                    applicant_evidence
                ),
                "medical_knowledge": (
                    medical_knowledge
                ),
            },
        )

    def _regulatory_search(
        self,
        query: str,
        top_k: int,
    ) -> dict[str, Any]:
        regulatory = (
            hybrid_rag.search_regulatory(
                query=query,
                jurisdiction="India",
                top_k=top_k,
            )
        )

        return self._build_response(
            query=query,
            intent="regulatory",
            sources={
                "regulatory": regulatory,
            },
        )

    def _underwriting_search(
        self,
        query: str,
        profile: dict[str, Any],
        top_k: int,
    ) -> dict[str, Any]:
        product = profile.get(
            "requested_product"
        )

        underwriting = (
            hybrid_rag.search_underwriting(
                query=query,
                product=product,
                top_k=top_k,
            )
        )

        return self._build_response(
            query=query,
            intent="underwriting",
            sources={
                "underwriting": underwriting,
            },
        )

    def _claims_search(
        self,
        applicant_id: str,
        query: str,
        top_k: int,
    ) -> dict[str, Any]:
        claims = (
            retriever.retrieve_claims_evidence(
                applicant_id=applicant_id,
                query=query,
                top_k=top_k,
            )
        )

        return self._build_response(
            query=query,
            intent="claims",
            sources={
                "claims": claims,
            },
        )

    def _policy_search(
        self,
        applicant_id: str,
        query: str,
        top_k: int,
    ) -> dict[str, Any]:
        policy = (
            retriever.retrieve_policy_evidence(
                applicant_id=applicant_id,
                query=query,
                top_k=top_k,
            )
        )

        return self._build_response(
            query=query,
            intent="policy",
            sources={
                "policy": policy,
            },
        )

    def _broad_search(
        self,
        applicant_id: str,
        query: str,
        profile: dict[str, Any],
        top_k: int,
    ) -> dict[str, Any]:
        applicant_results = retriever.retrieve_all(
            applicant_id=applicant_id,
            query=query,
            top_k=top_k,
        )

        medical_results = (
            medgraph_rag.search_medical_knowledge(
                query=query,
                top_k=top_k,
            )
        )

        regulatory_results = (
            hybrid_rag.search_regulatory(
                query=query,
                jurisdiction="India",
                top_k=top_k,
            )
        )

        underwriting_results = (
            hybrid_rag.search_underwriting(
                query=query,
                product=profile.get(
                    "requested_product"
                ),
                top_k=top_k,
            )
        )

        return self._build_response(
            query=query,
            intent="broad",
            sources={
                "applicant_evidence": applicant_results,
                "medical_knowledge": medical_results,
                "regulatory": regulatory_results,
                "underwriting": underwriting_results,
            },
        )

    def _build_response(
        self,
        query: str,
        intent: str,
        sources: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "query": query,
            "intent": intent,
            "sources_used": list(
                sources.keys()
            ),
            "results": sources,
            "total_results": self._count_results(
                sources
            ),
        }

    def _count_results(
        self,
        value: Any,
    ) -> int:
        if isinstance(value, list):
            return len(value)

        if isinstance(value, dict):
            if "result_count" in value:
                try:
                    return int(
                        value.get(
                            "result_count",
                            0,
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    return 0

            return sum(
                self._count_results(item)
                for item in value.values()
            )

        return 0


agentic_rag = AgenticRAG()