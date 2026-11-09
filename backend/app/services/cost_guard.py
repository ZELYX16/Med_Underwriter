"""
Cost guard for LLM calls on free tiers.

A per-case call budget stops a loop or a long session from burning a daily
quota, and a rolling per-minute limit protects hosted providers. When a call is
not allowed the caller uses its deterministic path instead. Local models
(Ollama) are only limited per case.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_per_case: dict[str, int] = defaultdict(int)
_window: deque[float] = deque()


def _limits() -> tuple[int, int, str]:
    try:
        from app.config import settings

        return (settings.llm_calls_per_case, settings.llm_calls_per_minute, settings.llm_provider)
    except Exception:
        return (8, 20, "ollama")


def allow(case_id: str | None, kind: str = "llm") -> bool:
    per_case, per_minute, provider = _limits()
    now = time.monotonic()
    with _lock:
        key = case_id or "_"
        # Bound _per_case memory growth
        if len(_per_case) > 1000:
            for old_key in list(_per_case.keys())[:200]:
                _per_case.pop(old_key, None)
        if _per_case[key] >= per_case:
            return False
        if provider != "ollama":
            while _window and now - _window[0] > 60:
                _window.popleft()
            if len(_window) >= per_minute:
                return False
            _window.append(now)
        _per_case[key] += 1
        return True


def reset(case_id: str) -> None:
    """A new run of the same case starts with a fresh budget."""
    with _lock:
        _per_case.pop(case_id, None)


def current_case_id() -> str | None:
    try:
        from app.cache.pattern_cache import _trace

        trace = _trace.get()
        return trace.case_id if trace else None
    except Exception:
        return None
