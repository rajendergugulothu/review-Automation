import hmac
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote_plus

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.database import (
    find_review_by_external_event,
    get_review_by_token,
    insert_review_request,
    update_review_request_by_token,
)
from app.services.communications import (
    frontend_base_url,
    google_review_url,
    send_admin_alert,
    send_channel_message,
)

router = APIRouter()

SUPPORTED_CHANNELS = {"email", "sms", "whatsapp"}
DEFAULT_OFFICE_NAME = "Urban Country Management"
DEFAULT_OFFICE_SLUG = "urban-country-management"
AUTOMATION_EVENT_TYPES = {
    "lease_signing": "lease_signing",
    "lease_signed": "lease_signing",
    "move_in": "move_in",
    "move_in_completed": "move_in",
    "work_order_completion": "work_order_completion",
    "work_order_completed": "work_order_completion",
    "lease_renewal": "lease_renewal",
    "lease_renewed": "lease_renewal",
}
class ReviewRequest(BaseModel):
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    event_type: str
    channel: str
    office_code: str | None = None


class AutomationTriggerRequest(BaseModel):
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    event_name: str
    channel: str
    office_code: str | None = None
    external_source: str = "automation"
    external_event_id: str | None = None


class OfficeReviewStart(BaseModel):
    name: str
    email: str
    phone: str | None = None
    event_type: str = "in_office"


class RatingSubmission(BaseModel):
    token: str
    rating: int
    name: str | None = None
    email: str | None = None
    feedback: str | None = None


class PublicRatingSubmission(BaseModel):
    rating: int
    name: str | None = None
    email: str | None = None
    office_code: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _channel_or_error(channel: str) -> str:
    channel_normalized = channel.strip().lower()
    if channel_normalized not in SUPPORTED_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel '{channel}'. Use email, sms, or whatsapp.",
        )
    return channel_normalized


def _validate_email(value: str) -> bool:
    return bool(re.match(r"^\S+@\S+\.\S+$", value))


def _event_type_or_error(event_name: str) -> str:
    event_normalized = event_name.strip().lower().replace("-", "_").replace(" ", "_")
    event_type = AUTOMATION_EVENT_TYPES.get(event_normalized)
    if not event_type:
        allowed = ", ".join(sorted(set(AUTOMATION_EVENT_TYPES.values())))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event '{event_name}'. Use one of: {allowed}.",
        )
    return event_type


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _default_office_name() -> str:
    return DEFAULT_OFFICE_NAME


def _default_office_slug() -> str:
    return DEFAULT_OFFICE_SLUG


def _office_name_for_storage(office_code: str | None) -> str:
    cleaned = _clean_optional_text(office_code)
    if not cleaned:
        return _default_office_name()
    if cleaned.lower().replace("-", " ") in {
        _default_office_slug().replace("-", " "),
        _default_office_name().lower(),
        "frisco",
    }:
        return _default_office_name()
    return cleaned


def _validate_request_contacts(
    *,
    channel: str,
    client_email: str | None,
    client_phone: str | None,
) -> None:
    if client_email and not _validate_email(client_email):
        raise HTTPException(status_code=400, detail="Client email is invalid")
    if channel == "email" and not client_email:
        raise HTTPException(status_code=400, detail="Client email is required for email")
    if channel in {"sms", "whatsapp"} and not client_phone:
        raise HTTPException(
            status_code=400, detail=f"Client phone is required for {channel}"
        )


def _apply_optional_message_fields(
    *,
    payload: dict,
    delivery: dict,
    is_request_send: bool = False,
) -> None:
    payload["last_channel_status"] = "sent" if delivery.get("success") else "failed"
    payload["last_channel_detail"] = delivery.get("detail", "")
    payload["last_channel_provider"] = delivery.get("provider", "")
    if delivery.get("external_id"):
        payload["last_channel_message_id"] = delivery.get("external_id")
    if is_request_send and delivery.get("success"):
        payload["request_sent_at"] = _now_iso()


def _find_existing_automation_request(
    *,
    external_source: str | None,
    external_event_id: str | None,
):
    return find_review_by_external_event(external_source, external_event_id)


def _review_link_for_token(token: str) -> str:
    return f"{frontend_base_url()}/rate/{token}"


def _review_alert_body(
    *,
    name: str,
    email: str,
    rating: int,
    token: str,
    office_code: str,
    event_type: str,
    channel: str,
) -> str:
    return (
        f"Client: {name or 'Not provided'}\n"
        f"Email: {email or 'Not provided'}\n"
        f"Rating: {rating}\n"
        f"Token: {token}\n"
        f"Office: {office_code}\n"
        f"Event: {event_type}\n"
        f"Original Channel: {channel}\n"
    )


def _notify_review_received(
    *,
    token: str,
    rating: int,
    name: str,
    email: str,
    office_code: str,
    event_type: str,
    channel: str,
) -> None:
    common_alert_body = _review_alert_body(
        name=name,
        email=email,
        rating=rating,
        token=token,
        office_code=office_code,
        event_type=event_type,
        channel=channel,
    )
    send_admin_alert(
        subject=f"New Review Received ({rating} stars)",
        body=common_alert_body,
    )
    if rating <= 3:
        send_admin_alert(
            subject=f"Negative Review Alert ({rating} stars)",
            body=common_alert_body + "\nAction: Follow up with the client immediately.",
        )


def _rating_redirect_payload(*, token: str, rating: int) -> dict:
    if rating <= 3:
        return {
            "type": "negative",
            "redirect_url": f"{frontend_base_url()}/internal-feedback?token={token}",
        }
    return {
        "type": "positive",
        "redirect_url": google_review_url(),
    }


def _create_review_request_record(
    *,
    client_name: str,
    client_email: str | None,
    client_phone: str | None,
    event_type: str,
    channel: str,
    office_code: str | None = None,
    external_source: str | None = None,
    external_event_id: str | None = None,
):
    channel_normalized = _channel_or_error(channel)
    safe_name = client_name.strip()
    safe_event_type = event_type.strip()
    safe_email = _clean_optional_text(client_email)
    safe_phone = _clean_optional_text(client_phone)
    safe_office_code = _office_name_for_storage(office_code)
    safe_external_source = _clean_optional_text(external_source)
    safe_external_event_id = _clean_optional_text(external_event_id)

    if not safe_name:
        raise HTTPException(status_code=400, detail="Client name is required")
    if not safe_event_type:
        raise HTTPException(status_code=400, detail="Event type is required")

    _validate_request_contacts(
        channel=channel_normalized,
        client_email=safe_email,
        client_phone=safe_phone,
    )

    existing_row = _find_existing_automation_request(
        external_source=safe_external_source,
        external_event_id=safe_external_event_id,
    )
    if existing_row:
        existing_token = existing_row.get("unique_token", "")
        return {
            "message": "Automation event already processed",
            "review_link": _review_link_for_token(existing_token) if existing_token else None,
            "token": existing_token or None,
            "delivery": {
                "success": existing_row.get("last_channel_status") == "sent",
                "provider": existing_row.get("last_channel_provider", ""),
                "detail": existing_row.get("last_channel_detail", "Duplicate automation event"),
                "external_id": existing_row.get("last_channel_message_id", ""),
            },
            "duplicate": True,
        }

    token = secrets.token_urlsafe(16)
    insert_data = {
        "client_name": safe_name,
        "client_email": safe_email,
        "client_phone": safe_phone,
        "event_type": safe_event_type,
        "channel": channel_normalized,
        "unique_token": token,
        "status": "request_pending",
    }
    insert_data["office_code"] = safe_office_code
    if safe_external_source:
        insert_data["external_source"] = safe_external_source
    if safe_external_event_id:
        insert_data["external_event_id"] = safe_external_event_id

    try:
        row = insert_review_request(insert_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not row:
        raise HTTPException(status_code=400, detail="Insert failed")
    review_link = _review_link_for_token(token)

    delivery = send_channel_message(
        channel=channel_normalized,
        client_name=safe_name,
        client_email=safe_email,
        client_phone=safe_phone,
        review_link=review_link,
    )

    update_payload = {"status": "request_sent" if delivery.get("success") else "request_failed"}
    _apply_optional_message_fields(payload=update_payload, delivery=delivery, is_request_send=True)
    try:
        update_review_request_by_token(token, update_payload)
    except Exception:
        # Keep request creation successful even when metadata update fails.
        pass

    return {
        "message": "Review request created",
        "review_link": review_link,
        "token": token,
        "delivery": delivery,
        "duplicate": False,
    }


def _automation_secret_or_error(x_automation_secret: str | None) -> None:
    expected_secret = os.getenv("AUTOMATION_SHARED_SECRET", "").strip()
    if not expected_secret:
        raise HTTPException(
            status_code=503,
            detail="Automation trigger is not configured",
        )
    provided_secret = (x_automation_secret or "").strip()
    if not provided_secret or not hmac.compare_digest(provided_secret, expected_secret):
        raise HTTPException(status_code=401, detail="Invalid automation secret")


@router.post("/create-review-request")
def create_review_request(data: ReviewRequest):
    return _create_review_request_record(
        client_name=data.client_name,
        client_email=data.client_email,
        client_phone=data.client_phone,
        event_type=data.event_type,
        channel=data.channel,
        office_code=data.office_code,
    )


@router.post("/automation/trigger-review")
def trigger_review_from_automation(
    data: AutomationTriggerRequest,
    x_automation_secret: str | None = Header(default=None),
):
    _automation_secret_or_error(x_automation_secret)

    result = _create_review_request_record(
        client_name=data.client_name,
        client_email=data.client_email,
        client_phone=data.client_phone,
        event_type=_event_type_or_error(data.event_name),
        channel=data.channel,
        office_code=data.office_code,
        external_source=data.external_source,
        external_event_id=data.external_event_id,
    )
    result["event_type"] = _event_type_or_error(data.event_name)
    return result


@router.post("/office/{office_code}/start-review")
def start_office_review(office_code: str, data: OfficeReviewStart):
    name = data.name.strip()
    email = data.email.strip()
    phone = data.phone.strip() if data.phone else None
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not _validate_email(email):
        raise HTTPException(status_code=400, detail="Email is invalid")

    token = secrets.token_urlsafe(16)
    insert_data = {
        "client_name": name,
        "client_email": email,
        "client_phone": phone,
        "event_type": data.event_type.strip() or "in_office",
        "channel": "email",
        "office_code": _office_name_for_storage(office_code),
        "unique_token": token,
        "status": "request_sent",
    }

    try:
        row = insert_review_request(insert_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not row:
        raise HTTPException(status_code=400, detail="Insert failed")

    return {
        "message": "Office review started",
        "review_link": f"{frontend_base_url()}/rate/{token}",
        "token": token,
        "office_code": _default_office_slug(),
        "office_name": _default_office_name(),
    }


@router.get("/office/{office_code}/qr")
def get_office_qr(office_code: str):
    if not office_code.strip():
        raise HTTPException(status_code=400, detail="office_code is required")

    landing_url = f"{frontend_base_url()}/office/{_default_office_slug()}"
    qr_image_url = (
        "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data="
        f"{quote_plus(landing_url)}"
    )
    return {
        "office_code": _default_office_slug(),
        "office_name": _default_office_name(),
        "landing_url": landing_url,
        "qr_image_url": qr_image_url,
    }


@router.get("/rate/{token}")
def rate_page(token: str):
    review = get_review_by_token(token)
    if not review:
        raise HTTPException(status_code=404, detail="Invalid review link")

    return {
        "message": "Valid review link",
        "token": token,
        "instruction": "Submit rating via /submit-rating endpoint",
    }


@router.post("/submit-rating")
def submit_rating(data: RatingSubmission):
    if data.rating < 1 or data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    name = data.name.strip() if data.name else ""
    email = data.email.strip() if data.email else ""
    feedback = data.feedback.strip() if data.feedback else ""
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not _validate_email(email):
        raise HTTPException(status_code=400, detail="Email is invalid")

    row = get_review_by_token(data.token)
    if not row:
        raise HTTPException(status_code=404, detail="Invalid token")
    update_payload = {
        "rating": data.rating,
        "status": "completed",
    }
    if row.get("client_name") is not None:
        update_payload["client_name"] = name
    if row.get("client_email") is not None:
        update_payload["client_email"] = email
    if "review_submitted_at" in row:
        update_payload["review_submitted_at"] = _now_iso()
    for candidate in ("feedback", "internal_feedback", "notes", "comment"):
        if candidate in row and feedback:
            update_payload[candidate] = feedback
            break

    update_review_request_by_token(data.token, update_payload)

    _notify_review_received(
        token=data.token,
        rating=data.rating,
        name=name,
        email=email,
        office_code=row.get("office_code", "n/a"),
        event_type=row.get("event_type", "n/a"),
        channel=row.get("channel", "n/a"),
    )
    return _rating_redirect_payload(token=data.token, rating=data.rating)


@router.post("/submit-public-rating")
def submit_public_rating(data: PublicRatingSubmission):
    if data.rating < 1 or data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    name = _clean_optional_text(data.name) or "Valued customer"
    email = _clean_optional_text(data.email) or ""
    if email and not _validate_email(email):
        raise HTTPException(status_code=400, detail="Email is invalid")

    token = secrets.token_urlsafe(16)
    insert_data = {
        "client_name": name,
        "client_email": email or None,
        "event_type": "manual_link",
        "channel": "email",
        "office_code": _office_name_for_storage(data.office_code),
        "unique_token": token,
        "status": "completed",
        "rating": data.rating,
    }

    try:
        row = insert_review_request(insert_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not row:
        raise HTTPException(status_code=400, detail="Insert failed")
    update_payload = {}
    if "review_submitted_at" in row:
        update_payload["review_submitted_at"] = _now_iso()
    if update_payload:
        update_review_request_by_token(token, update_payload)

    _notify_review_received(
        token=token,
        rating=data.rating,
        name=name,
        email=email,
        office_code=row.get("office_code", _default_office_name()),
        event_type=row.get("event_type", "manual_link"),
        channel=row.get("channel", "manual"),
    )
    return _rating_redirect_payload(token=token, rating=data.rating)
