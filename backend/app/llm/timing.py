"""
Per-call timing from the model server, when it reports it.

Ollama returns nanosecond durations in the response metadata. Separating
model load, prompt processing and generation shows whether a slow call was
a model reload, a long prompt, or slow generation.
"""
from __future__ import annotations

from typing import Any

_NS = 1_000_000_000


def extract_timing(response: Any) -> dict[str, float]:
    meta = getattr(response, "response_metadata", None)
    if not isinstance(meta, dict):
        return {}

    def seconds(key: str) -> float | None:
        value = meta.get(key)
        try:
            return round(float(value) / _NS, 3) if value is not None else None
        except (TypeError, ValueError):
            return None

    load = seconds("load_duration")
    prompt_eval = seconds("prompt_eval_duration")
    generation = seconds("eval_duration")
    if load is None and prompt_eval is None and generation is None:
        return {}

    timing: dict[str, float] = {}
    if load is not None:
        timing["load_sec"] = load
    if prompt_eval is not None:
        timing["prompt_eval_sec"] = prompt_eval
    if generation is not None:
        timing["generation_sec"] = generation
    eval_count = meta.get("eval_count")
    try:
        if generation and eval_count:
            timing["tokens_per_sec"] = round(float(eval_count) / generation, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return timing