from datetime import datetime, timezone
from typing import Any

from app.rag.agentic_rag import agentic_rag
from app.rag.crag import crag
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
        ]

        if conditions:
            cond_str = ", ".join(conditions) if isinstance(conditions, list) else str(conditions)
            queries.append(f"medical conditions {cond_str}")

        if medications:
            med_str = ", ".join(medications) if isinstance(medications, list) else str(medications)
            queries.append(f"medications {med_str}")

        product = submission.get("product", "")
        if product:
            queries.append(f"underwriting requirements for {product}")

        queries.append("health insurance underwriting regulatory requirements India IRDAI")

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

        conditions = applicant_profile.get("medical_conditions", [])
        medications = applicant_profile.get("medications", [])

        medical_knowledge: list[dict[str, Any]] = []

        if conditions or medications:
            concept_queries = []
            if conditions:
                cond_str = ", ".join(conditions) if isinstance(conditions, list) else str(conditions)
                concept_queries.append(f"medical conditions {cond_str}")
            if medications:
                med_str = ", ".join(medications) if isinstance(medications, list) else str(medications)
                concept_queries.append(f"medications {med_str}")

            for query in concept_queries:
                try:
                    results = medgraph_rag.search_medical_knowledge(
                        query=query
                    )
                    if isinstance(results, dict):
                        medical_knowledge.extend(
                            results.get("results", [])
                        )
                    elif isinstance(results, list):
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

        crag_result: dict[str, Any] = {}
        try:
            crag_result = crag.retrieve(
                applicant_id=applicant_id,
                query="medical examination health record claims policy",
                applicant_profile=applicant_profile,
            )
        except Exception:
            crag_result = {
                "crag": {
                    "status": "bypassed",
                    "attempts": 0,
                    "correction_applied": False,
                }
            }

        coverage_gaps = self._detect_coverage_gaps(
            applicant_profile=applicant_profile,
            submission=submission,
            evidence=evidence,
        )

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
            "crag": crag_result.get("crag", {}),
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

    def _detect_coverage_gaps(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        evidence: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []

        conditions = list(applicant_profile.get("medical_conditions", []))
        declared_pre_existing = list(submission.get("declared_pre_existing_conditions", []))
        all_conditions = list(set(conditions + declared_pre_existing))

        # 1. Declared conditions but no medical examination report found
        if all_conditions and not evidence.get("medical"):
            gaps.append({
                "gap_type": "missing_medical_records",
                "severity": "high",
                "description": f"Declared conditions ({all_conditions}) but no medical examination report was retrieved.",
            })

        # 2. Cardiac condition declared: check if cardiology notes or cardiac intervention reports exist
        has_cardiac = any(
            term in str(cond).lower()
            for cond in all_conditions
            for term in ["cardiac", "coronary", "infarction", "angioplasty", "heart"]
        )
        if has_cardiac:
            med_docs = " ".join(
                str(d.get("document", "")) for d in evidence.get("medical", [])
            ).lower()
            if not any(t in med_docs for t in ["cardiology", "angioplasty", "stent", "ecg", "echo"]):
                gaps.append({
                    "gap_type": "missing_cardiology_workup",
                    "severity": "medium",
                    "description": "Cardiac history declared without detailed cardiology workup or intervention records.",
                })

        # 3. Previous policy declared but no existing policy schedule retrieved
        if submission.get("existing_policy") and not evidence.get("policy"):
            gaps.append({
                "gap_type": "missing_policy_schedule",
                "severity": "low",
                "description": "Previous policy declared but existing policy schedule could not be retrieved.",
            })

        return gaps


submission_agent = SubmissionIntelligenceAgent()