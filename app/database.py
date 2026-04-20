import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(os.getenv("SQLITE_DB_PATH", "reviews.db")).resolve()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
SUPABASE_TABLE = os.getenv("SUPABASE_REVIEW_TABLE", "review_requests").strip() or "review_requests"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _using_supabase() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _supabase_headers(*, prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _supabase_request(
    *,
    method: str,
    query: dict[str, str] | None = None,
    payload: Any = None,
    prefer: str | None = None,
) -> Any:
    if not _using_supabase():
        raise RuntimeError("Supabase is not configured")

    query_string = urlencode(query or {})
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    if query_string:
        url = f"{url}?{query_string}"

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = Request(url, data=body, method=method.upper())
    for key, value in _supabase_headers(prefer=prefer).items():
        request.add_header(key, value)

    try:
        with urlopen(request, timeout=20) as response:
            raw_body = response.read().decode("utf-8")
            if not raw_body:
                return None
            return json.loads(raw_body)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Supabase HTTP error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase network error: {exc}") from exc


def _supabase_first_or_none(rows: Any) -> dict[str, Any] | None:
    if isinstance(rows, list) and rows:
        first = rows[0]
        return first if isinstance(first, dict) else None
    return None


def _sqlite_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def _sqlite_execute(
    query: str,
    params: tuple[Any, ...] = (),
    *,
    fetchone: bool = False,
    fetchall: bool = False,
    commit: bool = False,
) -> Any:
    with _sqlite_connect() as connection:
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
    if _using_supabase():
        return

    with _sqlite_connect() as connection:
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

    if _using_supabase():
        rows = _supabase_request(
            method="POST",
            query={"select": "*"},
            payload=payload,
            prefer="return=representation",
        )
        row = _supabase_first_or_none(rows)
        if not row:
            raise RuntimeError("Supabase insert returned no row")
        return row

    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    values = tuple(payload.values())
    row_id = _sqlite_execute(
        f"INSERT INTO review_requests ({columns}) VALUES ({placeholders})",
        values,
        commit=True,
    )
    return get_review_by_id(int(row_id))


def update_review_request_by_token(token: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return get_review_by_token(token)

    if _using_supabase():
        rows = _supabase_request(
            method="PATCH",
            query={
                "unique_token": f"eq.{token}",
                "select": "*",
            },
            payload=payload,
            prefer="return=representation",
        )
        row = _supabase_first_or_none(rows)
        return row if row else get_review_by_token(token)

    assignments = ", ".join(f"{column} = ?" for column in payload.keys())
    values = tuple(payload.values()) + (token,)
    _sqlite_execute(
        f"UPDATE review_requests SET {assignments} WHERE unique_token = ?",
        values,
        commit=True,
    )
    return get_review_by_token(token)


def get_review_by_token(token: str) -> dict[str, Any] | None:
    if _using_supabase():
        rows = _supabase_request(
            method="GET",
            query={
                "select": "*",
                "unique_token": f"eq.{token}",
                "limit": "1",
            },
        )
        return _supabase_first_or_none(rows)

    return _sqlite_execute(
        "SELECT * FROM review_requests WHERE unique_token = ?",
        (token,),
        fetchone=True,
    )


def get_review_by_id(row_id: int) -> dict[str, Any] | None:
    if _using_supabase():
        rows = _supabase_request(
            method="GET",
            query={
                "select": "*",
                "id": f"eq.{row_id}",
                "limit": "1",
            },
        )
        return _supabase_first_or_none(rows)

    return _sqlite_execute(
        "SELECT * FROM review_requests WHERE id = ?",
        (row_id,),
        fetchone=True,
    )


def get_reviews(order_desc: bool = True) -> list[dict[str, Any]]:
    if _using_supabase():
        order_direction = "desc" if order_desc else "asc"
        rows = _supabase_request(
            method="GET",
            query={
                "select": "*",
                "order": f"created_at.{order_direction},id.{order_direction}",
            },
        )
        return rows if isinstance(rows, list) else []

    direction = "DESC" if order_desc else "ASC"
    return _sqlite_execute(
        f"SELECT * FROM review_requests ORDER BY datetime(created_at) {direction}, id {direction}",
        fetchall=True,
    )


def get_review_status_rows() -> list[dict[str, Any]]:
    if _using_supabase():
        rows = _supabase_request(
            method="GET",
            query={"select": "status"},
        )
        return rows if isinstance(rows, list) else []

    return _sqlite_execute("SELECT status FROM review_requests", fetchall=True)


def find_review_by_external_event(
    external_source: str | None,
    external_event_id: str | None,
) -> dict[str, Any] | None:
    if not external_source or not external_event_id:
        return None

    if _using_supabase():
        rows = _supabase_request(
            method="GET",
            query={
                "select": "*",
                "external_source": f"eq.{external_source}",
                "external_event_id": f"eq.{external_event_id}",
                "order": "id.desc",
                "limit": "1",
            },
        )
        return _supabase_first_or_none(rows)

    return _sqlite_execute(
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
