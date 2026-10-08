from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


EVALUATION_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALUATION_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


DEFAULT_TEST_QUERIES = [
    {
        "question": "What is diabetes mellitus?",
        "ground_truth": (
            "Diabetes mellitus is a chronic metabolic disorder "
            "characterized by elevated blood glucose levels."
        ),
    },
    {
        "question": "What is hypertension?",
        "ground_truth": (
            "Hypertension is persistently elevated blood pressure."
        ),
    },
    {
        "question": "What is hyperlipidemia?",
        "ground_truth": (
            "Hyperlipidemia is an abnormal elevation of lipids "
            "in the blood."
        ),
    },
    {
        "question": "What is asthma?",
        "ground_truth": (
            "Asthma is a chronic respiratory condition involving "
            "airway inflammation and variable airflow obstruction."
        ),
    },
    {
        "question": "What is chronic kidney disease?",
        "ground_truth": (
            "Chronic kidney disease is a long-term condition "
            "involving impaired kidney structure or function."
        ),
    },
    {
        "question": "What is coronary artery disease?",
        "ground_truth": (
            "Coronary artery disease involves narrowing or blockage "
            "of the coronary arteries."
        ),
    },
    {
        "question": "What is myocardial infarction?",
        "ground_truth": (
            "Myocardial infarction is damage to heart muscle caused "
            "by inadequate blood flow, commonly due to coronary "
            "artery blockage."
        ),
    },
    {
        "question": "What is chronic obstructive pulmonary disease?",
        "ground_truth": (
            "COPD is a chronic lung disease associated with "
            "persistent airflow limitation."
        ),
    },
    {
        "question": "What is anemia?",
        "ground_truth": (
            "Anemia is a condition in which the blood has reduced "
            "oxygen-carrying capacity, commonly due to low hemoglobin."
        ),
    },
    {
        "question": "What is gastroesophageal reflux disease?",
        "ground_truth": (
            "GERD is a condition in which stomach contents repeatedly "
            "flow back into the esophagus."
        ),
    },
    {
        "question": "What is obesity?",
        "ground_truth": (
            "Obesity is excessive or abnormal body fat accumulation "
            "that may impair health."
        ),
    },
    {
        "question": "What is rheumatoid arthritis?",
        "ground_truth": (
            "Rheumatoid arthritis is a chronic autoimmune disease "
            "that primarily affects joints."
        ),
    },
    {
        "question": "What is osteoarthritis?",
        "ground_truth": (
            "Osteoarthritis is a degenerative joint disorder involving "
            "breakdown of joint cartilage and associated structures."
        ),
    },
    {
        "question": "What is a urinary tract infection?",
        "ground_truth": (
            "A urinary tract infection is an infection affecting "
            "the urinary system."
        ),
    },
    {
        "question": "What is kidney stone disease?",
        "ground_truth": (
            "Kidney stone disease involves solid mineral deposits "
            "forming within the kidneys or urinary tract."
        ),
    },
    {
        "question": "What is hypothyroidism?",
        "ground_truth": (
            "Hypothyroidism is a condition in which the thyroid gland "
            "does not produce enough thyroid hormone."
        ),
    },
    {
        "question": "What is hyperthyroidism?",
        "ground_truth": (
            "Hyperthyroidism occurs when the thyroid gland produces "
            "excess thyroid hormone."
        ),
    },
    {
        "question": "What is atherosclerosis?",
        "ground_truth": (
            "Atherosclerosis is the buildup of plaque within arterial "
            "walls that can restrict blood flow."
        ),
    },
    {
        "question": "What is a stroke?",
        "ground_truth": (
            "A stroke occurs when blood flow to part of the brain is "
            "interrupted or when a blood vessel in the brain ruptures."
        ),
    },
    {
        "question": "What is heart failure?",
        "ground_truth": (
            "Heart failure is a condition in which the heart cannot "
            "pump enough blood to meet the body's needs."
        ),
    },
]


def _extract_text(value: Any) -> str:
    """Extract text from common RAG response formats."""

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        for key in (
            "answer",
            "response",
            "content",
            "text",
            "result",
        ):
            if key in value:
                return _extract_text(value[key])

    if isinstance(value, list):
        parts = [
            _extract_text(item)
            for item in value
        ]
        return "\n".join(
            part for part in parts if part
        )

    return str(value).strip()


def _extract_contexts(result: Any) -> list[str]:
    """Extract retrieved contexts from a RAG response."""

    if not isinstance(result, dict):
        return []

    possible_keys = (
        "contexts",
        "retrieved_contexts",
        "retrieved_documents",
        "documents",
        "evidence",
    )

    for key in possible_keys:
        value = result.get(key)

        if not value:
            continue

        if isinstance(value, str):
            return [value]

        if isinstance(value, list):
            contexts = []

            for item in value:
                text = _extract_text(item)

                if text:
                    contexts.append(text)

            return contexts

    return []


def _run_rag_pipeline(question: str) -> dict[str, Any]:
    """
    Run the project's RAG pipeline.

    The import is intentionally delayed so that the evaluation
    module can still be imported when the RAG stack is unavailable.
    """

    try:
        from app.rag.agentic_rag import agentic_rag

        result = agentic_rag.search(
            query=question,
            source_scope="knowledge",
        )

        if isinstance(result, dict):
            answer = _extract_text(result)
            contexts = _extract_contexts(result)

            return {
                "answer": answer,
                "contexts": contexts,
                "raw": result,
            }

    except Exception as exc:
        return {
            "answer": "",
            "contexts": [],
            "error": str(exc),
        }

    return {
        "answer": "",
        "contexts": [],
    }


def _build_dataset(test_queries: list[dict]) -> Any:
    """Build a RAGAS EvaluationDataset."""

    from ragas import EvaluationDataset

    samples = []

    for item in test_queries:
        question = item["question"]
        ground_truth = item["ground_truth"]

        result = _run_rag_pipeline(question)

        samples.append(
            {
                "user_input": question,
                "response": result["answer"],
                "retrieved_contexts": result["contexts"],
                "reference": ground_truth,
            }
        )

    return EvaluationDataset.from_list(samples)


def run_ragas_evaluation(
    test_queries: list[dict] | None = None,
) -> dict:
    """
    Run RAGAS evaluation on the MedUnderwrite AI RAG pipeline.

    Args:
        test_queries:
            List containing:
                {
                    "question": "...",
                    "ground_truth": "..."
                }

    Returns:
        Dictionary containing metric scores and per-query results.
    """

    queries = (
        test_queries
        if test_queries is not None
        else DEFAULT_TEST_QUERIES
    )

    if not queries:
        raise ValueError(
            "At least one evaluation query is required."
        )

    try:
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except ImportError as exc:
        raise RuntimeError(
            "RAGAS is not installed. "
            "Install it with: pip install ragas"
        ) from exc

    dataset = _build_dataset(queries)

    result = evaluate(
        dataset=dataset,
        metrics=[
            faithfulness,
            context_precision,
            context_recall,
            answer_relevancy,
        ],
    )

    scores = {}

    for metric in (
        "faithfulness",
        "context_precision",
        "context_recall",
        "answer_relevancy",
    ):
        try:
            scores[metric] = float(
                result[metric]
            )
        except Exception:
            scores[metric] = None

    evaluation_output = {
        "project": "MedUnderwrite AI",
        "total_queries": len(queries),
        "metrics": scores,
        "target": {
            "faithfulness": 0.90,
            "context_precision": None,
            "context_recall": None,
            "answer_relevancy": None,
        },
    }

    output_path = (
        RESULTS_DIR / "ragas_results.json"
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            evaluation_output,
            file,
            indent=2,
        )

    return evaluation_output


def main() -> None:
    print("=" * 60)
    print("MedUnderwrite AI - RAGAS Evaluation")
    print("=" * 60)

    result = run_ragas_evaluation()

    print("\nRAGAS RESULTS")

    for metric, score in result["metrics"].items():
        if score is None:
            print(f"{metric:22}: unavailable")
        else:
            print(f"{metric:22}: {score:.4f}")

    print(
        f"\nQueries evaluated: "
        f"{result['total_queries']}"
    )

    print(
        f"Results saved to: "
        f"{RESULTS_DIR / 'ragas_results.json'}"
    )


if __name__ == "__main__":
    main()