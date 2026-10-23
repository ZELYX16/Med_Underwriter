from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from app.cache.pattern_cache import pattern_cache
from app.config import settings
from app.rag.agentic_rag import agentic_rag
from app.rag.budget import retrieval_budget
from app.rag.hybrid_rag import hybrid_rag
from app.rag.medgraph_rag import medgraph_rag
from app.rag.retriever import retriever


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_KNOWLEDGE_CACHE: dict[tuple, tuple[float, list[dict[str, Any]]]] = {}
_KNOWLEDGE_TTL_SEC = 3600.0


def _knowledge_cache(key: tuple, fetch) -> list[dict[str, Any]]:
    """Cache non-applicant knowledge lookups; failures return [] uncached."""
    now = time.monotonic()
    hit = _KNOWLEDGE_CACHE.get(key)
    pattern_key = "|".join(str(part) for part in key)
    if hit and now - hit[0] < _KNOWLEDGE_TTL_SEC:
        pattern_cache.record_hit("knowledge", pattern_key)
        return hit[1]

    stored = pattern_cache.get("knowledge", pattern_key)
    if isinstance(stored, list) and stored:
        _KNOWLEDGE_CACHE[key] = (now, stored)
        return stored

    try:
        results = fetch()
    except Exception:
        return []
    if isinstance(results, list) and results:
        if len(_KNOWLEDGE_CACHE) > 128:
            _KNOWLEDGE_CACHE.clear()
        _KNOWLEDGE_CACHE[key] = (now, results)
        pattern_cache.put("knowledge", pattern_key, results)
    return results if isinstance(results, list) else []


class SubmissionIntelligenceAgent:
    """
    Agent 1 — Submission Intelligence.

    Builds the complete risk context required by downstream agents.

    Five core delegations:
        1. EHR / medical evidence
        2. Claims history
        3. Regulatory requirements
        4. Industry / actuarial / pricing guidance
        5. Coverage-gap analysis

    The collected information is converted into a structured
    working-memory scratchpad for Agent 2.
    """

    def _applicant_id(
        self,
        applicant_profile: dict[str, Any],
    ) -> str:
        return str(
            applicant_profile.get("applicant_id")
            or applicant_profile.get("id")
            or ""
        )

    @staticmethod
    def _join(values: Any, limit: int = 6) -> str:
        """Readable 'a, b, c' text instead of a raw Python list repr."""
        if not isinstance(values, (list, tuple)):
            values = [values] if values else []
        parts = []
        for v in values[:limit]:
            if isinstance(v, dict):
                v = v.get("name") or v.get("condition") or v.get("title") or ""
            v = str(v).strip()
            if v:
                parts.append(v)
        return ", ".join(parts)

    def _build_queries(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
    ) -> dict[str, str]:
        conditions = self._join(
            applicant_profile.get("medical_conditions", [])
        )
        medications = self._join(
            applicant_profile.get("medications", [])
        )
        product = str(submission.get("product", "") or "")

        medical = " ".join(
            part
            for part in (
                f"diagnosis and treatment of {conditions}"
                if conditions
                else "medical history diagnosis treatment",
                f"medications {medications}" if medications else "",
            )
            if part
        )

        return {
            "medical": medical,
            "claims": (
                f"claims hospitalization {conditions}"
                if conditions
                else "claims hospitalization admission history"
            ),
            "policy": (
                f"existing {product} policy coverage sum insured "
                "exclusions status"
            ).replace("  ", " "),
            "underwriting": (
                f"{product} underwriting submission sum insured "
                "medical declarations"
            ).strip(),
            "regulatory": (
                "IRDAI health insurance underwriting disclosure "
                "requirements"
                + (f" for {conditions}" if conditions else "")
            ),
            "actuarial": (
                f"{product} risk loading premium guidance"
                + (f" for {conditions}" if conditions else "")
            ).strip(),
        }

    def _retrieve_medical_evidence(
        self,
        applicant_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        if not applicant_id:
            return []

        try:
            return retriever.retrieve_medical_evidence(
                applicant_id=applicant_id,
                query=query,
            )
        except Exception:
            return []

    def _retrieve_claims_evidence(
        self,
        applicant_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        if not applicant_id:
            return []

        try:
            return retriever.retrieve_claims_evidence(
                applicant_id=applicant_id,
                query=query,
            )
        except Exception:
            return []

    def _retrieve_policy_evidence(
        self,
        applicant_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        if not applicant_id:
            return []

        try:
            return retriever.retrieve_policy_evidence(
                applicant_id=applicant_id,
                query=query,
            )
        except Exception:
            return []

    def _retrieve_underwriting_submission(
        self,
        applicant_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        if not applicant_id:
            return []

        try:
            return retriever.retrieve_underwriting_submission(
                applicant_id=applicant_id,
                query=query,
            )
        except Exception:
            return []

    def _build_reviewer_evidence(
        self,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert RAG chunks into document-level reviewer evidence."""
        if not isinstance(results, list) or not results:
            return []

        try:
            grouped = retriever.group_by_document(results)
        except Exception:
            return []

        return grouped if isinstance(grouped, list) else []

    @staticmethod
    def _reviewer_evidence_summary(
        medical_review_evidence: list[dict[str, Any]],
        claims_review_evidence: list[dict[str, Any]],
        policy_review_evidence: list[dict[str, Any]],
        underwriting_review_evidence: list[dict[str, Any]],
    ) -> dict[str, int]:
        return {
            "medical_review_documents": len(medical_review_evidence),
            "claims_review_documents": len(claims_review_evidence),
            "policy_review_documents": len(policy_review_evidence),
            "underwriting_review_documents": len(
                underwriting_review_evidence
            ),
        }

    def _retrieve_regulatory(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        # Regulatory text is the same for every applicant asking the same
        # thing, so serve it from a short-lived cache.
        return _knowledge_cache(
            ("regulatory", query),
            lambda: hybrid_rag.search_regulatory(
                query=query,
                jurisdiction="India",
                top_k=settings.retrieval_per_source_k,
            ),
        )

    def _retrieve_actuarial_guidance(
        self,
        query: str,
        product: str | None,
    ) -> list[dict[str, Any]]:
        """
        Retrieves underwriting, pricing and actuarial guidance.

        The current POC stores this guidance in the underwriting
        knowledge collection, so no separate actuarial collection
        is required.
        """
        return _knowledge_cache(
            ("actuarial", query, product),
            lambda: hybrid_rag.search_underwriting(
                query=query,
                product=product,
                top_k=settings.retrieval_per_source_k,
            ),
        )

    async def _retrieve_coverage_gaps(
        self,
        applicant_id: str,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        prefetched: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        if not applicant_id:
            return {
                "coverage_gaps": [],
                "evidence_status": {},
            }

        try:
            result = await agentic_rag.retrieve(
                query=(
                    "Identify coverage gaps, missing evidence, "
                    "policy limitations, exclusions, and "
                    "underwriting information gaps for this applicant."
                ),
                context={
                    "applicant_id": applicant_id,
                    "applicant_profile": applicant_profile,
                    "submission": submission,
                    "prefetched_evidence": prefetched,
                },
            )
        except Exception:
            return {
                "coverage_gaps": [],
                "evidence_status": {},
            }

        if not isinstance(result, dict):
            return {
                "coverage_gaps": [],
                "evidence_status": {},
            }

        gaps = result.get(
            "coverage_gaps",
            [],
        )

        evidence_status = result.get(
            "evidence_status",
            {},
        )

        return {
            "coverage_gaps": (
                gaps
                if isinstance(gaps, list)
                else []
            ),
            "evidence_status": (
                evidence_status
                if isinstance(evidence_status, dict)
                else {}
            ),
        }

    async def _retrieve_medical_knowledge(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        try:
            results = medgraph_rag.search_medical_knowledge(
                query=query,
                top_k=5,
            )
        except TypeError:
            try:
                results = medgraph_rag.search_medical_knowledge(
                    query=query,
                )
            except Exception:
                return []
        except Exception:
            return []

        return results if isinstance(results, list) else []

    @staticmethod
    def _unique_documents(
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []

        for item in results:
            if not isinstance(item, dict):
                continue

            metadata = item.get(
                "metadata",
                {},
            )

            if not isinstance(metadata, dict):
                metadata = {}

            document_id = (
                item.get("document_id")
                or metadata.get("document_id")
                or item.get("file_name")
                or metadata.get("file_name")
                or item.get("content", "")[:120]
            )

            if not document_id:
                document_id = str(len(unique))

            if document_id in seen:
                continue

            seen.add(document_id)
            unique.append(item)

        return unique

    @classmethod
    def _count_documents(
        cls,
        results: Any,
    ) -> int:
        if not isinstance(results, list):
            return 0

        return len(
            cls._unique_documents(results)
        )

    @staticmethod
    def _split_gap_types(
        gaps: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Separate confirmed coverage findings from evidence limitations."""
        confirmed: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []

        evidence_types = {
            "evidence_unavailable",
            "missing_policy_evidence",
            "missing_underwriting_evidence",
            "claims_evidence_incomplete",
            "medical_evidence_incomplete",
        }

        for item in gaps:
            if not isinstance(item, dict):
                continue

            item_type = str(item.get("type", "")).strip().lower()
            status = str(item.get("status", "")).strip().lower()

            if item_type in evidence_types or status == "needs_more_information":
                evidence.append(item)
            else:
                confirmed.append(item)

        return confirmed, evidence

    @staticmethod
    def _risk_flags(
        applicant_profile: dict[str, Any],
        medical_evidence: list[dict[str, Any]],
        claims_evidence: list[dict[str, Any]],
        coverage_gaps: list[dict[str, Any]],
    ) -> list[str]:
        flags: list[str] = []

        conditions = applicant_profile.get(
            "medical_conditions",
            [],
        )

        if conditions:
            flags.append("medical_conditions_present")

        if claims_evidence:
            flags.append("claims_history_present")

        if medical_evidence:
            flags.append("medical_evidence_present")

        if coverage_gaps:
            flags.append("coverage_or_information_gaps_present")

        return flags

    def _build_scratchpad(
        self,
        applicant_id: str,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        medical_evidence: list[dict[str, Any]],
        claims_evidence: list[dict[str, Any]],
        policy_evidence: list[dict[str, Any]],
        underwriting_submission: list[dict[str, Any]],
        regulatory_evidence: list[dict[str, Any]],
        actuarial_guidance: list[dict[str, Any]],
        medical_knowledge: list[dict[str, Any]],
        coverage_gaps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "case_id": submission.get("case_id"),
            "applicant_id": applicant_id,
            "applicant_profile": {
                "demographics": {
                    key: applicant_profile.get(key)
                    for key in (
                        "age",
                        "gender",
                        "occupation",
                    )
                    if key in applicant_profile
                },
                "medical_conditions": applicant_profile.get(
                    "medical_conditions",
                    [],
                ),
                "medications": applicant_profile.get(
                    "medications",
                    [],
                ),
                "risk_flags": self._risk_flags(
                    applicant_profile=applicant_profile,
                    medical_evidence=medical_evidence,
                    claims_evidence=claims_evidence,
                    coverage_gaps=coverage_gaps,
                ),
            },
            "submission": {
                "product": submission.get("product"),
                "sum_insured": submission.get("sum_insured"),
                "term_years": submission.get(
                    "term_years",
                    submission.get("term"),
                ),
                "jurisdiction": submission.get(
                    "jurisdiction"
                ),
                "insurer": submission.get(
                    "insurer"
                ),
                "requested_start_date": submission.get(
                    "requested_start_date"
                ),
            },
            "enrichment_results": {
                "medical_evidence": medical_evidence,
                "claims_history": claims_evidence,
                "policy_evidence": policy_evidence,
                "underwriting_submission": underwriting_submission,
                "regulatory_evidence": regulatory_evidence,
                "actuarial_guidance": actuarial_guidance,
                "medical_knowledge": medical_knowledge,
                "coverage_gaps": coverage_gaps,
            },
            "agent1_completed": True,
            "agent2_risk_score": None,
            "agent2_recommendation": None,
            "agent2_confidence": None,
            "agent3_reflection_required": False,
            "reflection_personas": [],
            "final_decision": None,
            "audit_trail": [],
        }

    def _build_evidence_summary(
        self,
        medical_evidence: list[dict[str, Any]],
        claims_evidence: list[dict[str, Any]],
        policy_evidence: list[dict[str, Any]],
        underwriting_submission: list[dict[str, Any]],
        regulatory_evidence: list[dict[str, Any]],
        actuarial_guidance: list[dict[str, Any]],
        medical_knowledge: list[dict[str, Any]],
        coverage_gaps: list[dict[str, Any]],
    ) -> dict[str, int]:
        return {
            "medical_documents": self._count_documents(
                medical_evidence
            ),
            "claims_documents": self._count_documents(
                claims_evidence
            ),
            "policy_documents": self._count_documents(
                policy_evidence
            ),
            "underwriting_documents": self._count_documents(
                underwriting_submission
            ),
            "underwriting_submission_documents": self._count_documents(
                underwriting_submission
            ),
            "underwriting_knowledge_documents": self._count_documents(
                actuarial_guidance
            ),
            "regulatory_documents": self._count_documents(
                regulatory_evidence
            ),
            "actuarial_documents": self._count_documents(
                actuarial_guidance
            ),
            "medical_knowledge_documents": self._count_documents(
                medical_knowledge
            ),
            "coverage_gaps": len(coverage_gaps),
        }
    async def _execute_delegations(
        self,
        applicant_id: str,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        queries: dict[str, str],
    ) -> dict[str, Any]:
        """
        Executes Agent 1's five delegation areas.

        Synchronous retrieval operations are moved to worker threads
        so the independent retrieval tasks can execute concurrently.
        """

        medical_task = asyncio.to_thread(
            self._retrieve_medical_evidence,
            applicant_id,
            queries["medical"],
        )

        claims_task = asyncio.to_thread(
            self._retrieve_claims_evidence,
            applicant_id,
            queries["claims"],
        )

        regulatory_task = asyncio.to_thread(
            self._retrieve_regulatory,
            queries["regulatory"],
        )

        actuarial_task = asyncio.to_thread(
            self._retrieve_actuarial_guidance,
            queries["actuarial"],
            submission.get("product"),
        )

        # Nothing to look up in the medical knowledge graph when the
        # applicant declares no conditions.
        if applicant_profile.get("medical_conditions"):
            medical_knowledge_task = self._retrieve_medical_knowledge(
                queries["medical"]
            )
        else:
            async def _no_knowledge() -> list[dict[str, Any]]:
                return []

            medical_knowledge_task = _no_knowledge()

        policy_task = asyncio.to_thread(
            self._retrieve_policy_evidence,
            applicant_id,
            queries["policy"],
        )

        underwriting_task = asyncio.to_thread(
            self._retrieve_underwriting_submission,
            applicant_id,
            queries["underwriting"],
        )

        (
            medical_evidence,
            claims_evidence,
            regulatory_evidence,
            actuarial_guidance,
            medical_knowledge,
            policy_evidence,
            underwriting_submission,
        ) = await asyncio.gather(
            medical_task,
            claims_task,
            regulatory_task,
            actuarial_task,
            medical_knowledge_task,
            policy_task,
            underwriting_task,
        )

        # Coverage analysis reuses the applicant evidence fetched above
        # (it used to re-run those four queries).
        coverage_gaps = await self._retrieve_coverage_gaps(
            applicant_id=applicant_id,
            applicant_profile=applicant_profile,
            submission=submission,
            prefetched={
                "medical": medical_evidence,
                "claims": claims_evidence,
                "policy": policy_evidence,
                "underwriting": underwriting_submission,
            },
        )

        return {
            "medical_evidence": medical_evidence,
            "claims_evidence": claims_evidence,
            "regulatory_evidence": regulatory_evidence,
            "actuarial_guidance": actuarial_guidance,
            "coverage_gaps": coverage_gaps,
            "medical_knowledge": medical_knowledge,
            "policy_evidence": policy_evidence,
            "underwriting_submission": underwriting_submission,
        }

    async def run(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        applicant_id = self._applicant_id(
            applicant_profile
        )

        queries = self._build_queries(
            applicant_profile=applicant_profile,
            submission=submission,
        )

        workflow_trace = [
            {
                "step": "reason",
                "status": "completed",
                "description": (
                    "Identified independent medical, claims, "
                    "regulatory, actuarial, and coverage-gap "
                    "delegations."
                ),
            }
        ]

        # One shared budget bounds every vector query this case makes,
        # including CRAG / agentic sub-searches.
        with retrieval_budget() as budget:
            enrichment = await self._execute_delegations(
                applicant_id=applicant_id,
                applicant_profile=applicant_profile,
                submission=submission,
                queries=queries,
            )
        retrieval_stats = budget.summary()

        workflow_trace.append(
            {
                "step": "act",
                "status": "completed",
                "description": (
                    "Executed Agent 1 evidence delegations "
                    "concurrently."
                ),
            }
        )

        medical_evidence = enrichment[
            "medical_evidence"
        ]

        claims_evidence = enrichment[
            "claims_evidence"
        ]

        policy_evidence = enrichment[
            "policy_evidence"
        ]

        underwriting_submission = enrichment[
            "underwriting_submission"
        ]

        # Keep RAG chunks for AI reasoning, but create a separate
        # document-level representation for the reviewer UI.
        medical_review_evidence = self._build_reviewer_evidence(
            medical_evidence
        )
        claims_review_evidence = self._build_reviewer_evidence(
            claims_evidence
        )
        policy_review_evidence = self._build_reviewer_evidence(
            policy_evidence
        )
        underwriting_review_evidence = self._build_reviewer_evidence(
            underwriting_submission
        )

        reviewer_evidence_summary = self._reviewer_evidence_summary(
            medical_review_evidence=medical_review_evidence,
            claims_review_evidence=claims_review_evidence,
            policy_review_evidence=policy_review_evidence,
            underwriting_review_evidence=underwriting_review_evidence,
        )

        regulatory_evidence = enrichment[
            "regulatory_evidence"
        ]

        actuarial_guidance = enrichment[
            "actuarial_guidance"
        ]

        medical_knowledge = enrichment[
            "medical_knowledge"
        ]

        coverage_result = enrichment[
            "coverage_gaps"
        ]

        if isinstance(coverage_result, dict):
            raw_gaps = coverage_result.get(
                "confirmed_coverage_gaps",
                coverage_result.get("coverage_gaps", []),
            )
            raw_evidence_gaps = coverage_result.get(
                "evidence_gaps",
                [],
            )
            raw_gaps = raw_gaps if isinstance(raw_gaps, list) else []
            raw_evidence_gaps = (
                raw_evidence_gaps
                if isinstance(raw_evidence_gaps, list)
                else []
            )
            split_confirmed, split_evidence = self._split_gap_types(raw_gaps)
            coverage_gaps = split_confirmed
            evidence_gaps = raw_evidence_gaps + split_evidence
            coverage_evidence_status = coverage_result.get(
                "evidence_status",
                {},
            )
            if not isinstance(coverage_evidence_status, dict):
                coverage_evidence_status = {}
        else:
            coverage_gaps = []
            evidence_gaps = []
            coverage_evidence_status = {}

        evidence_summary = self._build_evidence_summary(
            medical_evidence=medical_evidence,
            claims_evidence=claims_evidence,
            policy_evidence=policy_evidence,
            underwriting_submission=underwriting_submission,
            regulatory_evidence=regulatory_evidence,
            actuarial_guidance=actuarial_guidance,
            medical_knowledge=medical_knowledge,
            coverage_gaps=coverage_gaps,
        )

        scratchpad = self._build_scratchpad(
            applicant_id=applicant_id,
            applicant_profile=applicant_profile,
            submission=submission,
            medical_evidence=medical_evidence,
            claims_evidence=claims_evidence,
            policy_evidence=policy_evidence,
            underwriting_submission=underwriting_submission,
            regulatory_evidence=regulatory_evidence,
            actuarial_guidance=actuarial_guidance,
            medical_knowledge=medical_knowledge,
            coverage_gaps=coverage_gaps,
        )

        workflow_trace.append(
            {
                "step": "observe",
                "status": "completed",
                "description": (
                    "Aggregated retrieved evidence into the "
                    "Agent 1 working-memory scratchpad."
                ),
                "evidence_summary": evidence_summary,
                "reviewer_evidence_summary": reviewer_evidence_summary,
            }
        )

        metrics = {
            "latency_sec": round(time.perf_counter() - started, 4),
            "llm_latency_sec": 0.0,
            # Agent 1 makes no LLM call: retrieval is not token usage.
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "token_source": "none",
            "retrieval": retrieval_stats,
            "llm_used": False,
        }

        return {
            "agent1_enrichment": {
                "applicant_id": applicant_id,
                "medical_evidence": medical_evidence,
                "claims_evidence": claims_evidence,
                "policy_evidence": policy_evidence,
                "underwriting_submission": underwriting_submission,
                "medical_review_evidence": medical_review_evidence,
                "claims_review_evidence": claims_review_evidence,
                "policy_review_evidence": policy_review_evidence,
                "underwriting_review_evidence": underwriting_review_evidence,
                "reviewer_evidence_summary": reviewer_evidence_summary,
                "regulatory_evidence": regulatory_evidence,
                "actuarial_guidance": actuarial_guidance,
                "underwriting_knowledge_evidence": actuarial_guidance,
                "medical_knowledge": medical_knowledge,
                "coverage_gaps": coverage_gaps,
                "confirmed_coverage_gaps": coverage_gaps,
                "evidence_gaps": evidence_gaps,
                "coverage_evidence_status": coverage_evidence_status,
                "evidence_summary": evidence_summary,
                "scratchpad": scratchpad,
                "workflow_trace": workflow_trace,
                "retrieved_at": utc_now(),
            },
            "medical_evidence": medical_evidence,
            "claims_evidence": claims_evidence,
            "policy_evidence": policy_evidence,
            "underwriting_evidence": actuarial_guidance,
            "medical_review_evidence": medical_review_evidence,
            "claims_review_evidence": claims_review_evidence,
            "policy_review_evidence": policy_review_evidence,
            "underwriting_review_evidence": underwriting_review_evidence,
            "reviewer_evidence_summary": reviewer_evidence_summary,
            "underwriting_submission": underwriting_submission,
            "regulatory_evidence": regulatory_evidence,
            "actuarial_guidance": actuarial_guidance,
            "medical_knowledge": medical_knowledge,
            "coverage_gaps": coverage_gaps,
            "confirmed_coverage_gaps": coverage_gaps,
            "evidence_gaps": evidence_gaps,
            "coverage_evidence_status": coverage_evidence_status,
            "evidence_summary": evidence_summary,
            "scratchpad": scratchpad,
            "workflow_trace": workflow_trace,
            "metrics": metrics,
            "agent1_metrics": metrics,
            "agent1_completed": True,
            "retrieved_at": utc_now(),
        }


submission_agent = SubmissionIntelligenceAgent()