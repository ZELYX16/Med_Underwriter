"""
Persistent pattern cache (SQLite, shared across workers and restarts).

Two namespaces, both chosen so a hit can never put one applicant's data in
another applicant's case:

  rationale  Agent 2 explanation keyed by a hash of the *exact* facts,
             scores, pricing and recommendation. Only identical decisions
             hit (re-submissions, rescore rounds, repeat runs), so the
             exact age/BMI/claim counts in the text are always correct.
  knowledge  Non-applicant retrieval (regulatory, underwriting guidance)
             keyed by the pattern (kind, product, condition set), so every
             similar case reuses one retrieval.

What gets recorded is deliberately selective:
  - only validated output (passed the consistency check),
  - never for cases with fraud indicators,
  - invalidated when a human overrides or sends the case back,
  - versioned (prompt / rules) and expiring,
  - bounded: least-recently-used entries are evicted past `max_entries`.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class CacheTrace:
    """What one case read from / wrote to the cache during a node."""

    def __init__(self, case_id: str | None) -> None:
        self.case_id = case_id
        self.events: list[dict[str, Any]] = []

    def add(self, event: dict[str, Any]) -> None:
        self.events.append(event)


_trace: ContextVar[CacheTrace | None] = ContextVar("cache_trace", default=None)


@contextmanager
def cache_scope(case_id: str | None):
    """
    Attribute cache reads/writes to a case. Inside the scope every hit or
    miss is recorded (with the case that originally stored the entry) so the
    UI can show which cached case this one reused. Context propagates into
    asyncio.to_thread workers.
    """
    trace = CacheTrace(case_id)
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)


def _label(namespace: str, key: str) -> str:
    """Human-readable pattern label (rationale keys are opaque hashes)."""
    if namespace == "rationale":
        return f"identical facts, scores and recommendation ({key[:10]}…)"
    return key.replace("|", " · ")[:160]


def note_cache_event(
    namespace: str,
    key: str,
    outcome: str,
    **extra: Any,
) -> None:
    trace = _trace.get()
    if trace is not None:
        trace.add(
            {
                "namespace": namespace,
                "pattern": _label(namespace, key),
                "outcome": outcome,
                **extra,
            }
        )


class PatternCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            settings.sqlite_file,
            check_same_thread=False,
            timeout=5,
        )
        if not self._ready:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pattern_cache (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    version TEXT NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_used REAL NOT NULL,
                    source_case_id TEXT,
                    PRIMARY KEY (namespace, key)
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(pattern_cache)"
                )
            }
            if "source_case_id" not in columns:
                connection.execute(
                    "ALTER TABLE pattern_cache "
                    "ADD COLUMN source_case_id TEXT"
                )
            connection.commit()
            self._ready = True
        return connection

    @contextmanager
    def _session(self):
        """Commit and always close (sqlite's own `with` never closes)."""
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get(self, namespace: str, key: str) -> Any | None:
        if not settings.pattern_cache_enabled:
            return None
        now = time.time()
        try:
            with self._lock, self._session() as connection:
                row = connection.execute(
                    "SELECT value, version, created_at, source_case_id, "
                    "hits FROM pattern_cache "
                    "WHERE namespace = ? AND key = ?",
                    (namespace, key),
                ).fetchone()
                if row is None:
                    note_cache_event(namespace, key, "miss")
                    return None
                value, version, created_at, source_case_id, prior_hits = row
                expired = now - created_at > settings.pattern_cache_ttl_sec
                if version != settings.prompt_version or expired:
                    connection.execute(
                        "DELETE FROM pattern_cache "
                        "WHERE namespace = ? AND key = ?",
                        (namespace, key),
                    )
                    note_cache_event(namespace, key, "miss", reason="expired")
                    return None
                connection.execute(
                    "UPDATE pattern_cache SET hits = hits + 1, "
                    "last_used = ? WHERE namespace = ? AND key = ?",
                    (now, namespace, key),
                )
                note_cache_event(
                    namespace,
                    key,
                    "hit",
                    source_case_id=source_case_id,
                    reuse_count=int(prior_hits or 0) + 1,
                    stored_at=created_at,
                )
                return json.loads(value)
        except Exception as exc:  # cache must never break a case
            logger.warning("pattern cache read failed: %s", exc)
            return None

    def put(self, namespace: str, key: str, value: Any) -> None:
        if not settings.pattern_cache_enabled:
            return
        now = time.time()
        trace = _trace.get()
        case_id = trace.case_id if trace else None
        try:
            with self._lock, self._session() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO pattern_cache "
                    "(namespace, key, value, version, hits, created_at, "
                    "last_used, source_case_id) "
                    "VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
                    (
                        namespace,
                        key,
                        json.dumps(value, default=str),
                        settings.prompt_version,
                        now,
                        now,
                        case_id,
                    ),
                )
                note_cache_event(namespace, key, "stored")
                connection.execute(
                    "DELETE FROM pattern_cache WHERE rowid IN ("
                    "SELECT rowid FROM pattern_cache ORDER BY last_used "
                    "DESC LIMIT -1 OFFSET ?)",
                    (settings.pattern_cache_max_entries,),
                )
        except Exception as exc:
            logger.warning("pattern cache write failed: %s", exc)

    def record_hit(self, namespace: str, key: str) -> None:
        """
        Count a reuse served from a process-local memo and attribute it to
        the entry's source case (the memo itself holds no provenance).
        """
        if not settings.pattern_cache_enabled:
            return
        try:
            with self._lock, self._session() as connection:
                row = connection.execute(
                    "SELECT created_at, source_case_id, hits "
                    "FROM pattern_cache WHERE namespace = ? AND key = ?",
                    (namespace, key),
                ).fetchone()
                if row is None:
                    note_cache_event(namespace, key, "hit", source_case_id=None)
                    return
                connection.execute(
                    "UPDATE pattern_cache SET hits = hits + 1, last_used = ? "
                    "WHERE namespace = ? AND key = ?",
                    (time.time(), namespace, key),
                )
                note_cache_event(
                    namespace,
                    key,
                    "hit",
                    source_case_id=row[1],
                    reuse_count=int(row[2] or 0) + 1,
                    stored_at=row[0],
                )
        except Exception as exc:
            logger.warning("pattern cache record_hit failed: %s", exc)

    def invalidate(self, namespace: str, key: str | None) -> None:
        if not key:
            return
        try:
            with self._lock, self._session() as connection:
                connection.execute(
                    "DELETE FROM pattern_cache "
                    "WHERE namespace = ? AND key = ?",
                    (namespace, key),
                )
        except Exception as exc:
            logger.warning("pattern cache invalidate failed: %s", exc)

    def stats(self) -> dict[str, Any]:
        try:
            with self._lock, self._session() as connection:
                rows = connection.execute(
                    "SELECT namespace, COUNT(*), COALESCE(SUM(hits), 0) "
                    "FROM pattern_cache GROUP BY namespace"
                ).fetchall()
            return {
                ns: {"entries": count, "hits": hits}
                for ns, count, hits in rows
            }
        except Exception:
            return {}


pattern_cache = PatternCache()