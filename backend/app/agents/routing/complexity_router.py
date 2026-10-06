from typing import Any, Literal

from app.llm.factory import get_llm


ComplexityLevel = Literal[
    "simple",
    "standard",
    "complex",
]


class ComplexityRouter:
    def __init__(self):
        self.llm = get_llm(
            role="planner",
            temperature=0.0,
        )

    def route(
        self,
        applicant_profile: dict[str, Any],
        enrichment_results: dict[str, Any],
    ) -> dict[str, Any]:
        features = self._extract_features(
            applicant_profile,
            enrichment_results,
        )

        complexity = self._rule_based_complexity(
            features
        )

        if complexity is None:
            complexity = self._llm_complexity(
                features
            )

        strategy = self._select_strategy(
            complexity
        )

        reasons = self._build_reasons(
            features,
            complexity,
        )

        return {
            "complexity_level": complexity,
            "routing_strategy": strategy,
            "complexity_reasons": reasons,
            "features": features,
        }

    def _extract_features(
        self,
        applicant_profile: dict[str, Any],
        enrichment_results: dict[str, Any],
    ) -> dict[str, Any]:
        medical = enrichment_results.get(
            "medical_evidence",
            {},
        )

        claims = enrichment_results.get(
            "claims_evidence",
            {},
        )

        coverage_gaps = enrichment_results.get(
            "coverage_gaps",
            [],
        )

        conditions = self._get_list(
            medical,
            "conditions",
        )

        medications = self._get_list(
            medical,
            "medications",
        )

        hospitalizations = self._get_list(
            medical,
            "hospitalizations",
        )

        claim_records = self._get_claim_records(
            claims
        )

        age = applicant_profile.get(
            "age",
            0,
        )

        return {
            "age": age,
            "condition_count": len(conditions),
            "medication_count": len(medications),
            "hospitalization_count": len(
                hospitalizations
            ),
            "claim_count": len(claim_records),
            "coverage_gap_count": len(
                coverage_gaps
            ),
            "has_chronic_condition": self._has_chronic_condition(
                conditions
            ),
            "has_major_procedure": self._has_major_procedure(
                hospitalizations
            ),
            "has_multiple_claims": len(
                claim_records
            ) >= 3,
            "has_multiple_conditions": len(
                conditions
            ) >= 3,
        }

    def _rule_based_complexity(
        self,
        features: dict[str, Any],
    ) -> ComplexityLevel | None:
        complexity_score = 0

        if features["age"] >= 60:
            complexity_score += 2
        elif features["age"] >= 50:
            complexity_score += 1

        if features["condition_count"] >= 3:
            complexity_score += 3
        elif features["condition_count"] >= 2:
            complexity_score += 2
        elif features["condition_count"] == 1:
            complexity_score += 1

        if features["has_chronic_condition"]:
            complexity_score += 1

        if features["medication_count"] >= 5:
            complexity_score += 2
        elif features["medication_count"] >= 3:
            complexity_score += 1

        if features["hospitalization_count"] >= 2:
            complexity_score += 2
        elif features["hospitalization_count"] == 1:
            complexity_score += 1

        if features["claim_count"] >= 5:
            complexity_score += 3
        elif features["claim_count"] >= 3:
            complexity_score += 2
        elif features["claim_count"] >= 1:
            complexity_score += 1

        if features["coverage_gap_count"] >= 2:
            complexity_score += 2
        elif features["coverage_gap_count"] == 1:
            complexity_score += 1

        if features["has_major_procedure"]:
            complexity_score += 2

        if complexity_score >= 8:
            return "complex"

        if complexity_score >= 3:
            return "standard"

        if complexity_score >= 0:
            return "simple"

        return None

    def _llm_complexity(
        self,
        features: dict[str, Any],
    ) -> ComplexityLevel:
        prompt = f"""
Classify this medical insurance underwriting case.

Choose exactly one:
simple
standard
complex

Case features:
{features}

Guidance:
- simple: low medical complexity, limited history,
  and little evidence requiring cross-domain reasoning.
- standard: one or more meaningful risk factors requiring
  normal underwriting analysis.
- complex: multiple conditions, significant medical history,
  repeated claims, major procedures, substantial coverage
  gaps, or conflicting evidence.

Return only:
complexity=<simple|standard|complex>
"""

        response = self.llm.invoke(prompt)
        content = response.content.strip().lower()

        for level in (
            "complex",
            "standard",
            "simple",
        ):
            if f"complexity={level}" in content:
                return level

        return "standard"

    @staticmethod
    def _select_strategy(
        complexity: ComplexityLevel,
    ) -> str:
        if complexity == "simple":
            return "plan_and_execute"

        if complexity == "standard":
            return "plan_and_execute"

        return "tree_of_thought"

    @staticmethod
    def _build_reasons(
        features: dict[str, Any],
        complexity: ComplexityLevel,
    ) -> list[str]:
        reasons = []

        if features["age"] >= 60:
            reasons.append(
                "Applicant age is 60 or above."
            )
        elif features["age"] >= 50:
            reasons.append(
                "Applicant age is 50 or above."
            )

        if features["has_multiple_conditions"]:
            reasons.append(
                "Multiple medical conditions are present."
            )

        elif features["condition_count"] == 1:
            reasons.append(
                "A medical condition is present."
            )

        if features["has_chronic_condition"]:
            reasons.append(
                "Chronic medical condition identified."
            )

        if features["medication_count"] >= 5:
            reasons.append(
                "Multiple medications require consideration."
            )

        if features["hospitalization_count"] >= 2:
            reasons.append(
                "Multiple hospitalization events are present."
            )

        elif features["hospitalization_count"] == 1:
            reasons.append(
                "Previous hospitalization is present."
            )

        if features["has_multiple_claims"]:
            reasons.append(
                "Multiple historical claims are present."
            )

        if features["coverage_gap_count"] > 0:
            reasons.append(
                "Coverage gap evidence requires review."
            )

        if features["has_major_procedure"]:
            reasons.append(
                "Major medical procedure requires additional assessment."
            )

        if not reasons:
            reasons.append(
                "Limited risk factors were identified."
            )

        reasons.append(
            f"Case classified as {complexity}."
        )

        return reasons

    @staticmethod
    def _get_list(
        source: Any,
        key: str,
    ) -> list[Any]:
        if isinstance(source, list):
            items = []
            for item in source:
                if isinstance(item, dict) and key in item:
                    val = item[key]
                    if isinstance(val, list):
                        items.extend(val)
                    else:
                        items.append(val)
            return items

        if isinstance(source, dict):
            value = source.get(key, [])
            return value if isinstance(value, list) else []

        return []

    @staticmethod
    def _get_claim_records(
        claims: Any,
    ) -> list[Any]:
        if isinstance(claims, list):
            return claims

        if isinstance(claims, dict):
            for key in (
                "claims",
                "claim_records",
                "records",
            ):
                value = claims.get(key)
                if isinstance(value, list):
                    return value

        return []

    @staticmethod
    def _has_chronic_condition(
        conditions: list[Any],
    ) -> bool:
        chronic_terms = {
            "diabetes",
            "hypertension",
            "rheumatoid",
            "arthritis",
            "asthma",
            "coronary",
            "cardiac",
            "dyslipidemia",
            "hypothyroidism",
            "chronic",
        }

        condition_text = " ".join(
            str(condition).lower()
            for condition in conditions
        )

        return any(
            term in condition_text
            for term in chronic_terms
        )

    @staticmethod
    def _has_major_procedure(
        hospitalizations: list[Any],
    ) -> bool:
        procedure_terms = {
            "angioplasty",
            "stent",
            "surgery",
            "transplant",
            "bypass",
            "replacement",
            "cholecystectomy",
            "lithotripsy",
        }

        hospitalization_text = " ".join(
            str(item).lower()
            for item in hospitalizations
        )

        return any(
            term in hospitalization_text
            for term in procedure_terms
        )


complexity_router = ComplexityRouter()