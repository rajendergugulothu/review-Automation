import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(os.getenv("SQLITE_DB_PATH", "reviews.db")).resolve()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def _execute(
    query: str,
    params: tuple[Any, ...] = (),
    *,
    fetchone: bool = False,
    fetchall: bool = False,
    commit: bool = False,
) -> Any:
    with _connect() as connection:
        cursor = connection.execute(query, params)
        if commit:
            connection.commit()
        if fetchone:
            row = cursor.fetchone()
            return dict(row) if row else None
        if fetchall:
            return [dict(row) for row in cursor.fetchall()]
        return cursor.lastrowid


def init_db() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT,
                client_email TEXT,
                client_phone TEXT,
                event_type TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'email',
                unique_token TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'request_pending',
                office_code TEXT,
                rating INTEGER,
                feedback TEXT,
                internal_feedback TEXT,
                notes TEXT,
                comment TEXT,
                created_at TEXT NOT NULL,
                request_sent_at TEXT,
                first_reminder_sent_at TEXT,
                second_reminder_sent_at TEXT,
                last_reminder_at TEXT,
                review_submitted_at TEXT,
                feedback_submitted_at TEXT,
                last_channel_status TEXT,
                last_channel_detail TEXT,
                last_channel_provider TEXT,
                last_channel_message_id TEXT,
                external_source TEXT,
                external_event_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_review_requests_unique_token
                ON review_requests (unique_token);
            CREATE INDEX IF NOT EXISTS idx_review_requests_status
                ON review_requests (status);
            CREATE INDEX IF NOT EXISTS idx_review_requests_created_at
                ON review_requests (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_review_requests_office_code
                ON review_requests (office_code);
            CREATE INDEX IF NOT EXISTS idx_review_requests_external_event
                ON review_requests (external_source, external_event_id);
            CREATE INDEX IF NOT EXISTS idx_review_requests_status_created_at
                ON review_requests (status, created_at DESC);
            """
        )
        connection.commit()


def insert_review_request(insert_data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(insert_data)
    payload.setdefault("created_at", _utc_now_iso())
    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    values = tuple(payload.values())
    row_id = _execute(
        f"INSERT INTO review_requests ({columns}) VALUES ({placeholders})",
        values,
        commit=True,
    )
    return get_review_by_id(int(row_id))


def update_review_request_by_token(token: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return get_review_by_token(token)
    assignments = ", ".join(f"{column} = ?" for column in payload.keys())
    values = tuple(payload.values()) + (token,)
    _execute(
        f"UPDATE review_requests SET {assignments} WHERE unique_token = ?",
        values,
        commit=True,
    )
    return get_review_by_token(token)


def get_review_by_token(token: str) -> dict[str, Any] | None:
    return _execute(
        "SELECT * FROM review_requests WHERE unique_token = ?",
        (token,),
        fetchone=True,
    )


def get_review_by_id(row_id: int) -> dict[str, Any] | None:
    return _execute(
        "SELECT * FROM review_requests WHERE id = ?",
        (row_id,),
        fetchone=True,
    )


def get_reviews(order_desc: bool = True) -> list[dict[str, Any]]:
    direction = "DESC" if order_desc else "ASC"
    return _execute(
        f"SELECT * FROM review_requests ORDER BY datetime(created_at) {direction}, id {direction}",
        fetchall=True,
    )


def get_review_status_rows() -> list[dict[str, Any]]:
    return _execute("SELECT status FROM review_requests", fetchall=True)


def find_review_by_external_event(
    external_source: str | None,
    external_event_id: str | None,
) -> dict[str, Any] | None:
    if not external_source or not external_event_id:
        return None
    return _execute(
        """
        SELECT * FROM review_requests
        WHERE external_source = ? AND external_event_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (external_source, external_event_id),
        fetchone=True,
    )


init_db()
