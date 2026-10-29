"""
Per-case retrieval budget.

One RetrievalBudget is activated per workflow run (Agent 1). Every vector
query is charged against it from VectorStore.query, so CRAG, agentic RAG and
the plain retrievers are all bounded without each needing its own counters.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from app.config import settings


class RetrievalBudget:
    def __init__(
        self,
        max_calls: int | None = None,
        max_chunks: int | None = None,
        max_seconds: float | None = None,
    ) -> None:
        self.max_calls = max_calls or settings.rag_max_calls_per_case
        self.max_chunks = max_chunks or settings.rag_max_chunks_per_case
        self.max_seconds = max_seconds or settings.rag_max_seconds_per_case
        self.calls = 0
        self.chunks = 0
        self.denied = 0
        self._started = time.perf_counter()
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        """Reserve one query. False means the budget is spent."""
        with self._lock:
            if (
                self.calls >= self.max_calls
                or self.chunks >= self.max_chunks
                or time.perf_counter() - self._started > self.max_seconds
            ):
                self.denied += 1
                return False
            self.calls += 1
            return True

    def remaining_chunks(self) -> int:
        with self._lock:
            return max(0, self.max_chunks - self.chunks)

    def record_chunks(self, count: int) -> None:
        with self._lock:
            self.chunks += count

    def exhausted(self) -> bool:
        with self._lock:
            return (
                self.calls >= self.max_calls
                or self.chunks >= self.max_chunks
                or time.perf_counter() - self._started > self.max_seconds
            )

    def summary(self) -> dict[str, float | int | bool]:
        with self._lock:
            return {
                "calls": self.calls,
                "chunks": self.chunks,
                "denied_calls": self.denied,
                "elapsed_sec": round(time.perf_counter() - self._started, 3),
                "exhausted": self.denied > 0,
            }


_current: ContextVar[RetrievalBudget | None] = ContextVar(
    "retrieval_budget", default=None
)


def current_budget() -> RetrievalBudget | None:
    return _current.get()


@contextmanager
def retrieval_budget(
    budget: RetrievalBudget | None = None,
) -> Iterator[RetrievalBudget]:
    active = budget or RetrievalBudget()
    token = _current.set(active)
    try:
        yield active
    finally:
        _current.reset(token)