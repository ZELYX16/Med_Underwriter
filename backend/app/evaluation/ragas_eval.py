"""
MedUnderwrite AI — RAGAS Evaluation Pipeline

Owner: Persona A (Day 2 AM)

Runs RAGAS on 20 test medical queries measuring:
  - Faithfulness       (answer grounded in retrieved context?) → target > 0.90
  - Context Precision  (relevant chunks in top-5?)
  - Context Recall     (all required facts retrieved?)
  - Answer Relevancy   (does it answer the query?)

Usage:
    python backend/scripts/run_ragas_eval.py

TODO (Persona A): define 20 test queries and expected answers, wire RAGAS metrics.
"""


def run_ragas_evaluation(test_queries: list[dict] = None) -> dict:
    """
    Run RAGAS evaluation on the RAG pipeline.

    Args:
        test_queries: List of {question, ground_truth} dicts.
                      Uses built-in 20 queries if None.

    Returns:
        Dict of RAGAS metric scores.
    """
    raise NotImplementedError("ragas_eval.py is implemented by Persona A (Day 2 AM).")
