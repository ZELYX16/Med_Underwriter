from __future__ import annotations

from typing import Any


class MARPersonas:
    PERSONAS = {
        "medical_expert": (
            "Review clinical accuracy, medical evidence, "
            "conditions, treatments, and medical risk."
        ),
        "actuary": (
            "Review risk scoring, loading, pricing logic, "
            "and actuarial consistency."
        ),
        "compliance_officer": (
            "Review regulatory evidence, underwriting rules, "
            "and compliance concerns."
        ),
        "customer_advocate": (
            "Review fairness, explainability, proportionality, "
            "and unsupported demographic influence."
        ),
    }

    def review(
        self,
        applicant_profile: dict[str, Any],
        risk_assessment: dict[str, Any],
        pricing_result: dict[str, Any],
        recommendation: str,
        evidence: dict[str, Any],
        selected_personas: list[str] | None = None,
        previous_findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        outputs: dict[str, dict[str, Any]] = {}

        active_personas = (
            selected_personas
            if selected_personas
            else list(self.PERSONAS.keys())
        )

        for persona in active_personas:
            if persona not in self.PERSONAS:
                continue

            outputs[persona] = self._review_persona(
                persona=persona,
                focus=self.PERSONAS[persona],
                applicant_profile=applicant_profile,
                risk_assessment=risk_assessment,
                pricing_result=pricing_result,
                recommendation=recommendation,
                evidence=evidence,
                previous_findings=previous_findings or [],
            )

        synthesis = self._synthesize(outputs)

        return {
            "persona_outputs": outputs,
            "consensus": synthesis["consensus"],
            "verdict": synthesis["verdict"],
            "disagreements": synthesis["disagreements"],
            "requires_rescore": synthesis["requires_rescore"],
        }

    def _review_persona(
        self,
        persona: str,
        focus: str,
        applicant_profile: dict[str, Any],
        risk_assessment: dict[str, Any],
        pricing_result: dict[str, Any],
        recommendation: str,
        evidence: dict[str, Any],
        previous_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        concerns: list[str] = []
        previous_persona_findings = [
            finding.get("finding", "")
            for finding in previous_findings
            if finding.get("persona") == persona
            and finding.get("finding")
        ]

        previous_context = ""

        if previous_persona_findings:
            previous_context = (
                "Previous reflection finding was reconsidered: "
                + previous_persona_findings[-1]
            )
        if not evidence:
            concerns.append(
                "Insufficient evidence available for independent review."
            )

        if not risk_assessment:
            concerns.append(
                "Risk assessment is missing."
            )

        if not pricing_result:
            concerns.append(
                "Pricing assessment is missing."
            )

        if not recommendation:
            concerns.append(
                "Underwriting recommendation is missing."
            )

        # Evidence that was not retrieved is "unknown" (listed as a
        # verification item); it is not a concern about the decision.

        if persona == "actuary":
            risk_score = risk_assessment.get(
                "overall_risk_score"
            )

            if risk_score is None:
                concerns.append(
                    "Overall risk score is unavailable."
                )

        if persona == "medical_expert":
            # A serious condition without any grounding in the documents or
            # declarations would be a real concern; missing retrieval is not.
            assessments = risk_assessment.get("condition_assessments") or []
            for assessment in assessments:
                if assessment.get("tier") == "serious" and not assessment.get("reasons"):
                    concerns.append(
                        f"Serious condition '{assessment.get('label')}' has no stated basis."
                    )

        previous_concern_findings = [
            finding.get("finding", "")
            for finding in previous_findings
            if finding.get("persona") == persona
            and finding.get("verdict") in {
                "concern",
                "flag",
                "review",
            }
            and finding.get("finding")
        ]

        if previous_concern_findings and not concerns:
            concerns.append(
                "Previous reflection concern remains unresolved: "
                + previous_concern_findings[-1]
            )

        verdict = (
            "flag"
            if concerns
            else "pass"
        )

        return {
            "persona": persona,
            "focus": focus,
            "verdict": verdict,
            "concerns": concerns,
            "reasoning": (
                "Review identified one or more concerns."
                if concerns
                else "Review completed with no material concerns."
            ),
        }

    def _synthesize(
        self,
        outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        verdicts = [
            result.get("verdict", "flag")
            for result in outputs.values()
        ]

        passes = verdicts.count("pass")
        flags = verdicts.count("flag")

        disagreements: list[str] = []

        if passes and flags:
            disagreements.append(
                "Reflection personas did not reach unanimous consensus."
            )

        if flags >= 2:
            verdict = "escalate"
            requires_rescore = True
        elif flags == 1:
            verdict = "review"
            requires_rescore = True
        else:
            verdict = "pass"
            requires_rescore = False

        return {
            "consensus": len(set(verdicts)) == 1,
            "verdict": verdict,
            "disagreements": disagreements,
            "requires_rescore": requires_rescore,
        }


mar_personas = MARPersonas()