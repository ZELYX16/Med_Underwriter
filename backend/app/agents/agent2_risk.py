import re
from typing import Any

from app.config import settings
from app.llm.factory import get_llm


class RiskAssessmentAgent:
    def __init__(self):
        self.llm = get_llm(
            role="reasoning",
            temperature=0.1,
        )

    def run(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
        routing_result: dict[str, Any],
    ) -> dict[str, Any]:
        features = self._extract_features(
            applicant_profile=applicant_profile,
            submission=submission,
            enrichment_results=enrichment_results,
        )

        strategy = routing_result.get(
            "routing_strategy",
            "plan_and_execute",
        )

        reasoning = self._reason(
            applicant_profile=applicant_profile,
            submission=submission,
            enrichment_results=enrichment_results,
            routing_result=routing_result,
            features=features,
        )

        risk_scores = self._calculate_risk_scores(
            features=features,
            reasoning=reasoning,
        )

        pricing = self._calculate_pricing(
            submission=submission,
            risk_scores=risk_scores,
            reasoning=reasoning,
        )

        recommendation = self._recommend(
            risk_scores=risk_scores,
            pricing=pricing,
            reasoning=reasoning,
            routing_result=routing_result,
        )

        confidence = self._calculate_confidence(
            risk_scores=risk_scores,
            enrichment_results=enrichment_results,
            reasoning=reasoning,
        )

        return {
            "reasoning_strategy": strategy,
            "risk_assessment": {
                "medical_risk_score": risk_scores[
                    "medical_risk_score"
                ],
                "claims_risk_score": risk_scores[
                    "claims_risk_score"
                ],
                "overall_risk_score": risk_scores[
                    "overall_risk_score"
                ],
                "risk_factors": reasoning.get(
                    "risk_factors",
                    [],
                ),
                "protective_factors": reasoning.get(
                    "protective_factors",
                    [],
                ),
                "evidence_basis": reasoning.get(
                    "evidence_basis",
                    [],
                ),
            },
            "pricing_result": pricing,
            "recommendation": recommendation[
                "decision"
            ],
            "recommendation_reason": recommendation[
                "reason"
            ],
            "confidence": confidence,
            "reasoning": reasoning,
        }

    def _extract_features(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
    ) -> dict[str, Any]:
        medical = submission.get(
            "medical",
            {},
        )

        claims = (
            submission.get("claims", [])
            or enrichment_results.get("claims_evidence", [])
        )

        existing_policy = (
            submission.get("existing_policy")
            or (enrichment_results.get("policy_evidence", [{}])[0] if enrichment_results.get("policy_evidence") else None)
        )

        coverage_gaps = enrichment_results.get(
            "coverage_gaps",
            [],
        )

        conditions = (
            applicant_profile.get("medical_conditions", [])
            or submission.get("declared_pre_existing_conditions", [])
            or medical.get("conditions", [])
        )

        medications = (
            applicant_profile.get("medications", [])
            or medical.get("medications", [])
        )

        procedures = list(medical.get("procedures", []))
        hospitalizations = list(medical.get("hospitalizations", []))

        if isinstance(enrichment_results.get("medical_evidence"), list):
            for doc in enrichment_results.get("medical_evidence", []):
                doc_text = doc.get("document", "") if isinstance(doc, dict) else str(doc)
                if self._is_procedure(doc_text):
                    procedures.append("cardiac angioplasty/stent")
                if self._is_hospitalized(doc_text):
                    hospitalizations.append(doc_text)

        return {
            "age": applicant_profile.get(
                "age",
                0,
            ),
            "conditions": conditions,
            "medications": medications,
            "procedures": procedures,
            "hospitalizations": hospitalizations,
            "laboratory_results": medical.get(
                "laboratory_results",
                [],
            ),
            "lifestyle": applicant_profile.get(
                "lifestyle",
                medical.get("lifestyle", {}),
            ),
            "claims": claims,
            "claim_count": len(claims),
            "has_existing_policy": (
                existing_policy is not None
            ),
            "existing_sum_insured": (
                existing_policy.get(
                    "sum_insured",
                    0,
                )
                if existing_policy
                else 0
            ),
            "coverage_gap_count": len(
                coverage_gaps
            ),
        }

    def _reason(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
        routing_result: dict[str, Any],
        features: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = routing_result.get(
            "routing_strategy",
            "plan_and_execute",
        )

        prompt = f"""
You are a medical insurance underwriting risk assessment
assistant.

Your role is decision support. Do not invent medical facts,
claims, policy terms, regulatory requirements, or pricing rules.

Analyze the applicant using only the supplied evidence.

Applicant:
{applicant_profile}

Submission:
{submission}

Enrichment evidence:
{enrichment_results}

Complexity:
{routing_result}

Reasoning strategy:
{strategy}

Return a structured assessment containing:

risk_factors:
- important evidence-supported risk factors

protective_factors:
- evidence-supported favorable factors

evidence_basis:
- specific evidence supporting the assessment

medical_risk:
- qualitative assessment of medical risk

claims_risk:
- qualitative assessment of claims risk

pricing_considerations:
- factors that may affect pricing

reasoning:
- concise underwriting reasoning

Do not make a final medical diagnosis.
Do not create unsupported claims.
Do not treat a medical event as an insurance claim unless
claim evidence is present.
Do not attribute conditions from general medical knowledge or guidelines to the applicant unless confirmed in the applicant's medical report or declared conditions.
"""

        response = self.llm.invoke(prompt)

        content = response.content.strip()

        return {
            "strategy": strategy,
            "risk_factors": self._extract_section(
                content,
                "risk_factors",
            ),
            "protective_factors": self._extract_section(
                content,
                "protective_factors",
            ),
            "evidence_basis": self._extract_section(
                content,
                "evidence_basis",
            ),
            "medical_risk": self._extract_section(
                content,
                "medical_risk",
            ),
            "claims_risk": self._extract_section(
                content,
                "claims_risk",
            ),
            "pricing_considerations": self._extract_section(
                content,
                "pricing_considerations",
            ),
            "reasoning": content,
            "features": features,
        }

    def _calculate_risk_scores(
        self,
        features: dict[str, Any],
        reasoning: dict[str, Any],
    ) -> dict[str, float]:
        medical_score = 0.0
        claims_score = 0.0

        age = features["age"]
        conditions = features["conditions"]
        medications = features["medications"]
        hospitalizations = features["hospitalizations"]
        claims = features["claims"]

        if age >= 65:
            medical_score += 15
        elif age >= 55:
            medical_score += 10
        elif age >= 45:
            medical_score += 5

        condition_count = len(conditions)

        if condition_count >= 4:
            medical_score += 30
        elif condition_count >= 3:
            medical_score += 24
        elif condition_count >= 2:
            medical_score += 16
        elif condition_count == 1:
            medical_score += 8

        if len(medications) >= 6:
            medical_score += 15
        elif len(medications) >= 4:
            medical_score += 10
        elif len(medications) >= 2:
            medical_score += 5

        if len(hospitalizations) >= 3:
            medical_score += 20
        elif len(hospitalizations) >= 2:
            medical_score += 14
        elif len(hospitalizations) == 1:
            medical_score += 7

        if claims:
            claim_count = len(claims)

            if claim_count >= 5:
                claims_score += 40
            elif claim_count >= 3:
                claims_score += 30
            elif claim_count >= 2:
                claims_score += 20
            else:
                claims_score += 10

        medical_score = min(
            medical_score,
            100.0,
        )

        claims_score = min(
            claims_score,
            100.0,
        )

        overall_score = (
            medical_score * 0.65
            + claims_score * 0.35
        )

        return {
            "medical_risk_score": round(
                medical_score,
                2,
            ),
            "claims_risk_score": round(
                claims_score,
                2,
            ),
            "overall_risk_score": round(
                overall_score,
                2,
            ),
        }

    def _calculate_pricing(
        self,
        submission: dict[str, Any],
        risk_scores: dict[str, float],
        reasoning: dict[str, Any],
    ) -> dict[str, Any]:
        request = submission.get(
            "underwriting_request",
            {},
        )

        sum_insured = float(
            submission.get("sum_insured")
            or request.get("sum_insured", 0)
            or 0
        )

        risk_score = risk_scores[
            "overall_risk_score"
        ]

        base_rate = self._get_base_rate(
            sum_insured=sum_insured,
            policy_term_years=int(
                submission.get(
                    "policy_term_years",
                    request.get("policy_term_years", 1),
                )
                or 1
            ),
        )

        loading = self._get_loading(
            risk_score
        )

        final_premium = (
            base_rate * (1 + loading / 100)
        )

        return {
            "currency": "INR",
            "sum_insured": sum_insured,
            "base_premium": round(
                base_rate,
                2,
            ),
            "loading_percentage": round(
                loading,
                2,
            ),
            "final_premium": round(
                final_premium,
                2,
            ),
            "pricing_basis": [
                "Configured demonstration pricing model",
                "Overall risk score",
                "Requested sum insured",
                "Policy term",
            ],
            "disclaimer": (
                "Demonstration pricing only. "
                "Production pricing must use approved "
                "actuarial pricing rules."
            ),
        }

    @staticmethod
    def _get_base_rate(
        sum_insured: float,
        policy_term_years: int,
    ) -> float:
        if sum_insured <= 0:
            return 0.0

        annual_rate = 0.03

        base = sum_insured * annual_rate

        return base * max(
            policy_term_years,
            1,
        )

    @staticmethod
    def _get_loading(
        risk_score: float,
    ) -> float:
        if risk_score >= 75:
            return 40.0

        if risk_score >= 60:
            return 30.0

        if risk_score >= 45:
            return 20.0

        if risk_score >= 30:
            return 10.0

        return 0.0

    @staticmethod
    def _recommend(
        risk_scores: dict[str, float],
        pricing: dict[str, Any],
        reasoning: dict[str, Any],
        routing_result: dict[str, Any],
    ) -> dict[str, str]:
        score = risk_scores[
            "overall_risk_score"
        ]

        if score >= 75:
            return {
                "decision": "human_review",
                "reason": (
                    "High overall risk requires "
                    "underwriter review."
                ),
            }

        if score >= 60:
            return {
                "decision": "accept_with_loading",
                "reason": (
                    "Elevated risk may require "
                    "additional premium loading."
                ),
            }

        if score >= 30 or float(pricing.get("loading_percentage", 0) or 0) > 0:
            return {
                "decision": "accept_with_loading",
                "reason": (
                    "Moderate risk indicates "
                    "potential loading."
                ),
            }

        return {
            "decision": "standard_acceptance",
            "reason": (
                "Available evidence indicates "
                "relatively limited underwriting risk."
            ),
        }

    @staticmethod
    def _calculate_confidence(
        risk_scores: dict[str, float],
        enrichment_results: dict[str, Any],
        reasoning: dict[str, Any],
    ) -> float:
        evidence_summary = enrichment_results.get(
            "evidence_summary",
            {},
        )

        doc_count_summary = sum(
            int(value or 0)
            for key, value in evidence_summary.items()
            if (key.endswith("_documents") or key.endswith("_records_count") or key.endswith("_count"))
            and isinstance(value, (int, float))
        )

        doc_count_direct = (
            len(enrichment_results.get("medical_evidence", []))
            + len(enrichment_results.get("claims_evidence", []))
            + len(enrichment_results.get("policy_evidence", []))
        )

        document_count = max(doc_count_summary, doc_count_direct)

        confidence = 0.55

        if document_count >= 2:
            confidence += 0.15

        if document_count >= 5:
            confidence += 0.10

        if enrichment_results.get(
            "medical_evidence",
        ) or enrichment_results.get(
            "medical_knowledge",
        ):
            confidence += 0.05

        if enrichment_results.get(
            "regulatory_evidence",
        ):
            confidence += 0.05

        if risk_scores[
            "overall_risk_score"
        ] >= 75:
            confidence -= 0.10

        return round(
            max(
                0.0,
                min(
                    confidence,
                    0.95,
                ),
            ),
            2,
        )

    @staticmethod
    def _extract_section(
        content: str,
        section_name: str,
    ) -> list[str]:
        lines = content.splitlines()

        collecting = False
        values = []

        for line in lines:
            stripped = line.strip()

            if not stripped:
                continue

            normalized = stripped.lower()

            if normalized.startswith(
                f"{section_name.lower()}:"
            ):
                collecting = True

                remainder = stripped.split(
                    ":",
                    1,
                )[1].strip()

                if remainder:
                    values.append(
                        remainder
                    )

                continue

            if collecting and stripped.endswith(
                ":"
            ):
                break

            if collecting:
                values.append(
                    stripped.lstrip(
                        "-* "
                    )
                )

        return values

    @staticmethod
    def _is_hospitalized(text: str) -> bool:
        negation = re.compile(
            r"\b(no|denies|without|none|zero|negative for)\b(?:\s+\w+){0,3}\s+\b(hospitalization|hospitalized|admission|admitted)\b",
            re.IGNORECASE,
        )
        if negation.search(text):
            return False
        positive = re.compile(
            r"\b(hospitalization|hospitalized|admission|admitted)\b",
            re.IGNORECASE,
        )
        return bool(positive.search(text))

    @staticmethod
    def _is_procedure(text: str) -> bool:
        negation = re.compile(
            r"\b(no|denies|without|none|zero|negative for)\b(?:\s+\w+){0,3}\s+\b(angioplasty|stent|surgery|bypass|procedure)\b",
            re.IGNORECASE,
        )
        if negation.search(text):
            return False
        positive = re.compile(
            r"\b(angioplasty|stent|surgery|bypass)\b",
            re.IGNORECASE,
        )
        return bool(positive.search(text))


risk_agent = RiskAssessmentAgent()
