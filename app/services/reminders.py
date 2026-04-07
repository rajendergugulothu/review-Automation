import os
from datetime import datetime, timezone
from typing import Any

from app.database import get_reviews, update_review_request_by_token
from app.services.communications import frontend_base_url, send_channel_message


TERMINAL_STATUSES = {"completed", "feedback_received"}


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _first_reminder_hours() -> int:
    return int(os.getenv("REMINDER_FIRST_HOURS", "24"))


def _second_reminder_hours() -> int:
    return int(os.getenv("REMINDER_SECOND_HOURS", "72"))


def _review_link_for_token(token: str) -> str:
    return f"{frontend_base_url()}/rate/{token}"


def _safe_status(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return "request_sent"


def _optional_update(
    *,
    row: dict[str, Any],
    payload: dict[str, Any],
    reminder_number: int,
    delivery: dict[str, Any],
) -> None:
    now_iso = _utc_now().isoformat()
    if "last_channel_status" in row:
        payload["last_channel_status"] = "sent" if delivery.get("success") else "failed"
    if "last_channel_detail" in row:
        payload["last_channel_detail"] = delivery.get("detail", "")
    if "last_channel_provider" in row:
        payload["last_channel_provider"] = delivery.get("provider", "")
    if "last_channel_message_id" in row and delivery.get("external_id"):
        payload["last_channel_message_id"] = delivery.get("external_id")
    if "last_reminder_at" in row and delivery.get("success"):
        payload["last_reminder_at"] = now_iso
    if reminder_number == 1 and "first_reminder_sent_at" in row and delivery.get("success"):
        payload["first_reminder_sent_at"] = now_iso
    if reminder_number == 2 and "second_reminder_sent_at" in row and delivery.get("success"):
        payload["second_reminder_sent_at"] = now_iso


def process_due_reminders() -> dict[str, Any]:
    rows = get_reviews(order_desc=False)

    first_hours = _first_reminder_hours()
    second_hours = _second_reminder_hours()
    now = _utc_now()

    attempted = 0
    sent = 0
    failed = 0
    skipped = 0
    details: list[dict[str, Any]] = []

    for row in rows:
        token = row.get("unique_token")
        if not token:
            skipped += 1
            continue

        status = _safe_status(row.get("status"))
        if status in TERMINAL_STATUSES:
            skipped += 1
            continue

        created_at = _parse_iso(row.get("created_at"))
        if not created_at:
            skipped += 1
            continue

        age_hours = (now - created_at).total_seconds() / 3600
        reminder_number = None
        next_status = None
        if status in {"request_sent", "request_failed"} and age_hours >= first_hours:
            reminder_number = 1
            next_status = "reminder_24_sent"
        elif status == "reminder_24_sent" and age_hours >= second_hours:
            reminder_number = 2
            next_status = "reminder_72_sent"

        if reminder_number is None or next_status is None:
            skipped += 1
            continue

        attempted += 1
        delivery = send_channel_message(
            channel=row.get("channel", "email"),
            client_name=row.get("client_name", ""),
            client_email=row.get("client_email"),
            client_phone=row.get("client_phone"),
            review_link=_review_link_for_token(token),
            is_reminder=True,
            reminder_number=reminder_number,
        )

        payload: dict[str, Any] = {}
        if delivery.get("success"):
            payload["status"] = next_status
            sent += 1
        else:
            failed += 1

        _optional_update(
            row=row,
            payload=payload,
            reminder_number=reminder_number,
            delivery=delivery,
        )

        if payload:
            update_review_request_by_token(token, payload)

        details.append(
            {
                "token": token,
                "status_before": status,
                "status_after": payload.get("status", status),
                "reminder_number": reminder_number,
                "channel": row.get("channel"),
                "delivery": delivery,
            }
        )

    return {
        "attempted": attempted,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "first_reminder_hours": first_hours,
        "second_reminder_hours": second_hours,
        "details": details,
    }
