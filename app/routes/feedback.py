import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_review_by_token, update_review_request_by_token
from app.services.communications import send_admin_alert

router = APIRouter()


class FeedbackSubmission(BaseModel):
    token: str
    feedback: str
    name: str | None = None
    email: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_email(value: str) -> bool:
    return bool(re.match(r"^\S+@\S+\.\S+$", value))


@router.post("/submit-feedback")
def submit_feedback(data: FeedbackSubmission):
    name = data.name.strip() if data.name else ""
    email = data.email.strip() if data.email else ""
    feedback = data.feedback.strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="Feedback is required")

    row = get_review_by_token(data.token)
    if not row:
        raise HTTPException(status_code=404, detail="Invalid token")
    resolved_name = name or row.get("client_name") or "Valued customer"
    resolved_email = email or row.get("client_email") or ""
    if resolved_email and not _validate_email(resolved_email):
        raise HTTPException(status_code=400, detail="Email is invalid")

    update_payload = {"status": "feedback_received"}

    if "client_name" in row and resolved_name:
        update_payload["client_name"] = resolved_name
    if "client_email" in row and resolved_email:
        update_payload["client_email"] = resolved_email
    if "feedback_submitted_at" in row:
        update_payload["feedback_submitted_at"] = _now_iso()

    # Some deployments may not have a dedicated feedback text column yet.
    for candidate in ("feedback", "internal_feedback", "notes", "comment"):
        if candidate in row:
            update_payload[candidate] = feedback
            break

    try:
        update_review_request_by_token(data.token, update_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    send_admin_alert(
        subject="Internal Feedback Received",
        body=(
            f"Client: {resolved_name}\n"
            f"Email: {resolved_email or 'Not provided'}\n"
            f"Token: {data.token}\n"
            f"Feedback:\n{feedback}"
        ),
    )

    return {"message": "Feedback submitted successfully"}
