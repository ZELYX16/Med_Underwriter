"""
Batch mode: run similar pending cases together so they share work.

What is shared (safe, non-applicant data only):
  - regulatory / underwriting-guidance retrieval: fetched once per group and
    served from the pattern cache to every other case in the group,
  - query embeddings: encoded in a single batch call.

What is NOT shared: applicant evidence, scores, rationale. Every case still
gets its own workflow run and its own LLM call, so one applicant's data can
never leak into another's output.

Grouping happens *before* Agent 1 using only the submission: product plus
the set of recognised condition categories. A group is capped in size and
runs with bounded concurrency (Ollama serves one model well, a few
parallel requests badly), and cases that don't fit any group run alone.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from app.agents.agent1_submission import submission_agent
from app.cache.pattern_cache import cache_scope
from app.config import settings
from app.store.vector_store import vector_store

logger = logging.getLogger(__name__)

# Coarse condition categories used only for grouping.
_CATEGORIES = {
    "diabet": "metabolic",
    "thyroid": "metabolic",
    "hypertens": "cardio",
    "cardi": "cardio",
    "coronary": "cardio",
    "heart": "cardio",
    "cancer": "oncology",
    "renal": "renal",
    "kidney": "renal",
    "liver": "hepatic",
    "copd": "respiratory",
    "asthma": "respiratory",
    "arthritis": "musculoskeletal",
    "rheumat": "musculoskeletal",
}


def group_key(
    applicant_profile: dict[str, Any],
    submission: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    product = str(submission.get("product") or "").strip().lower()
    conditions = applicant_profile.get("medical_conditions") or []
    categories = {
        category
        for condition in conditions
        for term, category in _CATEGORIES.items()
        if term in str(condition).lower()
    }
    return product, tuple(sorted(categories))


def plan_groups(
    cases: dict[str, dict[str, Any]],
) -> list[list[str]]:
    """Group case ids by key, then split groups to the size cap."""
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for case_id, state in cases.items():
        key = group_key(
            state.get("applicant_profile", {}),
            state.get("submission", {}),
        )
        buckets[key].append(case_id)

    size = max(1, settings.batch_max_group_size)
    groups: list[list[str]] = []
    for ids in buckets.values():
        for start in range(0, len(ids), size):
            groups.append(ids[start: start + size])
    return groups


def _warm_shared_work(state: dict[str, Any]) -> None:
    """Fetch the group's shared knowledge once and batch-embed its queries."""
    profile = state.get("applicant_profile", {})
    submission = state.get("submission", {})
    queries = submission_agent._build_queries(profile, submission)

    # Regulatory + guidance land in the pattern cache for the whole group,
    # attributed to the case that triggered the warm-up.
    with cache_scope(state.get("case_id")):
        submission_agent._retrieve_regulatory(queries["regulatory"])
        submission_agent._retrieve_actuarial_guidance(
            queries["actuarial"], submission.get("product")
        )
    vector_store.warm_query_embeddings(list(queries.values()))


async def run_batch(
    cases: dict[str, dict[str, Any]],
    runner: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> dict[str, Any]:
    """
    Run `runner(case_id, state)` for every case, group by group.

    Returns a summary of what was grouped and how long it took.
    """
    started = time.perf_counter()
    groups = plan_groups(cases)
    semaphore = asyncio.Semaphore(max(1, settings.batch_concurrency))

    async def run_one(case_id: str) -> None:
        async with semaphore:
            try:
                await runner(case_id, cases[case_id])
            except Exception:
                # _run_case already routes failures to human review; this
                # only stops one case from cancelling its group.
                logger.exception("Batch case %s failed", case_id)

    for ids in groups:
        if len(ids) > 1:
            try:
                await asyncio.to_thread(_warm_shared_work, cases[ids[0]])
            except Exception:
                logger.exception("Batch warm-up failed; continuing")
        await asyncio.gather(*(run_one(case_id) for case_id in ids))

    return {
        "cases": len(cases),
        "groups": [len(ids) for ids in groups],
        "elapsed_sec": round(time.perf_counter() - started, 3),
    }