from __future__ import annotations

from typing import Any

from app.rag.hybrid_rag import hybrid_rag
from app.rag.medgraph_rag import medgraph_rag
from app.rag.query_classifier import query_classifier
from app.rag.retriever import retriever


class AgenticRAG:
    """
    Agentic retrieval layer.

    Routes queries between applicant-specific evidence
    and general knowledge sources.

    Applicant evidence:
        - medical
        - claims
        - policy
        - underwriting submission

    General knowledge:
        - medical knowledge
        - regulatory guidance
        - underwriting guidance

    Coverage analysis combines applicant evidence but
    does not assume that missing retrieval is a real
    coverage gap.
    """

    def __init__(self) -> None:
        self.default_top_k = 5

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        context = context or {}

        limit = max(
            1,
            min(
                top_k or self.default_top_k,
                20,
            ),
        )

        applicant_id = self._get_applicant_id(
            context
        )

        product = self._get_product(
            context
        )

        classification = self._classify(
            query=query,
            context=context,
        )

        intent = classification.get(
            "intent",
            "broad",
        )

        intent_confidence = float(
            classification.get(
                "confidence",
                0.0,
            )
            or 0.0
        )

        results: list[dict[str, Any]] = []
        sources_used: list[str] = []
        coverage_gaps: list[dict[str, Any]] = []
        evidence_status: dict[str, str] = {}

        if intent == "coverage":
            coverage_evidence, evidence_status = (
                self._search_coverage_evidence(
                    applicant_id=applicant_id,
                )
            )

            for (
                source_name,
                source_results,
            ) in coverage_evidence.items():
                if source_results:
                    results.extend(
                        source_results
                    )
                    sources_used.append(
                        source_name
                    )

            coverage_gaps = (
                self._build_coverage_gaps(
                    evidence=coverage_evidence,
                    evidence_status=evidence_status,
                    context=context,
                )
            )

        elif intent in {
            "medical",
            "claims",
            "policy",
            "underwriting",
            "broad",
        }:
            applicant_results = (
                self._search_applicant(
                    query=query,
                    applicant_id=applicant_id,
                    intent=intent,
                    top_k=limit,
                )
            )

            if applicant_results:
                results.extend(
                    applicant_results
                )
                sources_used.append(
                    "applicant_documents"
                )

        if intent == "medical":
            medical_results = self._search_medical_knowledge(
                query=query,
                top_k=limit,
            )

            if medical_results:
                results.extend(
                    medical_results
                )
                sources_used.append(
                    "medical_knowledge"
                )

        elif intent == "regulatory":
            regulatory_results = (
                self._search_regulatory(
                    query=query,
                    top_k=limit,
                )
            )

            if regulatory_results:
                results.extend(
                    regulatory_results
                )
                sources_used.append(
                    "regulatory"
                )

        elif intent == "underwriting":
            underwriting_results = (
                self._search_underwriting(
                    query=query,
                    product=product,
                    top_k=limit,
                )
            )

            if underwriting_results:
                results.extend(
                    underwriting_results
                )
                sources_used.append(
                    "underwriting"
                )

        elif intent == "broad":
            knowledge_results = (
                self._search_broad_knowledge(
                    query=query,
                    product=product,
                    top_k=limit,
                )
            )

            for (
                source_name,
                source_results,
            ) in knowledge_results.items():
                if source_results:
                    results.extend(
                        source_results
                    )
                    sources_used.append(
                        source_name
                    )

        results = self._deduplicate(
            results
        )

        return {
            "query": query,
            "intent": intent,
            "classification": classification,
            "intent_confidence": intent_confidence,
            "sources_used": list(
                dict.fromkeys(
                    sources_used
                )
            ),
            "results": results[:limit],
            "total_results": len(
                results[:limit]
            ),
            "coverage_gaps": coverage_gaps,
            "evidence_status": evidence_status,
        }

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(
        query: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            classification = (
                query_classifier.classify(
                    query=query,
                    context=context,
                )
            )

            if isinstance(
                classification,
                dict,
            ):
                return classification

        except Exception:
            pass

        return {
            "intent": "broad",
            "confidence": 0.0,
            "fallback": True,
        }

    # ------------------------------------------------------------------
    # Applicant retrieval
    # ------------------------------------------------------------------

    def _search_applicant(
        self,
        query: str,
        applicant_id: str,
        intent: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not applicant_id:
            return []

        try:
            if intent == "medical":
                return retriever.retrieve_medical_evidence(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )

            if intent == "claims":
                return retriever.retrieve_claims_evidence(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )

            if intent == "policy":
                return retriever.retrieve_policy_evidence(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )

            if intent == "underwriting":
                return retriever.retrieve_underwriting_submission(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )

            if intent == "broad":
                return retriever.search(
                    applicant_id=applicant_id,
                    query=query,
                    top_k=top_k,
                )

        except Exception:
            return []

        return []

    # ------------------------------------------------------------------
    # Coverage evidence
    # ------------------------------------------------------------------

    def _search_coverage_evidence(
        self,
        applicant_id: str,
    ) -> tuple[
        dict[str, list[dict[str, Any]]],
        dict[str, str],
    ]:
        sources = {
            "policy": (
                retriever.retrieve_policy_evidence,
                (
                    "existing policy coverage sum insured "
                    "deductible exclusions limitations"
                ),
            ),
            "medical": (
                retriever.retrieve_medical_evidence,
                (
                    "medical conditions diagnosis treatment "
                    "medications relevant medical history"
                ),
            ),
            "claims": (
                retriever.retrieve_claims_evidence,
                (
                    "insurance claims hospitalization "
                    "admission treatment utilization history"
                ),
            ),
            "underwriting": (
                retriever.retrieve_underwriting_submission,
                (
                    "underwriting submission product "
                    "sum insured declarations disclosures"
                ),
            ),
        }

        evidence: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        evidence_status: dict[
            str,
            str,
        ] = {}

        if not applicant_id:
            for source_name in sources:
                evidence[source_name] = []
                evidence_status[source_name] = (
                    "missing_applicant_id"
                )

            return (
                evidence,
                evidence_status,
            )

        for (
            source_name,
            (
                method,
                source_query,
            ),
        ) in sources.items():
            try:
                source_results = method(
                    applicant_id=applicant_id,
                    query=source_query,
                )

                if not isinstance(
                    source_results,
                    list,
                ):
                    source_results = []

                evidence[source_name] = (
                    source_results
                )

                if source_results:
                    evidence_status[source_name] = (
                        "evidence_found"
                    )
                else:
                    evidence_status[source_name] = (
                        "no_evidence_retrieved"
                    )

            except Exception as exc:
                evidence[source_name] = []
                evidence_status[source_name] = (
                    "retrieval_error"
                )

        return (
            evidence,
            evidence_status,
        )

    def _build_coverage_gaps(
        self,
        evidence: dict[str, list[dict[str, Any]]],
        evidence_status: dict[str, str],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []

        submission = context.get(
            "submission",
            {},
        )

        if not isinstance(
            submission,
            dict,
        ):
            submission = {}

        policy_status = evidence_status.get(
            "policy"
        )

        underwriting_status = evidence_status.get(
            "underwriting"
        )

        claims_status = evidence_status.get(
            "claims"
        )

        medical_status = evidence_status.get(
            "medical"
        )

        # Missing retrieval evidence is not automatically
        # treated as an actual coverage gap.
        if policy_status == "retrieval_error":
            gaps.append(
                {
                    "type": "evidence_unavailable",
                    "source": "policy",
                    "description": (
                        "Policy evidence could not be "
                        "retrieved for coverage assessment."
                    ),
                    "severity": "medium",
                    "status": "needs_more_information",
                }
            )

        if underwriting_status == "retrieval_error":
            gaps.append(
                {
                    "type": "evidence_unavailable",
                    "source": "underwriting",
                    "description": (
                        "Underwriting submission evidence "
                        "could not be retrieved."
                    ),
                    "severity": "medium",
                    "status": "needs_more_information",
                }
            )

        if claims_status == "retrieval_error":
            gaps.append(
                {
                    "type": "evidence_unavailable",
                    "source": "claims",
                    "description": (
                        "Claims evidence could not be "
                        "retrieved for assessment."
                    ),
                    "severity": "low",
                    "status": "needs_more_information",
                }
            )

        if medical_status == "retrieval_error":
            gaps.append(
                {
                    "type": "evidence_unavailable",
                    "source": "medical",
                    "description": (
                        "Medical evidence could not be "
                        "retrieved for assessment."
                    ),
                    "severity": "medium",
                    "status": "needs_more_information",
                }
            )

        # A missing policy is only considered a potential
        # information gap when the submission indicates
        # that existing coverage is relevant.
        existing_policy = (
            submission.get(
                "existing_policy"
            )
            or submission.get(
                "existing_policy_number"
            )
            or submission.get(
                "has_existing_policy"
            )
        )

        if (
            not evidence.get("policy")
            and existing_policy
            and policy_status
            == "no_evidence_retrieved"
        ):
            gaps.append(
                {
                    "type": "missing_policy_evidence",
                    "description": (
                        "The submission indicates existing "
                        "coverage, but policy evidence was "
                        "not retrieved."
                    ),
                    "severity": "medium",
                    "status": "needs_more_information",
                }
            )

        # A missing underwriting submission is an
        # information gap only when the current workflow
        # expects underwriting submission data.
        submission_required = (
            bool(submission)
            or context.get(
                "require_submission",
                False,
            )
        )

        if (
            submission_required
            and not evidence.get(
                "underwriting"
            )
            and underwriting_status
            == "no_evidence_retrieved"
        ):
            gaps.append(
                {
                    "type": "missing_underwriting_evidence",
                    "description": (
                        "Required underwriting submission "
                        "evidence was not retrieved."
                    ),
                    "severity": "medium",
                    "status": "needs_more_information",
                }
            )

        # Medical and claims are kept as evidence-quality
        # observations, not automatically labeled as
        # coverage gaps.
        if (
            medical_status
            == "evidence_found"
            and claims_status
            == "no_evidence_retrieved"
        ):
            gaps.append(
                {
                    "type": "claims_evidence_incomplete",
                    "description": (
                        "Medical evidence was retrieved, "
                        "but no claims evidence was retrieved. "
                        "This does not establish absence of claims."
                    ),
                    "severity": "low",
                    "status": "needs_more_information",
                }
            )

        if (
            claims_status
            == "evidence_found"
            and medical_status
            == "no_evidence_retrieved"
        ):
            gaps.append(
                {
                    "type": "medical_evidence_incomplete",
                    "description": (
                        "Claims evidence was retrieved, "
                        "but no medical evidence was retrieved. "
                        "Additional medical evidence may be needed."
                    ),
                    "severity": "medium",
                    "status": "needs_more_information",
                }
            )

        return gaps

    # ------------------------------------------------------------------
    # General knowledge retrieval
    # ------------------------------------------------------------------

    @staticmethod
    def _search_medical_knowledge(
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            return medgraph_rag.search_medical_knowledge(
                query=query,
                top_k=top_k,
            )
        except Exception:
            return []

    @staticmethod
    def _search_regulatory(
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            return hybrid_rag.search_regulatory(
                query=query,
                jurisdiction="India",
                top_k=top_k,
            )
        except Exception:
            return []

    @staticmethod
    def _search_underwriting(
        query: str,
        product: str | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            return hybrid_rag.search_underwriting(
                query=query,
                product=product,
                top_k=top_k,
            )
        except Exception:
            return []

    def _search_broad_knowledge(
        self,
        query: str,
        product: str | None,
        top_k: int,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "medical_knowledge": (
                self._search_medical_knowledge(
                    query=query,
                    top_k=top_k,
                )
            ),
            "regulatory": (
                self._search_regulatory(
                    query=query,
                    top_k=top_k,
                )
            ),
            "underwriting": (
                self._search_underwriting(
                    query=query,
                    product=product,
                    top_k=top_k,
                )
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_applicant_id(
        context: dict[str, Any],
    ) -> str:
        applicant_id = (
            context.get(
                "applicant_id"
            )
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
    def _deduplicate(
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()

        for result in results:
            if not isinstance(
                result,
                dict,
            ):
                continue

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
                    "",
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
            unique.append(
                result
            )

        return unique


agentic_rag = AgenticRAG()