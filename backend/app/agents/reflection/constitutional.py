from typing import Any

from app.llm.factory import get_llm


class ConstitutionalChecker:
    CHECKS = {
        "medical_accuracy": (
            "Check whether medical reasoning is supported "
            "by the available medical evidence."
        ),
        "actuarial_soundness": (
            "Check whether risk and pricing reasoning is "
            "internally consistent and evidence-supported."
        ),
        "regulatory_compliance": (
            "Check whether regulatory statements are supported "
            "by the retrieved regulatory evidence."
        ),
        "fairness": (
            "Check whether irrelevant demographic or protected "
            "characteristics improperly influence the decision."
        ),
        "explainability": (
            "Check whether the recommendation can be explained "
            "using the evidence available in the case."
        ),
    }

    def __init__(self):
        self.llm = get_llm(
            role="reflection",
            temperature=0.0,
        )

    def check_all(
        self,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        evidence: dict[str, Any],
        risk_result: dict[str, Any],
    ) -> dict[str, Any]:
        results = {}

        for check_name, instruction in self.CHECKS.items():
            results[check_name] = self.check(
                check_name=check_name,
                instruction=instruction,
                applicant_profile=applicant_profile,
                submission=submission,
                evidence=evidence,
                risk_result=risk_result,
            )

        return results

    def check(
        self,
        check_name: str,
        instruction: str,
        applicant_profile: dict[str, Any],
        submission: dict[str, Any],
        evidence: dict[str, Any],
        risk_result: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = f"""
Perform a constitutional safety check for a medical
insurance underwriting decision-support system.

Check:
{check_name}

Requirement:
{instruction}

Applicant:
{applicant_profile}

Submission:
{submission}

Available evidence:
{evidence}

Proposed risk assessment:
{risk_result}

Rules:
- Use only the supplied evidence.
- Do not invent missing facts.
- Do not create medical diagnoses.
- Do not invent regulatory requirements.
- Do not assume undocumented pricing rules.
- Identify unsupported reasoning explicitly.
- For fairness, distinguish legitimate underwriting
  evidence from irrelevant demographic information.

Return exactly:

status=<pass|concern|fail>
finding=<short finding>
evidence=<supporting evidence>
recommendation=<corrective recommendation>
"""

        response = self.llm.invoke(prompt)

        return self._parse_response(
            response.content,
            check_name,
        )

    @staticmethod
    def _parse_response(
        response: str,
        check_name: str,
    ) -> dict[str, Any]:
        result = {
            "check": check_name,
            "status": "concern",
            "finding": "",
            "evidence": "",
            "recommendation": "",
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

            if key == "status":
                if value in {
                    "pass",
                    "concern",
                    "fail",
                }:
                    result["status"] = value

            elif key in {
                "finding",
                "evidence",
                "recommendation",
            }:
                result[key] = value

        return result


constitutional_checker = ConstitutionalChecker()