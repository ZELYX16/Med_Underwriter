from __future__ import annotations

import time
from typing import Any

from app.agents.reflection.constitutional import (
    constitutional_checker,
)
from app.agents.reflection.llm_critic import llm_critic
from app.config import settings
from app.agents.reflection.mar_personas import (
    mar_personas,
)


class ReflectionAgent:
    MAX_REFLECTION_ROUNDS = 3

    def run(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        enrichment_results: dict[str, Any],
        risk_result: dict[str, Any],
        previous_findings: list[dict[str, Any]] | None = None,
        complexity_level: str = "",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        confidence = float(
            risk_result.get(
                "agent2_confidence",
                risk_result.get("confidence", 0.0),
            )
            or 0.0
        )
        previous_findings = previous_findings or []

        risk_assessment = risk_result.get(
            "risk_assessment",
            {},
        )

        pricing_result = risk_result.get(
            "pricing_result",
            {},
        )

        recommendation = risk_result.get(
            "agent2_recommendation",
            risk_result.get("recommendation", ""),
        )

        evidence = enrichment_results or {}

        constitutional = constitutional_checker.check(
            applicant_profile=applicant_profile,
            risk_assessment=risk_assessment,
            pricing_result=pricing_result,
            recommendation=recommendation,
            evidence=evidence,
        )

        flag_count = sum(
            1
            for result in constitutional.values()
            if result.get("status") == "flag"
        )

        reflection_type = self._select_reflection_type(
            confidence=confidence,
            flag_count=flag_count,
            risk_assessment=risk_assessment,
        )

        # Agent 3 always performs an actual critique.
        # "lightweight" means a smaller critique, not no critique.
        # This keeps Agent 3 as the mandatory quality gate for every case.
        personas = self._select_personas(
            reflection_type=reflection_type,
            constitutional=constitutional,
        )

        findings: list[dict[str, Any]] = []
        reflection_round = 1
        final_mar: dict[str, Any] = {}

        max_rounds = (
            1
            if reflection_type == "lightweight"
            else self.MAX_REFLECTION_ROUNDS
        )

        while reflection_round <= max_rounds:
            mar_result = mar_personas.review(
                applicant_profile=applicant_profile,
                risk_assessment=risk_assessment,
                pricing_result=pricing_result,
                recommendation=recommendation,
                evidence=evidence,
                selected_personas=personas,
                previous_findings=previous_findings,
            )

            round_findings = self._convert_mar_findings(
                round_number=reflection_round,
                mar_result=mar_result,
            )

            findings.extend(round_findings)
            previous_findings = round_findings
            final_mar = mar_result

            if mar_result.get("consensus"):
                break

            reflection_round += 1

        if reflection_round > max_rounds:
            reflection_round = max_rounds

        # LLM critique: only where it earns its cost (complex or high-risk).
        critique: dict[str, Any] | None = None
        if settings.reflection_llm_enabled and (
            reflection_type == "full_mar" or complexity_level == "complex"
        ):
            critique = llm_critic.critique(
                applicant_profile=applicant_profile,
                risk_assessment=risk_assessment,
                pricing_result=pricing_result,
                recommendation=recommendation,
                reasoning=str(risk_result.get("agent2_reasoning", "")),
                rule_concerns=[
                    str(f.get("finding", ""))
                    for f in findings
                    if f.get("verdict") != "pass"
                ],
            )
            if critique.get("ok"):
                for concern in critique["concerns"]:
                    findings.append(
                        {
                            "round": reflection_round,
                            "persona": concern["persona"],
                            "verdict": "concern",
                            "finding": concern["issue"],
                            "evidence": [
                                "LLM critique of the decision and rationale"
                            ],
                            "action": concern["action"],
                            "source": "llm",
                        }
                    )
        llm_disagrees = bool(
            critique
            and critique.get("ok")
            and critique["verdict"] == "disagree"
        )

        verdict = self._determine_verdict(
            mar_result=final_mar,
            constitutional=constitutional,
            flag_count=flag_count,
        )
        if llm_disagrees and verdict == "pass":
            verdict = "review"

        constitutional_flag = flag_count > 0
        mar_failed = str(
            final_mar.get("verdict", "")
        ).strip().lower() in {"fail", "failed"}

        require_human_review = (
            constitutional_flag
            or llm_disagrees
            or mar_failed
            or (
                reflection_round >= self.MAX_REFLECTION_ROUNDS
                and not final_mar.get("consensus", False)
            )
            or verdict in {"escalate", "fail"}
        )

        requires_rescore = (
            bool(final_mar.get("requires_rescore"))
            and not require_human_review
        )

        human_reason = self._human_review_reason(
            verdict=verdict,
            findings=findings,
            consensus=final_mar.get("consensus", False),
        )
        if llm_disagrees:
            human_reason = (
                "LLM critique disagrees with the recommendation: "
                + "; ".join(c["issue"] for c in critique["concerns"][:2])
                if critique["concerns"]
                else "LLM critique disagrees with the recommendation."
            )

        checks = self._build_checks(
            constitutional=constitutional,
            findings=findings,
        )

        # Rules/personas use no tokens; the LLM critique (complex or
        # high-risk cases only) reports its own usage.
        critique_metrics = critique["metrics"] if critique else {}
        metrics = {
            "latency_sec": round(time.perf_counter() - started, 4),
            "llm_latency_sec": critique_metrics.get("llm_latency_sec", 0.0),
            "input_tokens": critique_metrics.get("input_tokens", 0),
            "output_tokens": critique_metrics.get("output_tokens", 0),
            "total_tokens": critique_metrics.get("total_tokens", 0),
            "token_source": critique_metrics.get("token_source", "none"),
            "llm_used": bool(critique_metrics.get("llm_used", False)),
        }
        if critique and not critique.get("ok"):
            metrics["error"] = critique.get("error", "critique_failed")

        return {
            "reflection_required": True,
            "metrics": metrics,
            "agent3_metrics": metrics,
            "reflection_type": reflection_type,
            "reflection_personas": personas,
            "reflection_round": reflection_round,
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
            "fairness_check": checks["fairness"],
            "explainability_check": checks[
                "explainability"
            ],

            "constitutional_medical_accuracy": constitutional.get(
                "medical_accuracy",
                {},
            ),
            "constitutional_actuarial_soundness": constitutional.get(
                "actuarial_soundness",
                {},
            ),
            "constitutional_regulatory_compliance": constitutional.get(
                "regulatory_compliance",
                {},
            ),
            "constitutional_fairness": constitutional.get(
                "fairness",
                {},
            ),
            "constitutional_explainability": constitutional.get(
                "explainability",
                {},
            ),

            "reflection_verdict": verdict,
            "require_human_review": require_human_review,
            "require_human_escalation": require_human_review,
            "human_review_reason": human_reason,

            "requires_rescore": requires_rescore,
            "advisory": {
                "verdict": verdict,
                "consensus": final_mar.get(
                    "consensus",
                    False,
                ),
                "disagreements": final_mar.get(
                    "disagreements",
                    [],
                ),
                "recommended_actions": [
                    finding.get("action", "")
                    for finding in findings
                    if finding.get("action")
                ],
                "original_recommendation": recommendation,
                "original_confidence": confidence,
            },
        }

    @staticmethod
    def _select_reflection_type(
        confidence: float,
        flag_count: int,
        risk_assessment: dict[str, Any],
    ) -> str:
        medical_risk_score = float(
            risk_assessment.get(
                "medical_risk_score",
                0.0,
            )
            or 0.0
        )

        overall_risk_score = float(
            risk_assessment.get(
                "overall_risk_score",
                0.0,
            )
            or 0.0
        )

        risk_factors = risk_assessment.get(
            "risk_factors",
            [],
        )

        high_risk_factor = any(
            any(
                keyword in str(factor).lower()
                for keyword in (
                    "myocardial infarction",
                    "heart attack",
                    "coronary artery disease",
                    "cad",
                    "major cardiac",
                    "cancer",
                    "malignancy",
                    "organ failure",
                    "transplant",
                )
            )
            for factor in risk_factors
        )

        if (
            medical_risk_score >= 80
            or overall_risk_score >= 70
            or high_risk_factor
            or flag_count >= 2
        ):
            return "full_mar"

        if (
            confidence >= 0.85
            and flag_count == 0
            and medical_risk_score < 60
            and overall_risk_score < 60
        ):
            return "lightweight"

        if 0.70 <= confidence < 0.85:
            return "targeted"

        if confidence < 0.70:
            return "full_mar"

        return "targeted"

    @staticmethod
    def _select_personas(
        reflection_type: str,
        constitutional: dict[str, Any],
    ) -> list[str]:
        if reflection_type == "full_mar":
            return [
                "medical_expert",
                "actuary",
                "compliance_officer",
                "customer_advocate",
            ]

        personas = []

        mapping = {
            "medical_accuracy": "medical_expert",
            "actuarial_soundness": "actuary",
            "regulatory_compliance": "compliance_officer",
            "fairness": "customer_advocate",
            "explainability": "customer_advocate",
        }

        for principle, persona in mapping.items():
            result = constitutional.get(
                principle,
                {},
            )

            if result.get("status") == "flag":
                if persona not in personas:
                    personas.append(persona)

        if not personas:
            personas = [
                "medical_expert",
                "customer_advocate",
            ]

        return personas

    @staticmethod
    def _convert_mar_findings(
        round_number: int,
        mar_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        findings = []

        persona_outputs = mar_result.get(
            "persona_outputs",
            {},
        )

        for persona, output in persona_outputs.items():
            verdict = output.get(
                "verdict",
                "flag",
            )

            if verdict == "pass":
                normalized = "pass"
            elif verdict == "flag":
                normalized = "concern"
            else:
                normalized = "fail"

            concerns = output.get(
                "concerns",
                [],
            )

            findings.append(
                {
                    "round": round_number,
                    "persona": persona,
                    "verdict": normalized,
                    "finding": (
                        output.get("reasoning")
                        or "; ".join(concerns)
                    ),
                    "evidence": (
                        concerns
                        if concerns
                        else [
                            "Review completed using "
                            "available evidence."
                        ]
                    ),
                    "action": (
                        "Re-score the underwriting assessment."
                        if normalized != "pass"
                        else ""
                    ),
                }
            )

        return findings

    @staticmethod
    def _determine_verdict(
        mar_result: dict[str, Any],
        constitutional: dict[str, Any],
        flag_count: int,
    ) -> str:
        if flag_count >= 2:
            return "escalate"

        if not mar_result:
            return "review"

        mar_verdict = str(
            mar_result.get("verdict", "")
        ).strip().lower()

        if mar_verdict in {"fail", "failed"}:
            return "fail"

        if mar_verdict == "escalate":
            return "escalate"

        if mar_result.get("requires_rescore"):
            return "review"

        if flag_count == 1:
            return "review"

        if mar_result.get("consensus"):
            if mar_result.get("verdict") == "pass":
                return "pass"

            if mar_result.get("verdict") == "review":
                return "review"

        return "review"

    @staticmethod
    def _build_checks(
        constitutional: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        checks: dict[str, dict[str, Any]] = {}

        principles = [
            "medical_accuracy",
            "actuarial_soundness",
            "regulatory_compliance",
            "fairness",
            "explainability",
        ]

        for principle in principles:
            constitutional_result = constitutional.get(
                principle,
                {},
            )

            principle_findings = [
                finding
                for finding in findings
                if finding.get("persona")
                in {
                    "medical_expert"
                    if principle == "medical_accuracy"
                    else "actuary"
                    if principle == "actuarial_soundness"
                    else "compliance_officer"
                    if principle == "regulatory_compliance"
                    else "customer_advocate"
                    if principle in {
                        "fairness",
                        "explainability",
                    }
                    else ""
                }
                and finding.get("verdict") != "pass"
            ]

            checks[principle] = {
                "status": constitutional_result.get(
                    "status",
                    "flag",
                ),
                "passed": constitutional_result.get(
                    "passed",
                    False,
                ),
                "reason": constitutional_result.get(
                    "reason",
                    "",
                ),
                "findings": principle_findings,
            }

        return checks

    @staticmethod
    def _lightweight_result(
        recommendation: str,
        confidence: float,
        constitutional: dict[str, Any],
    ) -> dict[str, Any]:
        flag_count = sum(
            1
            for result in constitutional.values()
            if result.get("status") == "flag"
        )

        verdict = "review" if flag_count else "pass"

        return {
            "reflection_required": True,
            "reflection_type": "lightweight",
            "reflection_personas": [],
            "reflection_round": 1,
            "reflection_findings": [],
            "medical_accuracy_check": constitutional.get(
                "medical_accuracy",
                {},
            ),
            "actuarial_soundness_check": constitutional.get(
                "actuarial_soundness",
                {},
            ),
            "regulatory_compliance_check": constitutional.get(
                "regulatory_compliance",
                {},
            ),
            "fairness_check": constitutional.get(
                "fairness",
                {},
            ),
            "explainability_check": constitutional.get(
                "explainability",
                {},
            ),
            "reflection_verdict": verdict,
            "require_human_review": False,
            "require_human_escalation": False,
            "human_review_reason": "",
            "requires_rescore": False,
            "advisory": {
                "verdict": verdict,
                "consensus": flag_count == 0,
                "disagreements": [],
                "recommended_actions": [],
                "original_recommendation": recommendation,
                "original_confidence": confidence,
            },
        }
    @staticmethod
    def _no_reflection_result(
        recommendation: str,
        confidence: float,
        constitutional: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "reflection_required": False,
            "reflection_type": "none",
            "reflection_personas": [],
            "reflection_round": 0,
            "reflection_findings": [],
            "medical_accuracy_check": constitutional.get(
                "medical_accuracy",
                {},
            ),
            "actuarial_soundness_check": constitutional.get(
                "actuarial_soundness",
                {},
            ),
            "regulatory_compliance_check": constitutional.get(
                "regulatory_compliance",
                {},
            ),
            "fairness_check": constitutional.get(
                "fairness",
                {},
            ),
            "explainability_check": constitutional.get(
                "explainability",
                {},
            ),
            "reflection_verdict": "not_required",
            "require_human_review": False,
            "require_human_escalation": False,
            "human_review_reason": "",
            "requires_rescore": False,
            "advisory": {
                "verdict": "not_required",
                "consensus": True,
                "disagreements": [],
                "recommended_actions": [],
                "original_recommendation": recommendation,
                "original_confidence": confidence,
            },
        }

    @staticmethod
    def _human_review_reason(
        verdict: str,
        findings: list[dict[str, Any]],
        consensus: bool,
    ) -> str:
        if verdict == "escalate":
            return (
                "Multiple constitutional or MAR concerns "
                "require senior underwriting review."
            )

        if not consensus:
            return (
                "MAR personas did not reach consensus within "
                "the maximum reflection rounds."
            )

        if findings:
            concerns = [
                finding.get("finding", "")
                for finding in findings
                if finding.get("verdict") != "pass"
                and finding.get("finding")
            ]

            if concerns:
                return concerns[0]

        if verdict == "review":
            return (
                "Reflection identified concerns requiring "
                "additional underwriting review."
            )

        return ""


reflection_agent = ReflectionAgent()