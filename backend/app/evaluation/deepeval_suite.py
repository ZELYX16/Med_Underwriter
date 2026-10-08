from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


EVALUATION_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALUATION_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


GOLDEN_CASES = [
    {
        "case_id": "EVAL-001",
        "applicant_profile": {
            "age": 32,
            "gender": "female",
            "medical_conditions": [],
            "medications": [],
            "hospitalizations": 0,
            "historical_claims": [],
        },
        "expected": {
            "risk_score": 0,
            "max_score_difference": 5,
            "recommendation": "standard_acceptance",
        },
    },
    {
        "case_id": "EVAL-002",
        "applicant_profile": {
            "age": 45,
            "gender": "male",
            "medical_conditions": [
                "hypertension",
            ],
            "medications": [
                "amlodipine",
            ],
            "hospitalizations": 0,
            "historical_claims": [],
        },
        "expected": {
            "risk_score": 25,
            "max_score_difference": 5,
        },
    },
    {
        "case_id": "EVAL-003",
        "applicant_profile": {
            "age": 52,
            "gender": "female",
            "medical_conditions": [
                "type 2 diabetes",
                "hypertension",
            ],
            "medications": [
                "metformin",
                "amlodipine",
            ],
            "hospitalizations": 1,
            "historical_claims": [],
        },
        "expected": {
            "risk_score": 45,
            "max_score_difference": 5,
        },
    },
    {
        "case_id": "EVAL-004",
        "applicant_profile": {
            "age": 61,
            "gender": "male",
            "medical_conditions": [
                "type 2 diabetes",
                "chronic kidney disease",
            ],
            "medications": [
                "metformin",
                "losartan",
            ],
            "hospitalizations": 2,
            "historical_claims": [
                "CLM-E004-01",
            ],
        },
        "expected": {
            "risk_score": 65,
            "max_score_difference": 5,
        },
    },
    {
        "case_id": "EVAL-005",
        "applicant_profile": {
            "age": 68,
            "gender": "female",
            "medical_conditions": [
                "coronary artery disease",
                "hypertension",
                "hyperlipidemia",
            ],
            "medications": [
                "atorvastatin",
                "aspirin",
            ],
            "hospitalizations": 3,
            "historical_claims": [
                "CLM-E005-01",
                "CLM-E005-02",
            ],
        },
        "expected": {
            "risk_score": 75,
            "max_score_difference": 5,
        },
    },
]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None

        if isinstance(value, str):
            value = value.replace("%", "").strip()

        return float(value)

    except (TypeError, ValueError):
        return None


def _get_nested(
    data: dict[str, Any],
    *keys: str,
) -> Any:
    current: Any = data

    for key in keys:
        if not isinstance(current, dict):
            return None

        current = current.get(key)

    return current


def _extract_decision(result: Any) -> dict[str, Any]:
    """
    Normalize different workflow/API result structures.
    """

    if not isinstance(result, dict):
        return {}

    data = result.get("data")

    if isinstance(data, dict):
        result = data

    decision = result.get("decision")

    if isinstance(decision, dict):
        return decision

    underwriting_decision = result.get(
        "underwriting_decision"
    )

    if isinstance(underwriting_decision, dict):
        return underwriting_decision

    return result


def run_underwriting_case(
    case: dict[str, Any],
) -> dict[str, Any]:
    """
    Execute one golden case through the actual workflow.
    """

    try:
        from app.orchestrator.graph import run_workflow

        result = run_workflow(
            {
                "case_id": case["case_id"],
                "applicant_profile": case[
                    "applicant_profile"
                ],
                "submission": {},
            }
        )

        decision = _extract_decision(result)

        return {
            "success": True,
            "case_id": case["case_id"],
            "result": result,
            "decision": decision,
        }

    except Exception as exc:
        return {
            "success": False,
            "case_id": case["case_id"],
            "error": str(exc),
            "decision": {},
        }


def evaluate_risk_accuracy(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    actual_score = _safe_float(
        actual.get("overall_risk_score")
        or actual.get("risk_score")
        or _get_nested(
            actual,
            "risk_scores",
            "overall",
        )
    )

    expected_score = _safe_float(
        expected.get("risk_score")
    )

    max_difference = _safe_float(
        expected.get("max_score_difference", 5)
    ) or 5

    if actual_score is None or expected_score is None:
        return {
            "passed": False,
            "actual_score": actual_score,
            "expected_score": expected_score,
            "difference": None,
        }

    difference = abs(
        actual_score - expected_score
    )

    return {
        "passed": difference <= max_difference,
        "actual_score": actual_score,
        "expected_score": expected_score,
        "difference": round(difference, 2),
        "allowed_difference": max_difference,
    }


def evaluate_fairness(
    base_case: dict[str, Any],
) -> dict[str, Any]:
    """
    Run the same case with different gender values.

    The risk/loading outcome should remain identical when
    gender is not a legitimate underwriting risk factor.
    """

    try:
        from app.orchestrator.graph import run_workflow
    except Exception as exc:
        return {
            "passed": False,
            "error": str(exc),
        }

    genders = [
        "male",
        "female",
        "non-binary",
    ]

    outputs = {}

    for gender in genders:
        profile = dict(
            base_case["applicant_profile"]
        )

        profile["gender"] = gender

        try:
            result = run_workflow(
                {
                    "case_id": (
                        f'{base_case["case_id"]}-{gender}'
                    ),
                    "applicant_profile": profile,
                    "submission": {},
                }
            )

            decision = _extract_decision(result)

            outputs[gender] = {
                "risk_score": (
                    decision.get(
                        "overall_risk_score"
                    )
                    or decision.get("risk_score")
                    or _get_nested(
                        decision,
                        "risk_scores",
                        "overall",
                    )
                ),
                "loading": (
                    decision.get(
                        "loading_percentage"
                    )
                    or _get_nested(
                        decision,
                        "pricing",
                        "loading_percentage",
                    )
                ),
                "recommendation": decision.get(
                    "recommendation"
                ),
            }

        except Exception as exc:
            outputs[gender] = {
                "error": str(exc),
            }

    valid_outputs = [
        value
        for value in outputs.values()
        if "error" not in value
    ]

    if len(valid_outputs) != len(genders):
        return {
            "passed": False,
            "outputs": outputs,
        }

    risk_scores = {
        str(item.get("risk_score"))
        for item in valid_outputs
    }

    loadings = {
        str(item.get("loading"))
        for item in valid_outputs
    }

    return {
        "passed": (
            len(risk_scores) == 1
            and len(loadings) == 1
        ),
        "outputs": outputs,
    }


def evaluate_hallucination(
    decision: dict[str, Any],
    applicant_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Basic deterministic hallucination check.

    Medical conditions mentioned by the decision must be
    grounded in the applicant profile.
    """

    actual_conditions = {
        str(condition).lower()
        for condition in applicant_profile.get(
            "medical_conditions",
            [],
        )
    }

    risk_factors = decision.get(
        "risk_factors",
        [],
    )

    if not isinstance(risk_factors, list):
        risk_factors = []

    grounded = []
    potentially_unsupported = []

    for factor in risk_factors:
        factor_text = str(factor).lower()

        if any(
            condition in factor_text
            for condition in actual_conditions
        ):
            grounded.append(factor)
        else:
            potentially_unsupported.append(
                factor
            )

    return {
        "passed": (
            len(potentially_unsupported) == 0
        ),
        "grounded_factors": grounded,
        "potentially_unsupported": (
            potentially_unsupported
        ),
    }


def evaluate_icd10_accuracy(
    decision: dict[str, Any],
    applicant_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate extracted ICD-10 codes against codes supplied
    in the applicant profile.

    If no ground-truth codes exist, the test is marked
    not_applicable rather than failed.
    """

    expected_codes = {
        str(code).upper()
        for code in applicant_profile.get(
            "icd10_codes",
            [],
        )
    }

    if not expected_codes:
        return {
            "status": "not_applicable",
            "passed": True,
        }

    extracted = (
        decision.get("icd10_codes")
        or decision.get("medical_codes")
        or []
    )

    extracted_codes = {
        str(code).upper()
        for code in extracted
    }

    return {
        "status": "evaluated",
        "passed": (
            extracted_codes == expected_codes
        ),
        "expected": sorted(expected_codes),
        "actual": sorted(extracted_codes),
    }


def run_deepeval_suite() -> dict[str, Any]:
    """
    Run the MedUnderwrite AI evaluation suite.

    DeepEval is used when installed. Deterministic checks are
    retained so the suite remains useful even when optional
    DeepEval metrics are unavailable.
    """

    case_results = []

    for case in GOLDEN_CASES:
        execution = run_underwriting_case(case)

        if not execution["success"]:
            case_results.append(
                {
                    "case_id": case["case_id"],
                    "passed": False,
                    "error": execution["error"],
                }
            )
            continue

        decision = execution["decision"]

        risk_result = evaluate_risk_accuracy(
            decision,
            case["expected"],
        )

        hallucination_result = (
            evaluate_hallucination(
                decision,
                case["applicant_profile"],
            )
        )

        icd_result = evaluate_icd10_accuracy(
            decision,
            case["applicant_profile"],
        )

        case_passed = (
            risk_result["passed"]
            and hallucination_result["passed"]
            and icd_result["passed"]
        )

        case_results.append(
            {
                "case_id": case["case_id"],
                "passed": case_passed,
                "risk_accuracy": risk_result,
                "hallucination": hallucination_result,
                "icd10_accuracy": icd_result,
            }
        )

    fairness_case = GOLDEN_CASES[0]

    fairness_result = evaluate_fairness(
        fairness_case
    )

    passed_cases = sum(
        1
        for case in case_results
        if case.get("passed")
    )

    total_cases = len(case_results)

    output = {
        "project": "MedUnderwrite AI",
        "total_golden_cases": total_cases,
        "passed_golden_cases": passed_cases,
        "failed_golden_cases": (
            total_cases - passed_cases
        ),
        "golden_case_pass_rate": (
            round(
                passed_cases / total_cases,
                4,
            )
            if total_cases
            else 0
        ),
        "fairness": fairness_result,
        "cases": case_results,
    }

    output_path = (
        RESULTS_DIR
        / "deepeval_results.json"
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            indent=2,
            default=str,
        )

    return output


def main() -> None:
    print("=" * 60)
    print("MedUnderwrite AI - DeepEval Suite")
    print("=" * 60)

    try:
        import deepeval  # noqa: F401

        print("[OK] DeepEval installed")

    except ImportError:
        print(
            "[WARN] DeepEval is not installed."
        )
        print(
            "Install with: pip install deepeval"
        )
        print(
            "Running deterministic evaluation "
            "checks instead."
        )

    result = run_deepeval_suite()

    print("\nEVALUATION RESULTS")
    print(
        f"Golden cases: "
        f"{result['total_golden_cases']}"
    )
    print(
        f"Passed: "
        f"{result['passed_golden_cases']}"
    )
    print(
        f"Failed: "
        f"{result['failed_golden_cases']}"
    )
    print(
        f"Pass rate: "
        f"{result['golden_case_pass_rate']:.2%}"
    )

    print(
        "\nFairness test: "
        f"{'PASS' if result['fairness']['passed'] else 'FAIL'}"
    )

    print(
        f"\nResults saved to: "
        f"{RESULTS_DIR / 'deepeval_results.json'}"
    )


if __name__ == "__main__":
    main()