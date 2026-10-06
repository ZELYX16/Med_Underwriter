from datetime import datetime, timezone
from typing import Any

from app.rag.agentic_rag import agentic_rag
from app.rag.hybrid_rag import hybrid_rag
from app.rag.medgraph_rag import medgraph_rag
from app.rag.retriever import retriever


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SubmissionIntelligenceAgent:
    """
    Agent 1:
    Collects and organizes evidence required for underwriting.

    It does not make the final underwriting decision.
    """

    def _applicant_id(self, applicant_profile: dict[str, Any]) -> str:
        return (
            applicant_profile.get("applicant_id")
            or applicant_profile.get("id")
            or ""
        )

    def _build_queries(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
    ) -> list[str]:
        applicant_id = self._applicant_id(applicant_profile)

        conditions = applicant_profile.get("medical_conditions", [])
        medications = applicant_profile.get("medications", [])

        queries = [
            f"medical underwriting evidence for applicant {applicant_id}",
            f"medical conditions {conditions}",
            f"medications {medications}",
            f"underwriting requirements for {submission.get('product', '')}",
            "health insurance underwriting regulatory requirements India IRDAI",
        ]

        return [query for query in queries if query.strip()]

    def _retrieve_applicant_evidence(
        self,
        applicant_id: str,
        query: str = "medical examination health history claims policy",
    ) -> dict[str, list[dict[str, Any]]]:
        if not applicant_id:
            return {
                "medical": [],
                "claims": [],
                "policy": [],
                "underwriting": [],
            }

        return {
            "medical": retriever.retrieve_medical_evidence(
                applicant_id=applicant_id,
                query=f"medical examination health record {query}",
            ),
            "claims": retriever.retrieve_claims_evidence(
                applicant_id=applicant_id,
                query=f"insurance claim history hospitalization {query}",
            ),
            "policy": retriever.retrieve_policy_evidence(
                applicant_id=applicant_id,
                query=f"existing policy coverage terms {query}",
            ),
            "underwriting": retriever.retrieve_underwriting_submission(
                applicant_id=applicant_id,
                query=f"underwriting submission proposal {query}",
            ),
        }

    async def run(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
    ) -> dict[str, Any]:
        applicant_id = self._applicant_id(applicant_profile)

        evidence = self._retrieve_applicant_evidence(applicant_id)

        medical_queries = self._build_queries(
            applicant_profile,
            submission,
        )

        medical_knowledge: list[dict[str, Any]] = []

        for query in medical_queries[:3]:
            try:
                results = medgraph_rag.search_medical_knowledge(
                    query=query
                )
                medical_knowledge.extend(results)
            except Exception:
                continue

        regulatory_evidence: list[dict[str, Any]] = []

        try:
            regulatory_evidence = hybrid_rag.search_regulatory(
                query=(
                    "medical insurance underwriting requirements "
                    "and applicant assessment"
                ),
                jurisdiction="India",
            )
        except Exception:
            regulatory_evidence = []

        underwriting_evidence: list[dict[str, Any]] = []

        try:
            underwriting_evidence = hybrid_rag.search_underwriting(
                query=(
                    "medical underwriting assessment "
                    "risk and evidence requirements"
                ),
                product=submission.get("product"),
            )
        except Exception:
            underwriting_evidence = []

        coverage_gaps: list[dict[str, Any]] = []

        try:
            coverage_result = await agentic_rag.retrieve(
                query=(
                    f"coverage gaps and missing evidence for "
                    f"applicant {applicant_id}"
                ),
                context={
                    "applicant_id": applicant_id,
                    "applicant_profile": applicant_profile,
                    "submission": submission,
                },
            )

            if isinstance(coverage_result, dict):
                coverage_gaps = coverage_result.get(
                    "coverage_gaps",
                    [],
                )

        except Exception:
            coverage_gaps = []

        enrichment = {
            "applicant_id": applicant_id,
            "medical_evidence": evidence["medical"],
            "claims_evidence": evidence["claims"],
            "policy_evidence": evidence["policy"],
            "underwriting_submission": evidence["underwriting"],
            "regulatory_evidence": regulatory_evidence,
            "underwriting_evidence": underwriting_evidence,
            "medical_knowledge": medical_knowledge,
            "coverage_gaps": coverage_gaps,
            "retrieved_at": utc_now(),
        }

        return {
            "agent1_enrichment": enrichment,
            "medical_evidence": evidence["medical"],
            "claims_evidence": evidence["claims"],
            "policy_evidence": evidence["policy"],
            "regulatory_evidence": regulatory_evidence,
            "underwriting_evidence": underwriting_evidence,
            "medical_knowledge": medical_knowledge,
            "coverage_gaps": coverage_gaps,
            "agent1_completed": True,
        }


submission_agent = SubmissionIntelligenceAgent()