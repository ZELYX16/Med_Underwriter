from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, db_path: str | Path = "data/medunderwrite.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    # ------------------------------------------------------------------
    # Connection / initialization
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS applicants (
                        applicant_id TEXT PRIMARY KEY,
                        applicant_profile TEXT NOT NULL DEFAULT '{}',
                        source TEXT NOT NULL DEFAULT 'synthetic',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS underwriting_cases (
                        case_id TEXT PRIMARY KEY,
                        applicant_id TEXT,
                        status TEXT NOT NULL,
                        state_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (applicant_id)
                            REFERENCES applicants(applicant_id)
                            ON DELETE SET NULL
                    );

                    CREATE TABLE IF NOT EXISTS workflow_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        case_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        node TEXT,
                        status TEXT,
                        message TEXT,
                        data_json TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (case_id)
                            REFERENCES underwriting_cases(case_id)
                            ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS human_reviews (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        case_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reviewer TEXT,
                        comment TEXT,
                        decision TEXT,
                        data_json TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (case_id)
                            REFERENCES underwriting_cases(case_id)
                            ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS applicant_documents (
                        document_id TEXT PRIMARY KEY,
                        applicant_id TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        file_path TEXT,
                        source TEXT NOT NULL DEFAULT 'uploaded',
                        evidence_status TEXT NOT NULL DEFAULT 'PROVIDED',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (applicant_id)
                            REFERENCES applicants(applicant_id)
                            ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS case_documents (
                        document_id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        applicant_id TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        file_path TEXT,
                        source TEXT NOT NULL DEFAULT 'uploaded',
                        evidence_status TEXT NOT NULL DEFAULT 'PROVIDED',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (case_id)
                            REFERENCES underwriting_cases(case_id)
                            ON DELETE CASCADE,
                        FOREIGN KEY (applicant_id)
                            REFERENCES applicants(applicant_id)
                            ON DELETE CASCADE
                    );
                    """
                )

                # ------------------------------------------------------
                # Legacy DB migration
                # ------------------------------------------------------

                case_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(underwriting_cases)"
                    ).fetchall()
                }

                if "applicant_id" not in case_columns:
                    connection.execute(
                        """
                        ALTER TABLE underwriting_cases
                        ADD COLUMN applicant_id TEXT
                        """
                    )

                # Existing databases may not have these indexes.
                # The column migration MUST happen before this.
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_cases_applicant
                    ON underwriting_cases(applicant_id)
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_cases_status
                    ON underwriting_cases(status)
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_documents_applicant
                    ON applicant_documents(applicant_id)
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_case_documents_case
                    ON case_documents(case_id)
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_case_documents_applicant
                    ON case_documents(applicant_id)
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_events_case
                    ON workflow_events(case_id)
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    idx_reviews_case
                    ON human_reviews(case_id)
                    """
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value if value is not None else {},
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _from_json(value: str | None, default: Any = None) -> Any:
        if not value:
            return default if default is not None else {}

        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default if default is not None else {}

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # Applicants
    # ------------------------------------------------------------------

    def create_applicant(
        self,
        applicant_id: str | None = None,
        applicant_profile: dict[str, Any] | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        applicant_id = (
            str(applicant_id).strip()
            if applicant_id
            else f"APP-{uuid.uuid4().hex[:8].upper()}"
        )

        now = _now()
        profile = applicant_profile or {}

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO applicants (
                        applicant_id,
                        applicant_profile,
                        source,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        applicant_id,
                        self._json(profile),
                        source,
                        now,
                        now,
                    ),
                )

        return self.get_applicant(applicant_id)

    def get_applicant(
        self,
        applicant_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM applicants
                WHERE applicant_id = ?
                """,
                (applicant_id,),
            ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["applicant_profile"] = self._from_json(
            result.get("applicant_profile"),
            {},
        )

        result["documents"] = self.list_applicant_documents(
            applicant_id
        )

        result["cases"] = self.list_cases(
            applicant_id=applicant_id,
        )

        return result

    def update_applicant(
        self,
        applicant_id: str,
        applicant_profile: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE applicants
                    SET applicant_profile = ?,
                        updated_at = ?
                    WHERE applicant_id = ?
                    """,
                    (
                        self._json(applicant_profile),
                        _now(),
                        applicant_id,
                    ),
                )

                if cursor.rowcount == 0:
                    return None

        return self.get_applicant(applicant_id)

    def list_applicants(
        self,
        limit: int = 100,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))

        query = """
            SELECT *
            FROM applicants
        """
        params: list[Any] = []

        if search:
            query += """
                WHERE applicant_id LIKE ?
                OR applicant_profile LIKE ?
            """
            value = f"%{search}%"
            params.extend([value, value])

        query += """
            ORDER BY updated_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                query,
                params,
            ).fetchall()

        results: list[dict[str, Any]] = []

        for row in rows:
            item = dict(row)

            item["applicant_profile"] = self._from_json(
                item.get("applicant_profile"),
                {},
            )

            results.append(item)

        return results

    # ------------------------------------------------------------------
    # Cases
    # ------------------------------------------------------------------

    def create_case(
        self,
        case_id: str,
        applicant_id: str,
        state: dict[str, Any],
        status: str = "created",
    ) -> dict[str, Any]:
        now = _now()

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO underwriting_cases (
                        case_id,
                        applicant_id,
                        status,
                        state_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        applicant_id,
                        status,
                        self._json(state),
                        now,
                        now,
                    ),
                )

        return self.get_case(case_id)

    def save_case(
        self,
        case_id: str,
        state: dict[str, Any],
        status: str | None = None,
    ) -> dict[str, Any] | None:
        now = _now()

        with self._lock:
            with self._connect() as connection:
                if status is None:
                    connection.execute(
                        """
                        UPDATE underwriting_cases
                        SET state_json = ?,
                            updated_at = ?
                        WHERE case_id = ?
                        """,
                        (
                            self._json(state),
                            now,
                            case_id,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE underwriting_cases
                        SET state_json = ?,
                            status = ?,
                            updated_at = ?
                        WHERE case_id = ?
                        """,
                        (
                            self._json(state),
                            status,
                            now,
                            case_id,
                        ),
                    )

        return self.get_case(case_id)

    def get_case(
        self,
        case_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM underwriting_cases
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchone()

        if row is None:
            return None

        result = dict(row)

        state = self._from_json(
            result.pop("state_json", "{}"),
            {},
        )

        result.update(state)

        result["case_id"] = case_id
        result["applicant_id"] = (
            result.get("applicant_id")
            or state.get("applicant_id")
        )

        return result

    def list_cases(
        self,
        limit: int = 100,
        applicant_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))

        query = """
            SELECT *
            FROM underwriting_cases
            WHERE 1 = 1
        """

        params: list[Any] = []

        if applicant_id:
            query += " AND applicant_id = ?"
            params.append(applicant_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += """
            ORDER BY updated_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                query,
                params,
            ).fetchall()

        results: list[dict[str, Any]] = []

        for row in rows:
            raw = dict(row)

            state = self._from_json(
                raw.pop("state_json", "{}"),
                {},
            )

            raw.update(state)

            results.append(raw)

        return results

    def update_case_status(
        self,
        case_id: str,
        status: str,
    ) -> bool:
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE underwriting_cases
                    SET status = ?,
                        updated_at = ?
                    WHERE case_id = ?
                    """,
                    (
                        status,
                        _now(),
                        case_id,
                    ),
                )

                return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Applicant documents
    # ------------------------------------------------------------------

    def add_applicant_document(
        self,
        applicant_id: str,
        document_type: str,
        filename: str,
        file_path: str | None = None,
        source: str = "uploaded",
        evidence_status: str = "PROVIDED",
        metadata: dict[str, Any] | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        document_id = (
            document_id
            or f"DOC-{uuid.uuid4().hex[:12].upper()}"
        )

        now = _now()

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO applicant_documents (
                        document_id,
                        applicant_id,
                        document_type,
                        filename,
                        file_path,
                        source,
                        evidence_status,
                        metadata_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        applicant_id,
                        document_type,
                        filename,
                        file_path,
                        source,
                        evidence_status,
                        self._json(metadata or {}),
                        now,
                        now,
                    ),
                )

        return self.get_applicant_document(document_id)

    def get_applicant_document(
        self,
        document_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM applicant_documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()

        if row is None:
            return None

        result = dict(row)

        result["metadata"] = self._from_json(
            result.pop("metadata_json", "{}"),
            {},
        )

        return result

    def list_applicant_documents(
        self,
        applicant_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM applicant_documents
                WHERE applicant_id = ?
                ORDER BY created_at DESC
                """,
                (applicant_id,),
            ).fetchall()

        results = []

        for row in rows:
            item = dict(row)
            item["metadata"] = self._from_json(
                item.pop("metadata_json", "{}"),
                {},
            )
            results.append(item)

        return results

    def delete_applicant_document(
        self,
        document_id: str,
    ) -> bool:
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM applicant_documents
                    WHERE document_id = ?
                    """,
                    (document_id,),
                )

                return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Case documents
    # ------------------------------------------------------------------

    def add_case_document(
        self,
        case_id: str,
        applicant_id: str,
        document_type: str,
        filename: str,
        file_path: str | None = None,
        source: str = "uploaded",
        evidence_status: str = "PROVIDED",
        metadata: dict[str, Any] | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        document_id = (
            document_id
            or f"DOC-{uuid.uuid4().hex[:12].upper()}"
        )

        now = _now()

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO case_documents (
                        document_id,
                        case_id,
                        applicant_id,
                        document_type,
                        filename,
                        file_path,
                        source,
                        evidence_status,
                        metadata_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        case_id,
                        applicant_id,
                        document_type,
                        filename,
                        file_path,
                        source,
                        evidence_status,
                        self._json(metadata or {}),
                        now,
                        now,
                    ),
                )

        return self.get_case_document(document_id)

    def get_case_document(
        self,
        document_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM case_documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()

        if row is None:
            return None

        result = dict(row)

        result["metadata"] = self._from_json(
            result.pop("metadata_json", "{}"),
            {},
        )

        return result

    def list_case_documents(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM case_documents
                WHERE case_id = ?
                ORDER BY created_at DESC
                """,
                (case_id,),
            ).fetchall()

        results = []

        for row in rows:
            item = dict(row)

            item["metadata"] = self._from_json(
                item.pop("metadata_json", "{}"),
                {},
            )

            results.append(item)

        return results

    def delete_case_document(
        self,
        document_id: str,
        case_id: str | None = None,
    ) -> bool:
        with self._lock:
            with self._connect() as connection:
                if case_id:
                    cursor = connection.execute(
                        """
                        DELETE FROM case_documents
                        WHERE document_id = ?
                        AND case_id = ?
                        """,
                        (
                            document_id,
                            case_id,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """
                        DELETE FROM case_documents
                        WHERE document_id = ?
                        """,
                        (document_id,),
                    )

                return cursor.rowcount > 0

    def delete_document(
        self,
        document_id: str,
        case_id: str | None = None,
        applicant_id: str | None = None,
    ) -> bool:
        """
        Compatibility helper used by API/service layers.

        Deletes from case_documents first. If not found there,
        attempts applicant_documents.
        """

        deleted = self.delete_case_document(
            document_id=document_id,
            case_id=case_id,
        )

        if deleted:
            return True

        with self._lock:
            with self._connect() as connection:
                if applicant_id:
                    cursor = connection.execute(
                        """
                        DELETE FROM applicant_documents
                        WHERE document_id = ?
                        AND applicant_id = ?
                        """,
                        (
                            document_id,
                            applicant_id,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """
                        DELETE FROM applicant_documents
                        WHERE document_id = ?
                        """,
                        (document_id,),
                    )

                return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Workflow events
    # ------------------------------------------------------------------

    def add_workflow_event(
        self,
        case_id: str,
        event_type: str = "workflow",
        node: str | None = None,
        status: str | None = None,
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO workflow_events (
                        case_id,
                        event_type,
                        node,
                        status,
                        message,
                        data_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        event_type,
                        node,
                        status,
                        message,
                        self._json(data or {}),
                        _now(),
                    ),
                )

                return int(cursor.lastrowid)

    def save_workflow_event(
        self,
        case_id: str,
        event: dict[str, Any],
    ) -> int:
        return self.add_workflow_event(
            case_id=case_id,
            event_type=str(
                event.get("event_type")
                or event.get("type")
                or "workflow"
            ),
            node=event.get("node"),
            status=event.get("status"),
            message=event.get("message"),
            data=event,
        )

    def get_workflow_events(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM workflow_events
                WHERE case_id = ?
                ORDER BY id ASC
                """,
                (case_id,),
            ).fetchall()

        results = []

        for row in rows:
            item = dict(row)

            item["data"] = self._from_json(
                item.pop("data_json", "{}"),
                {},
            )

            results.append(item)

        return results

    # Compatibility alias
    def get_case_events(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        return self.get_workflow_events(case_id)

    # ------------------------------------------------------------------
    # Human reviews
    # ------------------------------------------------------------------

    def add_human_review(
        self,
        case_id: str,
        action: str,
        reviewer: str | None = None,
        comment: str | None = None,
        decision: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO human_reviews (
                        case_id,
                        action,
                        reviewer,
                        comment,
                        decision,
                        data_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        action,
                        reviewer,
                        comment,
                        decision,
                        self._json(data or {}),
                        _now(),
                    ),
                )

                return int(cursor.lastrowid)

    def get_human_reviews(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM human_reviews
                WHERE case_id = ?
                ORDER BY id ASC
                """,
                (case_id,),
            ).fetchall()

        results = []

        for row in rows:
            item = dict(row)

            item["data"] = self._from_json(
                item.pop("data_json", "{}"),
                {},
            )

            results.append(item)

        return results

    # Compatibility alias
    def get_case_reviews(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        return self.get_human_reviews(case_id)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1").fetchone()

            return {
                "status": "healthy",
                "database": str(self.db_path),
            }

        except Exception as exc:
            return {
                "status": "unhealthy",
                "database": str(self.db_path),
                "error": str(exc),
            }


# ----------------------------------------------------------------------
# Global store
# ----------------------------------------------------------------------

state_store = StateStore()