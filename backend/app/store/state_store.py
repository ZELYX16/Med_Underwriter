import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


class StateStore:
    def __init__(self, database_path: str | Path | None = None):
        self.database_path = Path(
            database_path or settings.sqlite_path
        )

        if not self.database_path.is_absolute():
            self.database_path = (
                settings.base_path / self.database_path
            )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS underwriting_cases (
                    case_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (case_id)
                        REFERENCES underwriting_cases(case_id)
                );

                CREATE TABLE IF NOT EXISTS human_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    reviewer TEXT,
                    approved INTEGER,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (case_id)
                        REFERENCES underwriting_cases(case_id)
                );
                """
            )

    def save_case(
        self,
        case_id: str,
        state: dict[str, Any],
        status: str = "created",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO underwriting_cases (
                    case_id,
                    status,
                    state_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_id)
                DO UPDATE SET
                    status = excluded.status,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    case_id,
                    status,
                    json.dumps(
                        state,
                        default=str,
                    ),
                    now,
                    now,
                ),
            )

    def get_case(
        self,
        case_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    case_id,
                    status,
                    state_json,
                    created_at,
                    updated_at
                FROM underwriting_cases
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "case_id": row["case_id"],
            "status": row["status"],
            "state": json.loads(row["state_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def update_case_status(
        self,
        case_id: str,
        status: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE underwriting_cases
                SET status = ?,
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    status,
                    now,
                    case_id,
                ),
            )

    def add_workflow_event(
        self,
        case_id: str,
        node_name: str,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_events (
                    case_id,
                    node_name,
                    event_type,
                    event_data,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    node_name,
                    event_type,
                    json.dumps(
                        event_data or {},
                        default=str,
                    ),
                    now,
                ),
            )

    def get_workflow_events(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    case_id,
                    node_name,
                    event_type,
                    event_data,
                    created_at
                FROM workflow_events
                WHERE case_id = ?
                ORDER BY id ASC
                """,
                (case_id,),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "case_id": row["case_id"],
                "node_name": row["node_name"],
                "event_type": row["event_type"],
                "event_data": (
                    json.loads(row["event_data"])
                    if row["event_data"]
                    else {}
                ),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_human_review(
        self,
        case_id: str,
        reviewer: str,
        approved: bool,
        notes: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO human_reviews (
                    case_id,
                    reviewer,
                    approved,
                    notes,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    reviewer,
                    int(approved),
                    notes,
                    now,
                ),
            )

    def get_human_reviews(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    case_id,
                    reviewer,
                    approved,
                    notes,
                    created_at
                FROM human_reviews
                WHERE case_id = ?
                ORDER BY id ASC
                """,
                (case_id,),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "case_id": row["case_id"],
                "reviewer": row["reviewer"],
                "approved": bool(row["approved"]),
                "notes": row["notes"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


state_store = StateStore()