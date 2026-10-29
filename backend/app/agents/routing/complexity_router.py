from __future__ import annotations

from typing import Any


class ComplexityRouter:
    COMPLEXITY_THRESHOLDS = {
        "simple": 0,
        "standard": 2,
    }

    HIGH_RISK_KEYWORDS = {
        "myocardial infarction",
        "nstemi",
        "stroke",
        "cancer",
        "malignancy",
        "renal failure",
        "heart failure",
        "organ failure",
        "transplant",
        "severe copd",
    }

    def route(
        self,
        applicant_profile: dict[str, Any],
        enrichment_results: dict[str, Any],
        submission: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Weighted complexity score over explainable signals.

        score 0            -> simple   (deterministic rationale, no LLM)
        score < threshold  -> standard
        score >= threshold -> complex  (tree-of-thought, LLM critique)

        Hard rules still force "complex": any high-risk condition keyword,
        conflicting evidence, or three or more declared conditions,
        regardless of the score.
        """
        from app.config import settings

        submission = submission or {}
        conditions = self._extract_conditions(
            applicant_profile,
            enrichment_results,
        )
        condition_count = len(conditions)
        red_flags = self._find_red_flags(conditions)
        conflicting = self._has_conflicting_evidence(enrichment_results)

        breakdown: list[dict[str, Any]] = []

        def add(signal: str, points: int, detail: str) -> None:
            if points:
                breakdown.append(
                    {"signal": signal, "points": points, "detail": detail}
                )

        add(
            "conditions",
            min(condition_count, 4),
            f"{condition_count} medical condition(s) identified",
        )
        add(
            "high_risk_indicators",
            min(3 * len(red_flags), 6),
            f"High-risk indicator(s): {', '.join(red_flags)}",
        )
        add("conflicting_evidence", 2 if conflicting else 0, "Conflicting evidence")

        medical = applicant_profile.get("medical")
        medical = medical if isinstance(medical, dict) else {}

        claims = self._count(
            applicant_profile.get("claims") or submission.get("claims")
        )
        add(
            "claims",
            2 if claims >= 4 else 1 if claims >= 2 else 0,
            f"{claims} prior claim(s)",
        )

        hospitalizations = self._count(
            applicant_profile.get("hospitalizations")
            or medical.get("hospitalizations")
        )
        add(
            "hospitalizations",
            2 if hospitalizations >= 3 else 1 if hospitalizations else 0,
            f"{hospitalizations} hospitalization(s)",
        )

        medications = self._count(
            applicant_profile.get("medications") or medical.get("medications")
        )
        add(
            "medications",
            2 if medications >= 5 else 1 if medications >= 3 else 0,
            f"{medications} current medication(s)",
        )

        age = self._number(applicant_profile.get("age") or submission.get("age"))
        add(
            "age",
            2 if age >= 65 else 1 if age >= 50 else 0,
            f"Age {age:g}",
        )

        bmi = self._number(applicant_profile.get("bmi") or medical.get("bmi"))
        add(
            "bmi",
            1 if bmi and (bmi >= 35 or bmi < 17) else 0,
            f"BMI {bmi:g}",
        )

        smoker = applicant_profile.get("smoker")
        add(
            "smoker",
            1 if smoker in (True, "True", "true", "yes", "Yes", 1) else 0,
            "Declared smoker",
        )

        sum_insured = self._number(
            submission.get("sum_insured")
            or submission.get("requested_sum_insured")
        )
        add(
            "sum_insured",
            1 if sum_insured >= 2_500_000 and condition_count else 0,
            f"High sum insured ({sum_insured:,.0f}) with medical history",
        )

        score = sum(item["points"] for item in breakdown)
        threshold = max(1, int(settings.router_complex_threshold))

        if (
            red_flags
            or conflicting
            or condition_count >= 3
            or score >= threshold
        ):
            complexity_level = "complex"
            routing_strategy = "tree_of_thought"
        elif score == 0:
            complexity_level = "simple"
            routing_strategy = "plan_and_execute"
        else:
            complexity_level = "standard"
            routing_strategy = "plan_and_execute"

        reasons = [
            f"{item['detail']} (+{item['points']})" for item in breakdown
        ] or ["No complexity signals found (score 0)."]
        reasons.append(
            f"Complexity score {score} (complex at {threshold}+): "
            f"{complexity_level}."
        )

        return {
            "complexity_level": complexity_level,
            "complexity_reasons": reasons,
            "routing_strategy": routing_strategy,
            "complexity_score": score,
            "score_breakdown": breakdown,
            "condition_count": condition_count,
            "conditions": conditions,
            "red_flags": red_flags,
        }

    @staticmethod
    def _count(value: Any) -> int:
        return len(value) if isinstance(value, (list, tuple)) else 0

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0

    def _extract_conditions(
        self,
        applicant_profile: dict[str, Any],
        enrichment_results: dict[str, Any],
    ) -> list[str]:
        conditions: list[str] = []

        profile_conditions = applicant_profile.get(
            "medical_conditions",
            [],
        )

        if isinstance(profile_conditions, list):
            conditions.extend(
                str(condition).strip()
                for condition in profile_conditions
                if str(condition).strip()
            )
        elif profile_conditions:
            conditions.append(
                str(profile_conditions).strip()
            )

        medical = applicant_profile.get(
            "medical",
            {},
        )

        if isinstance(medical, dict):
            medical_conditions = medical.get(
                "conditions",
                [],
            )

            if isinstance(
                medical_conditions,
                list,
            ):
                conditions.extend(
                    str(condition).strip()
                    for condition in medical_conditions
                    if str(condition).strip()
                )

        medical_evidence = enrichment_results.get(
            "medical_evidence",
            [],
        )

        if isinstance(medical_evidence, list):
            for item in medical_evidence:
                if not isinstance(item, dict):
                    continue

                extracted = item.get(
                    "conditions",
                    [],
                )

                if isinstance(extracted, list):
                    conditions.extend(
                        str(condition).strip()
                        for condition in extracted
                        if str(condition).strip()
                    )

        return self._deduplicate(
            conditions
        )

    def _find_red_flags(
        self,
        conditions: list[str],
    ) -> list[str]:
        red_flags: list[str] = []

        for condition in conditions:
            normalized = condition.lower()

            for keyword in self.HIGH_RISK_KEYWORDS:
                if keyword in normalized:
                    red_flags.append(condition)
                    break

        return self._deduplicate(
            red_flags
        )

    @staticmethod
    def _has_conflicting_evidence(
        enrichment_results: dict[str, Any],
    ) -> bool:
        value = enrichment_results.get(
            "conflicting_evidence",
            False,
        )

        if isinstance(value, bool):
            return value

        conflicts = enrichment_results.get(
            "evidence_conflicts",
            [],
        )

        return bool(conflicts)

    @staticmethod
    def _deduplicate(
        values: list[str],
    ) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for value in values:
            normalized = value.lower()

            if normalized in seen:
                continue

            seen.add(normalized)
            result.append(value)

        return result


complexity_router = ComplexityRouter()