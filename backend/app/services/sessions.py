"""
Application sessions: the live form, its documents and open items, persisted.

A session is identified by an unguessable token (the resume code). Every save
is an autosave, so the applicant can close the page and continue later with
the same code. No login is involved; add real authentication before real use.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TTL_DAYS = 14

_SCHEMA = """
CREATE TABLE IF NOT EXISTS application_sessions (
    token TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'collecting',
    form_json TEXT NOT NULL DEFAULT '{}',
    documents_json TEXT NOT NULL DEFAULT '[]',
    meta_json TEXT NOT NULL DEFAULT '{}',
    applicant_id TEXT,
    case_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        return {
            "token": d["token"], "status": d["status"], "applicant_id": d["applicant_id"], "case_id": d["case_id"],
            "form": json.loads(d["form_json"]), "documents": json.loads(d["documents_json"]),
            "meta": json.loads(d["meta_json"]), "created_at": d["created_at"],
            "updated_at": d["updated_at"], "expires_at": d["expires_at"],
        }

    def create(self, applicant_id: str, case_id: str) -> dict[str, Any]:
        token = secrets.token_urlsafe(12)
        now = _now()
        expires = (datetime.now(timezone.utc) + timedelta(days=TTL_DAYS)).isoformat()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO application_sessions (token, applicant_id, case_id, created_at, updated_at, expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (token, applicant_id, case_id, now, now, expires),
            )
        return self.get(token)  # type: ignore[return-value]

    def get(self, token: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM application_sessions WHERE token=?", (token,)).fetchone()
        session = self._row(row)
        if session and session["expires_at"] < _now():
            return None  # expired sessions cannot be resumed
        return session

    def update(self, token: str, *, form: dict | None = None, documents: list | None = None,
               meta: dict | None = None, status: str | None = None,
               case_id: str | None = None, applicant_id: str | None = None) -> None:
        sets, params = ["updated_at=?"], [_now()]
        for col, value in (("form_json", form), ("documents_json", documents), ("meta_json", meta)):
            if value is not None:
                sets.append(f"{col}=?")
                params.append(json.dumps(value, default=str))
        if status:
            sets.append("status=?")
            params.append(status)
        if case_id is not None:
            sets.append("case_id=?")
            params.append(case_id)
        if applicant_id is not None:
            sets.append("applicant_id=?")
            params.append(applicant_id)
        params.append(token)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE application_sessions SET {', '.join(sets)} WHERE token=?", params)

    def mutate_documents(self, token: str, fn) -> list[dict[str, Any]]:
        """Read-modify-write the document list under the lock (parallel jobs)."""
        with self._lock, self._conn() as c:
            row = c.execute("SELECT documents_json FROM application_sessions WHERE token=?", (token,)).fetchone()
            docs = json.loads(row["documents_json"]) if row else []
            docs = fn(docs) or docs
            c.execute("UPDATE application_sessions SET documents_json=?, updated_at=? WHERE token=?",
                      (json.dumps(docs, default=str), _now(), token))
        return docs

    def add_document_if_hash_new(self, token: str, entry: dict[str, Any]) -> bool:
        """Atomically add a session document unless its hash already exists.

        BEGIN IMMEDIATE serializes competing writers, including requests
        handled by separate API worker processes.
        """
        file_hash = str(entry.get("sha256") or "").strip()
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT documents_json FROM application_sessions WHERE token=?",
                (token,),
            ).fetchone()
            if row is None:
                raise KeyError("Application session no longer exists.")
            docs = json.loads(row["documents_json"] or "[]")
            if file_hash and any(
                d.get("sha256") == file_hash and d.get("status") != "rejected"
                for d in docs
            ):
                return False
            docs.append(entry)
            c.execute(
                "UPDATE application_sessions SET documents_json=?, updated_at=? WHERE token=?",
                (json.dumps(docs, default=str), _now(), token),
            )
            return True

    def update_document(self, token: str, doc_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        """Atomically patch one session document and return its latest value."""
        latest: dict[str, Any] | None = None
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT documents_json FROM application_sessions WHERE token=?",
                (token,),
            ).fetchone()
            if row is None:
                return None
            docs = json.loads(row["documents_json"] or "[]")
            for item in docs:
                if item.get("id") == doc_id:
                    # A deletion request wins over a late indexing status,
                    # while still retaining useful fields such as document_id.
                    deleting = item.get("status") == "deleting"
                    item.update(patch)
                    if deleting:
                        item["status"] = "deleting"
                    latest = dict(item)
                    break
            c.execute(
                "UPDATE application_sessions SET documents_json=?, updated_at=? WHERE token=?",
                (json.dumps(docs, default=str), _now(), token),
            )
        return latest

    def mark_document_deleting(self, token: str, doc_id: str) -> dict[str, Any] | None:
        """Mark a still-processing upload for deletion without racing its worker."""
        latest: dict[str, Any] | None = None
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT documents_json FROM application_sessions WHERE token=?",
                (token,),
            ).fetchone()
            if row is None:
                return None
            docs = json.loads(row["documents_json"] or "[]")
            for item in docs:
                if item.get("id") == doc_id:
                    item["status"] = "deleting"
                    latest = dict(item)
                    break
            c.execute(
                "UPDATE application_sessions SET documents_json=?, updated_at=? WHERE token=?",
                (json.dumps(docs, default=str), _now(), token),
            )
        return latest

    def remove_document_entry(self, token: str, doc_id: str) -> None:
        """Remove one session document entry after storage cleanup succeeds."""
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT documents_json FROM application_sessions WHERE token=?",
                (token,),
            ).fetchone()
            if row is None:
                return
            docs = json.loads(row["documents_json"] or "[]")
            docs = [item for item in docs if item.get("id") != doc_id]
            c.execute(
                "UPDATE application_sessions SET documents_json=?, updated_at=? WHERE token=?",
                (json.dumps(docs, default=str), _now(), token),
            )

    def purge_expired(self) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM application_sessions WHERE expires_at < ?", (_now(),)).rowcount


_store: SessionStore | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        from app.config import settings

        _store = SessionStore(settings.sqlite_file)
    return _store


def timed() -> float:
    return time.perf_counter()
