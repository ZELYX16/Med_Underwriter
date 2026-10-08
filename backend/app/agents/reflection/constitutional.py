from __future__ import annotations

from typing import Any


class ConstitutionalChecker:
    PRINCIPLES = (
        "medical_accuracy",
        "actuarial_soundness",
        "regulatory_compliance",
        "fairness",
        "explainability",
    )

    PROTECTED_ATTRIBUTES = {
        "gender",
        "sex",
        "religion",
        "race",
        "ethnicity",
        "caste",
        "marital_status",
        "nationality",
    }

    def check(
        self,
        applicant_profile: dict[str, Any],
        risk_assessment: dict[str, Any],
        pricing_result: dict[str, Any],
        recommendation: str,
        evidence: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        return {
            "medical_accuracy": self._medical_accuracy(
                applicant_profile,
                risk_assessment,
                evidence,
            ),
            "actuarial_soundness": self._actuarial_soundness(
                risk_assessment,
                pricing_result,
            ),
            "regulatory_compliance": self._regulatory_compliance(
                evidence,
            ),
            "fairness": self._fairness(
                applicant_profile,
                risk_assessment,
            ),
            "explainability": self._explainability(
                recommendation,
                risk_assessment,
                evidence,
            ),
        }

    def _medical_accuracy(
        self,
        applicant_profile: dict[str, Any],
        risk_assessment: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        risk_factors = risk_assessment.get("risk_factors", [])

        if not risk_factors:
            return self._result(
                True,
                "No medical risk factors were identified that require "
                "additional clinical grounding.",
            )

        medical_evidence = evidence.get("medical_evidence", [])
        claims_evidence = evidence.get("claims_evidence", [])

        applicant_age = applicant_profile.get("age")
        applicant_bmi = applicant_profile.get("bmi")

        medical_conditions = self._stringify_evidence(
            applicant_profile.get("medical_conditions", [])
        ).lower()

        medications = self._stringify_evidence(
            applicant_profile.get("medications", [])
        ).lower()

        hospitalizations = self._stringify_evidence(
            applicant_profile.get("hospitalizations", [])
        ).lower()

        medical_history = self._stringify_evidence(
            applicant_profile.get("medical_history", [])
        ).lower()

        medical_evidence_text = " ".join(
            self._stringify_evidence(item)
            for item in medical_evidence
        ).lower()

        grounding_text = " ".join(
            [
                medical_conditions,
                medications,
                hospitalizations,
                medical_history,
                medical_evidence_text,
            ]
        )

        unsupported: list[str] = []

        for factor in risk_factors:
            factor_text = str(factor).strip().lower()

            if not factor_text:
                continue

            grounded = False

            if "age" in factor_text:
                grounded = applicant_age is not None

            elif "bmi" in factor_text:
                grounded = applicant_bmi is not None

            elif "claim" in factor_text:
                grounded = bool(claims_evidence)

            elif "hospitalization" in factor_text:
                grounded = bool(hospitalizations)

            elif (
                "medication" in factor_text
                or "medications" in factor_text
            ):
                grounded = bool(medications)

            elif (
                "multiple chronic conditions" in factor_text
                or "multiple comorbid" in factor_text
            ):
                condition_values = applicant_profile.get(
                    "medical_conditions",
                    [],
                )

                condition_count = (
                    len(condition_values)
                    if isinstance(condition_values, list)
                    else 0
                )

                grounded = condition_count >= 2

            else:
                medical_terms = self._extract_medical_terms(
                    factor_text
                )

                if medical_terms:
                    grounded = any(
                        term in grounding_text
                        for term in medical_terms
                    )

                if not grounded:
                    factor_keywords = [
                        word
                        for word in factor_text
                        .replace(",", " ")
                        .replace("(", " ")
                        .replace(")", " ")
                        .replace(":", " ")
                        .split()
                        if len(word) >= 5
                    ]

                    grounded = bool(
                        factor_keywords
                        and any(
                            keyword in grounding_text
                            for keyword in factor_keywords
                        )
                    )

            if not grounded:
                unsupported.append(str(factor))

        if unsupported:
            return self._result(
                False,
                "Some risk factors could not be directly grounded in "
                "applicant-specific information or retrieved evidence: "
                + "; ".join(unsupported[:3]),
            )

        return self._result(
            True,
            "Risk factors are grounded in applicant-specific profile "
            "information or retrieved supporting evidence.",
        )

    @staticmethod
    def _extract_medical_terms(text: str) -> list[str]:
        medical_terms = (
            "diabetes",
            "t2dm",
            "hypertension",
            "htn",
            "cad",
            "cardiac",
            "heart",
            "asthma",
            "arthritis",
            "thyroid",
            "dyslipidemia",
            "obesity",
            "cancer",
            "malignancy",
            "kidney",
            "renal",
            "liver",
            "hepatic",
            "stroke",
            "neurological",
            "neuropathy",
            "copd",
            "asthma",
            "gerd",
            "ulcer",
            "fracture",
            "hernia",
            "stone",
            "calculi",
            "disc",
            "pain",
            "infection",
        )

        return [
            term
            for term in medical_terms
            if term in text
        ]

    @staticmethod
    def _stringify_evidence(value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(
                f"{key} "
                f"{ConstitutionalChecker._stringify_evidence(item)}"
                for key, item in value.items()
            )

        if isinstance(value, (list, tuple, set)):
            return " ".join(
                ConstitutionalChecker._stringify_evidence(item)
                for item in value
            )

        return str(value)

    def _actuarial_soundness(
        self,
        risk_assessment: dict[str, Any],
        pricing_result: dict[str, Any],
    ) -> dict[str, Any]:
        overall_risk = self._safe_float(
            risk_assessment.get("overall_risk_score")
        )

        medical_risk = self._safe_float(
            risk_assessment.get("medical_risk_score")
        )

        claims_risk = self._safe_float(
            risk_assessment.get("claims_risk_score")
        )

        coverage_gap = self._safe_float(
            risk_assessment.get("coverage_gap_score")
        )

        loading = self._safe_float(
            pricing_result.get("loading_percentage")
        )

        final_premium = self._safe_float(
            pricing_result.get("final_premium")
        )

        base_premium = self._safe_float(
            pricing_result.get("base_premium")
        )

        problems: list[str] = []

        for name, value in (
            ("overall risk score", overall_risk),
            ("medical risk score", medical_risk),
            ("claims risk score", claims_risk),
            ("coverage gap score", coverage_gap),
        ):
            if value is not None and not 0 <= value <= 100:
                problems.append(
                    f"{name} is outside the expected 0-100 range"
                )

        if loading is not None and loading < 0:
            problems.append(
                "loading percentage cannot be negative"
            )

        if (
            final_premium is not None
            and final_premium < 0
        ):
            problems.append(
                "final premium cannot be negative"
            )

        if (
            base_premium is not None
            and base_premium < 0
        ):
            problems.append(
                "base premium cannot be negative"
            )

        if (
            base_premium is not None
            and final_premium is not None
            and final_premium < base_premium
        ):
            problems.append(
                "final premium is lower than the base premium"
            )

        if problems:
            return self._result(
                False,
                "; ".join(problems),
            )

        return self._result(
            True,
            "Risk scores and pricing values remain within valid "
            "decision ranges and contain no internally invalid "
            "premium values.",
        )

    def _regulatory_compliance(
        self,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        regulatory_evidence = evidence.get(
            "regulatory_evidence",
            [],
        )

        if not regulatory_evidence:
            return self._result(
                False,
                "Regulatory evidence is missing for the underwriting "
                "decision.",
            )

        valid_evidence = [
            item
            for item in regulatory_evidence
            if self._stringify_evidence(item).strip()
        ]

        if not valid_evidence:
            return self._result(
                False,
                "Regulatory evidence was retrieved but contains no "
                "usable supporting content.",
            )

        regulatory_text = " ".join(
            self._stringify_evidence(item)
            for item in valid_evidence
        ).lower()

        india_indicators = (
            "irdai",
            "health insurance",
            "insurance act",
            "india",
            "indian",
        )

        has_relevant_india_context = any(
            indicator in regulatory_text
            for indicator in india_indicators
        )

        if not has_relevant_india_context:
            return self._result(
                False,
                "Regulatory evidence is available, but its jurisdiction "
                "or applicability to the Indian health-insurance decision "
                "could not be established from the retrieved evidence.",
            )

        return self._result(
            True,
            "Relevant regulatory evidence is available and contains "
            "Indian health-insurance regulatory context.",
        )

    def _fairness(
        self,
        applicant_profile: dict[str, Any],
        risk_assessment: dict[str, Any],
    ) -> dict[str, Any]:
        risk_factors = risk_assessment.get(
            "risk_factors",
            [],
        )

        risk_factor_text = " ".join(
            str(factor).lower()
            for factor in risk_factors
        )

        protected_used = sorted(
            attribute
            for attribute in self.PROTECTED_ATTRIBUTES
            if attribute in risk_factor_text
        )

        if protected_used:
            return self._result(
                False,
                "Protected demographic attributes appear to be used "
                "explicitly as risk factors: "
                + ", ".join(protected_used),
            )

        applicant_context = {
            key: value
            for key, value in applicant_profile.items()
            if key in self.PROTECTED_ATTRIBUTES
        }

        if applicant_context:
            return self._result(
                True,
                "Protected demographic attributes may exist in the "
                "applicant profile, but none were identified as explicit "
                "risk factors used in the underwriting assessment.",
            )

        return self._result(
            True,
            "No protected demographic attribute was identified as an "
            "explicit risk factor in the underwriting assessment.",
        )

    def _explainability(
        self,
        recommendation: str,
        risk_assessment: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        if not recommendation:
            return self._result(
                False,
                "Underwriting recommendation is missing.",
            )

        risk_score = risk_assessment.get(
            "overall_risk_score"
        )

        medical_score = risk_assessment.get(
            "medical_risk_score"
        )

        claims_score = risk_assessment.get(
            "claims_risk_score"
        )

        coverage_gap_score = risk_assessment.get(
            "coverage_gap_score"
        )

        if risk_score is None:
            return self._result(
                False,
                "Overall risk score is missing from the underwriting "
                "assessment.",
            )

        component_scores_present = any(
            score is not None
            for score in (
                medical_score,
                claims_score,
                coverage_gap_score,
            )
        )

        if not component_scores_present:
            return self._result(
                False,
                "No component risk scores are available to explain "
                "the underwriting recommendation.",
            )

        evidence_counts = {
            key: len(value)
            for key, value in evidence.items()
            if isinstance(value, list)
        }

        has_supporting_evidence = any(
            count > 0
            for count in evidence_counts.values()
        )

        if not has_supporting_evidence:
            return self._result(
                False,
                "No supporting evidence is available for the "
                "underwriting recommendation.",
            )

        risk_factors = risk_assessment.get(
            "risk_factors",
            [],
        )

        protective_factors = risk_assessment.get(
            "protective_factors",
            [],
        )

        coverage_gaps = risk_assessment.get(
            "coverage_gaps",
            [],
        )

        explanation_elements = []

        if risk_factors:
            explanation_elements.append(
                "identified risk factors"
            )

        if protective_factors:
            explanation_elements.append(
                "protective factors"
            )

        if coverage_gaps:
            explanation_elements.append(
                "coverage-gap findings"
            )

        if not explanation_elements:
            explanation_elements.append(
                "the available risk scores and supporting evidence"
            )

        return self._result(
            True,
            "Recommendation is explainable through "
            + ", ".join(explanation_elements)
            + ".",
        )

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _result(
        passed: bool,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "status": "pass" if passed else "flag",
            "passed": passed,
            "reason": reason,
        }


constitutional_checker = ConstitutionalChecker()