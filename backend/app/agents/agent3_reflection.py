from typing import Any

from app.llm.factory import get_llm


class ReflectionAgent:
    PERSONAS = [
        "medical_accuracy",
        "actuarial_soundness",
        "regulatory_compliance",
        "fairness",
        "explainability",
    ]

    MAX_REFLECTION_ROUNDS = 2

    def __init__(self):
        self.llm = get_llm(
            role="reflection",
            temperature=0.0,
        )

    def run(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
        risk_result: dict[str, Any],
    ) -> dict[str, Any]:
        confidence = float(
            risk_result.get(
                "confidence",
                0.0,
            )
            or 0.0
        )

        risk_assessment = risk_result.get(
            "risk_assessment",
            {},
        )

        overall_risk = float(
            risk_assessment.get(
                "overall_risk_score",
                0.0,
            )
            or 0.0
        )

        reflection_required = (
            confidence < 0.75
            or overall_risk >= 60
            or risk_result.get(
                "recommendation"
            )
            == "human_review"
        )

        if not reflection_required:
            return self._build_no_reflection_result(
                risk_result
            )

        personas = self._select_personas(
            confidence=confidence,
            overall_risk=overall_risk,
            enrichment_results=enrichment_results,
        )

        findings = []

        for round_number in range(
            1,
            self.MAX_REFLECTION_ROUNDS + 1,
        ):
            round_findings = self._run_reflection_round(
                round_number=round_number,
                personas=personas,
                applicant_profile=applicant_profile,
                submission=submission,
                enrichment_results=enrichment_results,
                risk_result=risk_result,
            )

            findings.extend(round_findings)

            if not self._needs_another_round(
                round_findings
            ):
                break

        checks = self._build_checks(
            findings
        )

        verdict = self._determine_verdict(
            findings=findings,
            risk_result=risk_result,
        )

        human_review_required = (
            verdict in {
                "fail",
                "escalate",
            }
            or confidence < 0.60
        )

        return {
            "reflection_required": True,
            "reflection_type": "multi_persona",
            "reflection_personas": personas,
            "reflection_round": min(
                self.MAX_REFLECTION_ROUNDS,
                max(
                    (
                        finding.get(
                            "round",
                            1,
                        )
                        for finding in findings
                    ),
                    default=1,
                ),
            ),
            "reflection_findings": findings,
            "medical_accuracy_check": checks[
                "medical_accuracy"
            ],
            "actuarial_soundness_check": checks[
                "actuarial_soundness"
            ],
            "regulatory_compliance_check": checks[
                "regulatory_compliance"
            ],
            "fairness_check": checks[
                "fairness"
            ],
            "explainability_check": checks[
                "explainability"
            ],
            "reflection_verdict": verdict,
            "require_human_review": human_review_required,
            "human_review_reason": self._human_review_reason(
                verdict,
                findings,
            ),
            "advisory": self._build_advisory(
                verdict,
                findings,
                risk_result,
            ),
        }

    def _run_reflection_round(
        self,
        round_number: int,
        personas: list[str],
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
        risk_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        findings = []

        for persona in personas:
            finding = self._evaluate_persona(
                round_number=round_number,
                persona=persona,
                applicant_profile=applicant_profile,
                submission=submission,
                enrichment_results=enrichment_results,
                risk_result=risk_result,
            )

            findings.append(finding)

        return findings

    def _evaluate_persona(
        self,
        round_number: int,
        persona: str,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
        risk_result: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = f"""
You are performing a safety reflection for a medical
insurance underwriting decision-support system.

Reflection persona:
{persona}

Applicant:
{applicant_profile}

Submission:
{submission}

Evidence:
{enrichment_results}

Proposed risk assessment:
{risk_result}

Evaluate only from the perspective of your assigned
persona.

Do not invent missing evidence.
Do not make a new medical diagnosis.
Do not create regulatory requirements.
Do not assume unsupported pricing rules.

Return exactly:

verdict=<pass|concern|fail>
finding=<short finding>
evidence=<evidence supporting the finding>
action=<recommended corrective action>

Persona guidance:

medical_accuracy:
Check whether medical reasoning is supported by the
available medical evidence.

actuarial_soundness:
Check whether risk and pricing reasoning is internally
consistent and whether unsupported actuarial assumptions
are being made.

regulatory_compliance:
Check whether regulatory claims are supported by the
retrieved regulatory evidence.

fairness:
Check whether the recommendation relies improperly on
protected or irrelevant demographic characteristics.

explainability:
Check whether the recommendation can be explained using
the evidence provided.
"""

        response = self.llm.invoke(prompt)

        parsed = self._parse_response(
            response.content
        )

        return {
            "round": round_number,
            "persona": persona,
            "verdict": parsed["verdict"],
            "finding": parsed["finding"],
            "evidence": parsed["evidence"],
            "action": parsed["action"],
        }

    def _select_personas(
        self,
        confidence: float,
        overall_risk: float,
        enrichment_results: dict[str, Any],
    ) -> list[str]:
        personas = [
            "medical_accuracy",
            "regulatory_compliance",
            "explainability",
        ]

        if overall_risk >= 45:
            personas.append(
                "actuarial_soundness"
            )

        if confidence < 0.75:
            personas.append(
                "fairness"
            )

        return personas

    @staticmethod
    def _needs_another_round(
        findings: list[dict[str, Any]],
    ) -> bool:
        return any(
            finding.get("verdict")
            in {
                "concern",
                "fail",
            }
            for finding in findings
        )

    @staticmethod
    def _build_checks(
        findings: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        checks = {}

        for persona in ReflectionAgent.PERSONAS:
            persona_findings = [
                finding
                for finding in findings
                if finding.get("persona")
                == persona
            ]

            if not persona_findings:
                checks[persona] = {
                    "status": "not_run",
                    "findings": [],
                }
                continue

            verdicts = [
                finding.get(
                    "verdict"
                )
                for finding in persona_findings
            ]

            if "fail" in verdicts:
                status = "fail"
            elif "concern" in verdicts:
                status = "concern"
            else:
                status = "pass"

            checks[persona] = {
                "status": status,
                "findings": persona_findings,
            }

        return checks

    @staticmethod
    def _determine_verdict(
        findings: list[dict[str, Any]],
        risk_result: dict[str, Any],
    ) -> str:
        if any(
            finding.get("verdict") == "fail"
            for finding in findings
        ):
            return "fail"

        concern_count = sum(
            finding.get("verdict") == "concern"
            for finding in findings
        )

        if concern_count >= 2:
            return "escalate"

        if concern_count == 1:
            return "review"

        return "pass"

    @staticmethod
    def _human_review_reason(
        verdict: str,
        findings: list[dict[str, Any]],
    ) -> str:
        if verdict == "fail":
            return (
                "Reflection identified a critical "
                "issue requiring human underwriting review."
            )

        if verdict == "escalate":
            return (
                "Multiple reflection concerns require "
                "human underwriting review."
            )

        if verdict == "review":
            return (
                "A reflection concern was identified "
                "and should be reviewed."
            )

        return ""

    @staticmethod
    def _build_advisory(
        verdict: str,
        findings: list[dict[str, Any]],
        risk_result: dict[str, Any],
    ) -> dict[str, Any]:
        actions = [
            finding.get("action")
            for finding in findings
            if finding.get("action")
        ]

        return {
            "verdict": verdict,
            "recommended_actions": actions,
            "original_recommendation": risk_result.get(
                "recommendation"
            ),
            "original_confidence": risk_result.get(
                "confidence"
            ),
        }

    @staticmethod
    def _parse_response(
        response: str,
    ) -> dict[str, str]:
        parsed = {
            "verdict": "concern",
            "finding": "",
            "evidence": "",
            "action": "",
        }

        for line in response.splitlines():
            line = line.strip()

            if "=" not in line:
                continue

            key, value = line.split(
                "=",
                1,
            )

            key = key.strip().lower()
            value = value.strip()

            if key in parsed:
                parsed[key] = value

        if parsed["verdict"] not in {
            "pass",
            "concern",
            "fail",
        }:
            parsed["verdict"] = "concern"

        return parsed

    @staticmethod
    def _build_no_reflection_result(
        risk_result: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "reflection_required": False,
            "reflection_type": "none",
            "reflection_personas": [],
            "reflection_round": 0,
            "reflection_findings": [],
            "medical_accuracy_check": {
                "status": "not_required",
                "findings": [],
            },
            "actuarial_soundness_check": {
                "status": "not_required",
                "findings": [],
            },
            "regulatory_compliance_check": {
                "status": "not_required",
                "findings": [],
            },
            "fairness_check": {
                "status": "not_required",
                "findings": [],
            },
            "explainability_check": {
                "status": "not_required",
                "findings": [],
            },
            "reflection_verdict": "not_required",
            "require_human_review": False,
            "human_review_reason": "",
            "advisory": {
                "verdict": "not_required",
                "recommended_actions": [],
                "original_recommendation": risk_result.get(
                    "recommendation"
                ),
                "original_confidence": risk_result.get(
                    "confidence"
                ),
            },
        }


reflection_agent = ReflectionAgent()