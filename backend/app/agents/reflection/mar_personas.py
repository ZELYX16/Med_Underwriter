from typing import Any


class ReflectionPersona:
    def __init__(
        self,
        name: str,
        objective: str,
        checks: list[str],
    ):
        self.name = name
        self.objective = objective
        self.checks = checks

    def build_prompt(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        evidence: dict[str, Any],
        risk_result: dict[str, Any],
    ) -> str:
        checks = "\n".join(
            f"- {check}"
            for check in self.checks
        )

        return f"""
You are the {self.name} reviewer in a
multi-agent medical insurance underwriting system.

Objective:
{self.objective}

Review these areas:
{checks}

Applicant:
{applicant_profile}

Submission:
{submission}

Available evidence:
{evidence}

Proposed risk assessment:
{risk_result}

Review rules:
- Use only the supplied evidence.
- Do not invent facts.
- Do not create medical diagnoses.
- Do not invent regulations or policy terms.
- Clearly identify unsupported assumptions.
- Recommend human review when the evidence is insufficient.

Return:

verdict=<pass|concern|fail>
finding=<short finding>
evidence=<supporting evidence>
action=<recommended action>
"""


class MedicalReviewer(ReflectionPersona):
    def __init__(self):
        super().__init__(
            name="Medical Accuracy Reviewer",
            objective=(
                "Verify that the medical interpretation "
                "is consistent with the available clinical "
                "evidence."
            ),
            checks=[
                "diagnoses and medical conditions",
                "medication interpretation",
                "hospitalization history",
                "procedures and clinical events",
                "medical risk reasoning",
            ],
        )


class ActuarialReviewer(ReflectionPersona):
    def __init__(self):
        super().__init__(
            name="Actuarial Soundness Reviewer",
            objective=(
                "Check whether the risk assessment and "
                "pricing logic are internally consistent "
                "and supported by approved evidence."
            ),
            checks=[
                "risk score consistency",
                "risk factor weighting",
                "loading rationale",
                "premium calculation",
                "unsupported actuarial assumptions",
            ],
        )


class RegulatoryReviewer(ReflectionPersona):
    def __init__(self):
        super().__init__(
            name="Regulatory Compliance Reviewer",
            objective=(
                "Verify that regulatory conclusions are "
                "supported by the applicable regulatory "
                "evidence."
            ),
            checks=[
                "jurisdiction",
                "IRDAI requirements",
                "regulatory evidence",
                "compliance reasoning",
                "unsupported regulatory claims",
            ],
        )


class FairnessReviewer(ReflectionPersona):
    def __init__(self):
        super().__init__(
            name="Fairness Reviewer",
            objective=(
                "Check whether the underwriting recommendation "
                "relies on legitimate risk evidence rather "
                "than irrelevant demographic characteristics."
            ),
            checks=[
                "relevance of demographic attributes",
                "medical evidence versus demographic assumptions",
                "consistent treatment of comparable risk",
                "unsupported bias",
                "explainable risk factors",
            ],
        )


class ExplainabilityReviewer(ReflectionPersona):
    def __init__(self):
        super().__init__(
            name="Explainability Reviewer",
            objective=(
                "Verify that the proposed underwriting "
                "recommendation can be clearly explained "
                "using traceable evidence."
            ),
            checks=[
                "evidence-to-decision traceability",
                "decision rationale",
                "risk factor explanation",
                "pricing explanation",
                "missing evidence",
            ],
        )


class MARPersonaRegistry:
    def __init__(self):
        self._personas = {
            "medical_accuracy": MedicalReviewer(),
            "actuarial_soundness": ActuarialReviewer(),
            "regulatory_compliance": RegulatoryReviewer(),
            "fairness": FairnessReviewer(),
            "explainability": ExplainabilityReviewer(),
        }

    def get(
        self,
        name: str,
    ) -> ReflectionPersona:
        if name not in self._personas:
            raise ValueError(
                f"Unknown reflection persona: {name}"
            )

        return self._personas[name]

    def get_many(
        self,
        names: list[str],
    ) -> list[ReflectionPersona]:
        return [
            self.get(name)
            for name in names
        ]

    def all(
        self,
    ) -> list[ReflectionPersona]:
        return list(
            self._personas.values()
        )

    def names(self) -> list[str]:
        return list(
            self._personas.keys()
        )


mar_personas = MARPersonaRegistry()