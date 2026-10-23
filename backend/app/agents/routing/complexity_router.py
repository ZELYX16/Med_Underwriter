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
    ) -> dict[str, Any]:
        conditions = self._extract_conditions(
            applicant_profile,
            enrichment_results,
        )

        condition_count = len(conditions)

        red_flags = self._find_red_flags(
            conditions
        )

        reasons: list[str] = []

        if condition_count <= 2:
            complexity_level = "standard"
            routing_strategy = "plan_and_execute"

            if condition_count == 0:
                reasons.append(
                    "No active medical conditions identified."
                )
            else:
                reasons.append(
                    f"{condition_count} medical condition(s) identified."
                )

        else:
            complexity_level = "complex"
            routing_strategy = "tree_of_thought"
            reasons.append(
                f"{condition_count} medical conditions identified."
            )

        if red_flags:
            complexity_level = "complex"
            routing_strategy = "tree_of_thought"
            reasons.append(
                "High-risk medical indicators require "
                "deeper reasoning."
            )

        if self._has_conflicting_evidence(
            enrichment_results
        ):
            complexity_level = "complex"
            routing_strategy = "tree_of_thought"
            reasons.append(
                "Conflicting evidence requires "
                "additional analysis."
            )

        # No conditions and no red flags / conflicts: nothing to reason
        # about, so Agent 2 can use its deterministic rationale.
        if condition_count == 0 and complexity_level == "standard":
            complexity_level = "simple"

        return {
            "complexity_level": complexity_level,
            "complexity_reasons": reasons,
            "routing_strategy": routing_strategy,
            "condition_count": condition_count,
            "conditions": conditions,
            "red_flags": red_flags,
        }

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