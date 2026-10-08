from __future__ import annotations

import time
from typing import Any

from app.config import settings
from app.llm.factory import get_llm


class RiskAssessmentAgent:
    """
    Agent 2: Risk Assessment and Pricing.

    Performs deterministic underwriting calculations first and optionally
    uses the configured LLM to provide supporting reasoning.
    """

    def __init__(self) -> None:
        self.llm = None
        self._last_llm_metrics: dict[str, Any] = {}

    def run(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
        routing_result: dict[str, Any],
    ) -> dict[str, Any]:
        agent_started = time.perf_counter()

        features = self._extract_features(
            applicant_profile,
            submission,
            enrichment_results,
        )

        risk = self._calculate_risk(features)

        pricing = self._calculate_pricing(
            submission=submission,
            risk=risk,
            features=features,
        )

        recommendation = self._recommend(
            risk_score=risk["overall_risk_score"],
            features=features,
        )

        confidence = self._calculate_confidence(
            features=features,
            enrichment_results=enrichment_results,
            risk=risk,
        )

        reasoning = self._reason(
            applicant_profile=applicant_profile,
            submission=submission,
            features=features,
            risk=risk,
            pricing=pricing,
            recommendation=recommendation,
            routing_result=routing_result,
        )

        decision_basis = self._build_decision_basis(
            risk=risk,
            pricing=pricing,
            recommendation=recommendation,
            confidence=confidence,
        )

        metrics = self._build_metrics(
            started=agent_started,
            llm_metrics=getattr(self, "_last_llm_metrics", {}),
        )

        return {
            "risk_assessment": {
                "medical_risk_score": risk["medical_risk_score"],
                "claims_risk_score": risk["claims_risk_score"],
                "coverage_gap_score": risk["coverage_gap_score"],
                "overall_risk_score": risk["overall_risk_score"],
                "risk_factors": risk["risk_factors"],
                "protective_factors": risk["protective_factors"],
                "evidence_completeness": risk["evidence_completeness"],
                "evidence_domains": risk.get("evidence_domains", {}),
                "evidence_gaps": risk.get("evidence_gaps", []),
                "decision_basis": decision_basis,
            },
            "medical_risk_score": risk["medical_risk_score"],
            "claims_risk_score": risk["claims_risk_score"],
            "coverage_gap_score": risk["coverage_gap_score"],
            "overall_risk_score": risk["overall_risk_score"],
            "pricing_result": pricing,
            "base_premium": pricing["base_premium"],
            "loading_percentage": pricing["loading_percentage"],
            "final_premium": pricing["final_premium"],
            "agent2_recommendation": recommendation,
            "agent2_confidence": confidence,
            "agent2_reasoning": reasoning,
            "decision_basis": decision_basis,
            "metrics": metrics,
            "agent2_metrics": metrics,
            "agent2_completed": True,
        }

    def _extract_features(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
    ) -> dict[str, Any]:
        medical = self._first_dict(
            submission.get("medical"),
            applicant_profile.get("medical"),
        )

        conditions = self._as_list(
            medical.get("conditions")
            or applicant_profile.get("medical_conditions")
            or applicant_profile.get("conditions")
        )

        conditions = self._deduplicate_values(conditions)

        medications = self._as_list(
            medical.get("medications")
            or applicant_profile.get("medications")
        )

        medications = self._deduplicate_values(medications)

        hospitalizations = self._as_list(
            medical.get("hospitalizations")
            or applicant_profile.get("hospitalizations")
        )

        hospitalizations = self._deduplicate_values(
            hospitalizations
        )

        medical_evidence = self._as_list(
            enrichment_results.get("medical_evidence")
        )

        claims_evidence = self._as_list(
            enrichment_results.get("claims_evidence")
        )

        claims = self._as_list(
            submission.get("claims")
            or applicant_profile.get("claims")
        )

        if not claims and claims_evidence:
            claims = self._extract_claims_from_evidence(
                claims_evidence
            )

        claims = self._deduplicate_claims(claims)

        policy_evidence = self._as_list(
            enrichment_results.get("policy_evidence")
        )

        regulatory_evidence = self._as_list(
            enrichment_results.get("regulatory_evidence")
        )

        underwriting_evidence = self._as_list(
            enrichment_results.get("underwriting_evidence")
            or enrichment_results.get(
                "underwriting_knowledge_evidence"
            )
        )

        coverage_gaps = self._as_list(
            enrichment_results.get("coverage_gaps")
        )

        age = self._number(
            applicant_profile.get("age")
            or submission.get("age")
        )

        bmi = self._number(
            applicant_profile.get("bmi")
            or medical.get("bmi")
        )

        sum_insured = self._extract_sum_insured(submission)

        term_years = self._number(
            submission.get("term_years")
            or submission.get("policy_term")
            or 1
        )

        return {
            "age": age,
            "bmi": bmi,
            "conditions": conditions,
            "medications": medications,
            "hospitalizations": hospitalizations,
            "claims": claims,
            "medical_evidence": medical_evidence,
            "claims_evidence": claims_evidence,
            "policy_evidence": policy_evidence,
            "regulatory_evidence": regulatory_evidence,
            "underwriting_evidence": underwriting_evidence,
            "coverage_gaps": coverage_gaps,
            "sum_insured": sum_insured,
            "term_years": max(term_years, 1),
            "condition_count": len(conditions),
            "medication_count": len(medications),
            "hospitalization_count": len(hospitalizations),
            "claim_count": len(claims),
        }

    @staticmethod
    def _deduplicate_values(
        values: list[Any],
    ) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()

        for value in values:
            if value is None:
                continue

            key = str(value).strip().lower()

            if not key or key in seen:
                continue

            seen.add(key)
            result.append(value)

        return result

    @staticmethod
    def _deduplicate_claims(
        claims: list[Any],
    ) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()

        for claim in claims:
            if not isinstance(claim, dict):
                key = str(claim).strip().lower()

                if key and key not in seen:
                    seen.add(key)
                    result.append(claim)

                continue

            claim_id = str(
                claim.get("claim_id")
                or ""
            ).strip().lower()

            date = str(
                claim.get("date")
                or claim.get("claim_date")
                or ""
            ).strip().lower()

            description = str(
                claim.get("description")
                or ""
            ).strip().lower()

            key = "|".join(
                part
                for part in (
                    claim_id,
                    date,
                    description,
                )
                if part
            )

            if not key:
                key = str(claim).strip().lower()

            if key in seen:
                continue

            seen.add(key)
            result.append(claim)

        return result

    @classmethod
    def _extract_claims_from_evidence(
        cls,
        claims_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []

        for item in claims_evidence:
            if not isinstance(item, dict):
                continue

            metadata = item.get("metadata", {})

            if not isinstance(metadata, dict):
                metadata = {}

            content = str(
                item.get("content")
                or item.get("text")
                or ""
            ).strip()

            claim = {
                "claim_id": (
                    item.get("claim_id")
                    or metadata.get("claim_id")
                    or metadata.get("document_id")
                    or metadata.get("file_name")
                ),
                "date": (
                    item.get("claim_date")
                    or item.get("date")
                    or metadata.get("claim_date")
                ),
                "description": (
                    item.get("description")
                    or content[:500]
                ),
                "content": content,
                "source": "applicant_claim_evidence",
            }

            if (
                claim["claim_id"]
                or claim["date"]
                or claim["description"]
                or claim["content"]
            ):
                claims.append(claim)

        return claims

    def _calculate_risk(
        self,
        features: dict[str, Any],
    ) -> dict[str, Any]:
        medical_score = 0.0
        claims_score = 0.0

        risk_factors: list[str] = []
        protective_factors: list[str] = []

        age = features["age"]
        bmi = features["bmi"]
        conditions = features["conditions"]
        medications = features["medications"]
        hospitalizations = features["hospitalizations"]
        claims = features["claims"]
        coverage_gaps = features["coverage_gaps"]

        if age >= 60:
            medical_score += 20
            risk_factors.append("Age 60 or above")
        elif age >= 50:
            medical_score += 12
            risk_factors.append("Age 50 or above")
        elif age >= 40:
            medical_score += 6

        if bmi >= 30:
            medical_score += 10
            risk_factors.append("BMI indicates obesity")
        elif bmi >= 25:
            medical_score += 5
            risk_factors.append("BMI indicates overweight range")
        elif 18.5 <= bmi < 25:
            protective_factors.append(
                "BMI within normal range"
            )

        condition_weights = {
            "diabetes": 15,
            "hypertension": 8,
            "coronary": 20,
            "cardiac": 20,
            "heart": 20,
            "cancer": 25,
            "renal": 18,
            "kidney": 18,
            "liver": 15,
            "copd": 15,
            "asthma": 8,
            "rheumatoid": 10,
            "arthritis": 5,
            "thyroid": 4,
            "hypothyroidism": 4,
        }

        for condition in conditions:
            condition_text = self._text(condition)
            condition_text = (
                condition_text
                .replace("Year diagnosed Status (as declared) ", "")
                .replace("Year diagnosed Status", "")
                .strip()
            )
            text = condition_text.lower()
            matched = False

            for keyword, weight in condition_weights.items():
                if keyword in text:
                    medical_score += weight
                    risk_factors.append(
                        "Medical condition requiring assessment: "
                        + condition_text
                    )
                    matched = True
                    break

            if not matched:
                medical_score += 3

        if len(conditions) >= 3:
            medical_score += 8
            risk_factors.append(
                "Multiple chronic conditions"
            )

        if len(medications) >= 4:
            medical_score += 5
            risk_factors.append(
                "Multiple ongoing medications"
            )

        if hospitalizations:
            medical_score += min(
                len(hospitalizations) * 5,
                15,
            )
            risk_factors.append(
                "History of hospitalization"
            )

        if claims:
            claims_score += min(
                len(claims) * 12,
                45,
            )
            risk_factors.append(
                "Previous insurance claims"
            )

        recent_claims = self._count_recent_claims(claims)

        if recent_claims >= 3:
            claims_score += 15
            risk_factors.append(
                "Multiple recent claims"
            )

        if len(claims) == 0:
            protective_factors.append(
                "No declared insurance claims"
            )

        if len(hospitalizations) == 0:
            protective_factors.append(
                "No declared hospitalization history"
            )

        coverage_gap_score = min(
            len(coverage_gaps) * 10,
            100,
        )

        if coverage_gaps:
            risk_factors.append(
                "Potential coverage gaps identified"
            )

        medical_score = min(
            round(medical_score, 2),
            100.0,
        )

        claims_score = min(
            round(claims_score, 2),
            100.0,
        )

        overall = round(
            (medical_score * 0.60)
            + (claims_score * 0.30)
            + (coverage_gap_score * 0.10),
            2,
        )

        evidence_domains = {
            "medical": bool(features["medical_evidence"]),
            "claims": bool(features["claims_evidence"]),
            "policy": bool(features["policy_evidence"]),
            "regulatory": bool(features["regulatory_evidence"]),
            "underwriting": bool(
                features["underwriting_evidence"]
            ),
        }

        evidence_completeness = round(
            sum(evidence_domains.values())
            / len(evidence_domains),
            2,
        )

        return {
            "medical_risk_score": medical_score,
            "claims_risk_score": claims_score,
            "coverage_gap_score": coverage_gap_score,
            "overall_risk_score": overall,
            "risk_factors": self._unique(
                risk_factors
            ),
            "protective_factors": self._unique(
                protective_factors
            ),
            "evidence_completeness": evidence_completeness,
            "evidence_domains": evidence_domains,
            "evidence_gaps": [
                domain
                for domain, available in evidence_domains.items()
                if not available
            ],
            "coverage_gaps": coverage_gaps,
        }

    def _calculate_pricing(
        self,
        submission: dict[str, Any],
        risk: dict[str, Any],
        features: dict[str, Any],
    ) -> dict[str, float]:
        sum_insured = features["sum_insured"]

        if sum_insured <= 0:
            sum_insured = 1_000_000.0

        term_years = features["term_years"]

        base_rate = 0.03

        base_premium = (
            sum_insured
            * base_rate
            * term_years
        )

        risk_score = risk["overall_risk_score"]

        if risk_score >= 70:
            loading = 40.0
        elif risk_score >= 60:
            loading = 30.0
        elif risk_score >= 45:
            loading = 20.0
        elif risk_score >= 30:
            loading = 10.0
        else:
            loading = 0.0

        final_premium = (
            base_premium
            * (1 + loading / 100)
        )

        return {
            "base_rate": round(
                base_rate,
                4,
            ),
            "base_premium": round(
                base_premium,
                2,
            ),
            "loading_percentage": loading,
            "loading_amount": round(
                final_premium - base_premium,
                2,
            ),
            "final_premium": round(
                final_premium,
                2,
            ),
            "currency": "INR",
            "pricing_basis": "DEMO_UNDERWRITING_MODEL",
        }

    def _recommend(
        self,
        risk_score: float,
        features: dict[str, Any],
    ) -> str:
        if risk_score >= 70:
            return "human_review"

        if risk_score >= 45:
            return "accept_with_loading"

        if features["condition_count"] >= 3:
            return "accept_with_loading"

        return "standard_acceptance"

    def _calculate_confidence(
        self,
        features: dict[str, Any],
        enrichment_results: dict[str, Any],
        risk: dict[str, Any],
    ) -> float:
        confidence = 0.55

        evidence_count = (
            len(features["medical_evidence"])
            + len(features["claims_evidence"])
            + len(features["policy_evidence"])
            + len(features["regulatory_evidence"])
        )

        if evidence_count >= 2:
            confidence += 0.10

        if evidence_count >= 5:
            confidence += 0.10

        if features["condition_count"] == 0:
            confidence += 0.08

        if features["claim_count"] == 0:
            confidence += 0.05

        if features["medical_evidence"]:
            confidence += 0.05

        if features["claims_evidence"]:
            confidence += 0.05

        if risk["evidence_completeness"] >= 0.75:
            confidence += 0.07
        elif risk["evidence_completeness"] < 0.75:
            confidence -= 0.10

        if features["coverage_gaps"]:
            confidence -= 0.10

        if risk["overall_risk_score"] >= 70:
            confidence -= 0.05

        return round(
            max(
                0.0,
                min(confidence, 0.99),
            ),
            2,
        )

    @staticmethod
    def _extract_token_usage(response: Any) -> dict[str, int]:
        usage: Any = getattr(response, "usage_metadata", None)

        if not isinstance(usage, dict):
            metadata = getattr(response, "response_metadata", None)
            if isinstance(metadata, dict):
                usage = (
                    metadata.get("token_usage")
                    or metadata.get("usage")
                    or metadata.get("usage_metadata")
                )

        if not isinstance(usage, dict):
            usage = getattr(response, "usage", None)

        if not isinstance(usage, dict):
            usage = {}

        input_tokens = int(
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or usage.get("input_token_count")
            or 0
        )
        output_tokens = int(
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or usage.get("output_token_count")
            or 0
        )
        total_tokens = int(
            usage.get("total_tokens")
            or input_tokens + output_tokens
        )

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _build_metrics(
        started: float,
        llm_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        input_tokens = int(llm_metrics.get("input_tokens", 0) or 0)
        output_tokens = int(llm_metrics.get("output_tokens", 0) or 0)
        total_tokens = int(
            llm_metrics.get("total_tokens", 0)
            or input_tokens + output_tokens
        )

        return {
            "latency_sec": round(time.perf_counter() - started, 4),
            "llm_latency_sec": float(
                llm_metrics.get("llm_latency_sec", 0.0) or 0.0
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _build_decision_basis(
        risk: dict[str, Any],
        pricing: dict[str, float],
        recommendation: str,
        confidence: float,
    ) -> dict[str, Any]:
        medical = float(risk["medical_risk_score"])
        claims = float(risk["claims_risk_score"])
        coverage = float(risk["coverage_gap_score"])
        overall = float(risk["overall_risk_score"])

        if overall >= 70:
            rule = "risk >= 70"
        elif overall >= 60:
            rule = "60 <= risk < 70"
        elif overall >= 45:
            rule = "45 <= risk < 60"
        elif overall >= 30:
            rule = "30 <= risk < 45"
        else:
            rule = "risk < 30"

        return {
            "medical_risk": {
                "score": medical,
                "weight": 0.60,
                "contributors": risk.get("risk_factors", [])[:5],
            },
            "claims_risk": {
                "score": claims,
                "weight": 0.30,
            },
            "coverage_assessment": {
                "score": coverage,
                "confirmed_gaps": risk.get("coverage_gaps", []),
                "evidence_gaps": risk.get("evidence_gaps", []),
            },
            "overall_risk": {
                "score": overall,
                "formula": (
                    f"{medical:g} × 0.60 + "
                    f"{claims:g} × 0.30 + "
                    f"{coverage:g} × 0.10"
                ),
            },
            "recommendation": {
                "result": recommendation,
                "rule": rule,
            },
            "confidence": confidence,
            "pricing": {
                "base_rate": pricing.get("base_rate", 0.0),
                "base_premium": pricing.get("base_premium", 0.0),
                "loading_percentage": pricing.get(
                    "loading_percentage", 0.0
                ),
                "loading_amount": pricing.get(
                    "loading_amount", 0.0
                ),
                "final_premium": pricing.get(
                    "final_premium", 0.0
                ),
                "basis": pricing.get(
                    "pricing_basis",
                    "DEMO_UNDERWRITING_MODEL",
                ),
            },
        }

    def _reason(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        features: dict[str, Any],
        risk: dict[str, Any],
        pricing: dict[str, float],
        recommendation: str,
        routing_result: dict[str, Any],
    ) -> str:
        """
        Generate grounded underwriting reasoning.

        Deterministic risk, pricing, and recommendation outputs are
        authoritative. The LLM only explains those outputs.
        """
        try:
            if self.llm is None:
                self.llm = get_llm("reasoning")

            authoritative_facts = {
                "applicant_id": applicant_profile.get(
                    "applicant_id"
                ),
                "age": features.get("age"),
                "gender": applicant_profile.get("gender"),
                "bmi": features.get("bmi"),
                "smoker": applicant_profile.get("smoker"),
                "alcohol_use": applicant_profile.get(
                    "alcohol_use"
                ),
                "medical_conditions": features.get(
                    "conditions",
                    [],
                ),
                "medications": features.get(
                    "medications",
                    [],
                ),
                "hospitalizations": features.get(
                    "hospitalizations",
                    [],
                ),
                "claims": features.get(
                    "claims",
                    [],
                ),
                "condition_count": features.get(
                    "condition_count",
                    0,
                ),
                "medication_count": features.get(
                    "medication_count",
                    0,
                ),
                "hospitalization_count": features.get(
                    "hospitalization_count",
                    0,
                ),
                "claim_count": features.get(
                    "claim_count",
                    0,
                ),
            }

            evidence_summary = {
                "medical_evidence_count": len(
                    features.get("medical_evidence", [])
                    if isinstance(
                        features.get("medical_evidence"),
                        list,
                    )
                    else []
                ),
                "claims_evidence_count": len(
                    features.get("claims_evidence", [])
                    if isinstance(
                        features.get("claims_evidence"),
                        list,
                    )
                    else []
                ),
                "policy_evidence_count": len(
                    features.get("policy_evidence", [])
                    if isinstance(
                        features.get("policy_evidence"),
                        list,
                    )
                    else []
                ),
                "underwriting_evidence_count": len(
                    features.get(
                        "underwriting_evidence",
                        [],
                    )
                    if isinstance(
                        features.get("underwriting_evidence"),
                        list,
                    )
                    else []
                ),
                "regulatory_evidence_count": len(
                    features.get("regulatory_evidence", [])
                    if isinstance(
                        features.get("regulatory_evidence"),
                        list,
                    )
                    else []
                ),
            }

            prompt = f"""
You are a medical insurance underwriting reasoning assistant.

Generate a concise, factual underwriting rationale from the supplied data.

AUTHORITATIVE RULES:
- Applicant profile is authoritative for applicant facts.
- Retrieved applicant evidence is authoritative for applicant-specific evidence.
- Deterministic risk, pricing, and recommendation are authoritative.
- The LLM explains the decision; it must not make a new decision.
- Use only supplied information.
- Never invent, infer, estimate, or assume applicant facts.
- Medical conditions must come only from AUTHORITATIVE APPLICANT FACTS.
- Medications must come only from AUTHORITATIVE APPLICANT FACTS.
- Do not use regulatory or underwriting knowledge as applicant medical facts.
- Do not use general medical knowledge to create diagnoses.
- Always use the exact supplied age, BMI, medical conditions, and medications.
- Never replace an exact supplied value with a different value.
- Do not change any risk score, loading, premium, confidence, or recommendation.
- Do not infer a claim from a hospitalization.
- Do not infer a hospitalization from a claim.
- Do not treat a medical event as a claim unless it is explicitly identified as a claim.
- Do not introduce unsupported diagnoses, procedures, policy terms, coverage gaps, or regulations.
- Do not use regulatory evidence as medical-risk evidence.
- If coverage_gap_score is 0, explicitly state that no coverage gap was identified.
- If claims evidence count is greater than 0, do not state that claims evidence is absent.

AUTHORITATIVE APPLICANT FACTS:
{authoritative_facts}

EVIDENCE AVAILABILITY:
{evidence_summary}

APPLICANT SUBMISSION:
{submission}

EXTRACTED FEATURES:
{features}

DETERMINISTIC RISK ASSESSMENT:
{risk}

DETERMINISTIC PRICING:
{pricing}

DETERMINISTIC RECOMMENDATION:
{recommendation}

ROUTING:
{routing_result}

Write exactly these five sections:

1. Main Medical Risk Factors
- State the exact applicant age.
- State the exact BMI when supplied.
- List only medical conditions from AUTHORITATIVE APPLICANT FACTS.
- List only medications from AUTHORITATIVE APPLICANT FACTS.
- Do not replace a specific condition with a broader or different condition.
- Mention smoking/alcohol status only when supplied.
- Mention hospitalizations only when explicitly present.
- Explain how these facts relate to the deterministic medical risk score.
- Do not introduce any new diagnosis, condition, medication, or medical interpretation.

2. Claims and Utilization
- State the deterministic claim count exactly when it is greater than zero.
- Describe claims only when supported by supplied claims data or applicant-specific claims evidence.
- Describe hospitalizations separately from claims.
- Do not convert hospitalizations into claims or claims into hospitalizations.
- If claim count is zero, state that no claims were identified.
- If claim count is greater than zero, never state that no claims were identified.

3. Protective Factors
- Mention only protective factors explicitly supported by the supplied data.
- If none are supported, state that no specific protective factors were identified.

4. Coverage and Evidence
- State the deterministic coverage_gap_score.
- If coverage_gap_score is 0, state that no coverage gap was identified.
- Mention evidence availability only using the supplied evidence counts.
- Do not call an evidence limitation a coverage gap.

5. Recommendation Rationale
- State the deterministic recommendation.
- Explain it using the deterministic overall risk assessment and pricing.
- Mention the final premium/loading when supplied.
- Do not modify or reinterpret the deterministic decision.

FINAL VALIDATION:
- Every medical condition mentioned must appear in AUTHORITATIVE APPLICANT FACTS.
- Every medication mentioned must appear in AUTHORITATIVE APPLICANT FACTS.
- Do not add diagnoses.
- Do not add medications.
- Claim count must match deterministic claim_count.
- Claims and hospitalizations must remain separate.
- If claim_count > 0, never say no claims were identified.
- If claim_count = 0, never imply claims exist.
- coverage_gap_score = 0 means no coverage gap was identified.
- Do not use regulatory or underwriting knowledge as applicant facts.
- Do not contradict the deterministic risk assessment.
- Do not modify recommendation, loading, premium, or risk scores.

Return only the underwriting rationale.
""".strip()

            llm_started = time.perf_counter()
            response = self.llm.invoke(prompt)
            llm_latency = round(time.perf_counter() - llm_started, 4)
            self._last_llm_metrics = {
                **self._extract_token_usage(response),
                "llm_latency_sec": llm_latency,
            }

            content = getattr(
                response,
                "content",
                response,
            )

            if isinstance(content, list):
                content = " ".join(
                    str(item.get("text", item))
                    if isinstance(item, dict)
                    else str(item)
                    for item in content
                )

            reasoning = str(content).strip()

            if not self._reasoning_is_consistent(
                reasoning=reasoning,
                features=features,
                risk=risk,
                recommendation=recommendation,
            ):
                return self._fallback_reasoning(
                    risk=risk,
                    pricing=pricing,
                    recommendation=recommendation,
                    error=(
                        "LLM reasoning failed deterministic "
                        "consistency checks."
                    ),
                )

            return reasoning

        except Exception as exc:
            self._last_llm_metrics = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "llm_latency_sec": 0.0,
            }
            return self._fallback_reasoning(
                risk=risk,
                pricing=pricing,
                recommendation=recommendation,
                error=str(exc),
            )

    @staticmethod
    def _reasoning_is_consistent(
        reasoning: str,
        features: dict[str, Any],
        risk: dict[str, Any],
        recommendation: str,
    ) -> bool:
        """
        Validate the generated rationale against deterministic facts.
        If the LLM contradicts important facts, fallback reasoning is used.
        """
        if not reasoning.strip():
            return False

        text = reasoning.lower()

        claim_count = int(
            features.get("claim_count", 0) or 0
        )

        coverage_gap_score = float(
            risk.get("coverage_gap_score", 0.0) or 0.0
        )

        if claim_count > 0:
            forbidden_claim_phrases = (
                "no claims were identified",
                "no claims identified",
                "no insurance claims",
                "no claim history",
                "there were no claims",
            )

            if any(
                phrase in text
                for phrase in forbidden_claim_phrases
            ):
                return False

        if claim_count == 0:
            forbidden_positive_claim_phrases = (
                "previous insurance claims",
                "multiple claims",
                "claim history shows",
                "claims were identified",
                "insurance claims were identified",
            )

            if any(
                phrase in text
                for phrase in forbidden_positive_claim_phrases
            ):
                return False

        if coverage_gap_score == 0:
            forbidden_gap_phrases = (
                "coverage gap was identified",
                "coverage gaps were identified",
                "potential coverage gap",
                "coverage gap exists",
                "coverage gaps exist",
            )

            if any(
                phrase in text
                for phrase in forbidden_gap_phrases
            ):
                return False

        if not recommendation:
            return False

        return True

    @staticmethod
    def _fallback_reasoning(
        risk: dict[str, Any],
        pricing: dict[str, float],
        recommendation: str,
        error: str | None = None,
    ) -> str:
        parts = [
            (
                f"Overall risk score: "
                f"{risk['overall_risk_score']:.2f}."
            ),
            (
                f"Medical risk score: "
                f"{risk['medical_risk_score']:.2f}."
            ),
            (
                f"Claims risk score: "
                f"{risk['claims_risk_score']:.2f}."
            ),
            (
                f"Coverage gap score: "
                f"{risk['coverage_gap_score']:.2f}."
            ),
            (
                f"Evidence completeness: "
                f"{risk['evidence_completeness']:.2f}."
            ),
        ]

        if risk["risk_factors"]:
            parts.append(
                "Key risk factors: "
                + "; ".join(
                    risk["risk_factors"][:5]
                )
                + "."
            )

        if risk["protective_factors"]:
            parts.append(
                "Protective factors: "
                + "; ".join(
                    risk["protective_factors"][:5]
                )
                + "."
            )

        if risk["coverage_gap_score"] == 0:
            parts.append(
                "No coverage gap was identified."
            )

        parts.append(
            f"Recommended action: {recommendation}."
        )

        parts.append(
            f"Base premium: INR "
            f"{pricing['base_premium']:,.2f}; "
            f"loading: "
            f"{pricing['loading_percentage']:.0f}%; "
            f"final premium: INR "
            f"{pricing['final_premium']:,.2f}."
        )

        if error:
            parts.append(
                "LLM reasoning was unavailable or failed "
                "consistency validation, so deterministic "
                "underwriting reasoning was used."
            )

        return " ".join(parts)

    @staticmethod
    def _extract_sum_insured(
        submission: dict[str, Any],
    ) -> float:
        candidates = [
            submission.get("sum_insured"),
            submission.get("coverage_amount"),
            submission.get("sumInsured"),
            submission.get("requested_sum_insured"),
        ]

        for value in candidates:
            number = RiskAssessmentAgent._number(
                value
            )

            if number > 0:
                return number

        return 0.0

    @staticmethod
    def _count_recent_claims(
        claims: list[Any],
    ) -> int:
        recent_count = 0

        for claim in claims:
            if not isinstance(claim, dict):
                continue

            if claim.get("recent") is True:
                recent_count += 1
                continue

            period = str(
                claim.get("claim_date")
                or claim.get("date")
                or claim.get("admission_date")
                or ""
            )

            if period.startswith(
                ("2024", "2025", "2026")
            ):
                recent_count += 1

        return recent_count

    @staticmethod
    def _first_dict(
        *values: Any,
    ) -> dict[str, Any]:
        for value in values:
            if isinstance(value, dict):
                return value

        return {}

    @staticmethod
    def _as_list(
        value: Any,
    ) -> list[Any]:
        if value is None:
            return []

        if isinstance(value, list):
            return value

        if isinstance(value, tuple):
            return list(value)

        if isinstance(value, set):
            return list(value)

        return [value]

    @staticmethod
    def _number(
        value: Any,
    ) -> float:
        if value is None:
            return 0.0

        if isinstance(value, bool):
            return float(value)

        try:
            text = (
                str(value)
                .replace(",", "")
                .strip()
            )

            digits = ""
            decimal_found = False

            for char in text:
                if char.isdigit():
                    digits += char
                elif char == "." and not decimal_found:
                    digits += char
                    decimal_found = True
                elif digits:
                    break

            return (
                float(digits)
                if digits
                else 0.0
            )

        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _text(
        value: Any,
    ) -> str:
        if isinstance(value, dict):
            return str(
                value.get("name")
                or value.get("condition")
                or value.get("diagnosis")
                or value.get("description")
                or value
            )

        return str(value)

    @staticmethod
    def _unique(
        values: list[str],
    ) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for value in values:
            normalized = value.strip()

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            result.append(normalized)

        return result

risk_agent = RiskAssessmentAgent()