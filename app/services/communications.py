import base64
import json
import os
import ssl
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi


def frontend_base_url() -> str:
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def google_review_url() -> str:
    return os.getenv(
        "GOOGLE_REVIEW_URL", "https://g.page/r/Cb5Nse1cQALuEBM/review"
    ).strip()


def _smtp_config() -> dict[str, Any]:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "username": os.getenv("SMTP_USERNAME", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_email": os.getenv("EMAIL_FROM", "").strip(),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    }


def _send_email_smtp(to_email: str, subject: str, body: str) -> dict[str, Any]:
    cfg = _smtp_config()
    if not cfg["host"] or not cfg["from_email"]:
        return {
            "success": False,
            "provider": "smtp",
            "detail": "SMTP not configured (set SMTP_HOST and EMAIL_FROM)",
        }

    message = EmailMessage()
    message["From"] = cfg["from_email"]
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        tls_context = ssl.create_default_context(cafile=certifi.where())
        # Avoid slow or hanging local FQDN lookups on some Windows machines.
        with smtplib.SMTP(
            cfg["host"],
            cfg["port"],
            local_hostname="localhost",
            timeout=20,
        ) as server:
            if cfg["use_tls"]:
                server.starttls(context=tls_context)
            if cfg["username"] and cfg["password"]:
                server.login(cfg["username"], cfg["password"])
            server.send_message(message)
    except Exception as exc:
        return {
            "success": False,
            "provider": "smtp",
            "detail": f"SMTP send failed: {exc}",
        }

    return {"success": True, "provider": "smtp", "detail": "Sent via SMTP"}


def _send_twilio_message(
    *,
    to_number: str,
    body: str,
    is_whatsapp: bool,
) -> dict[str, Any]:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_sms = os.getenv("TWILIO_FROM_SMS", "").strip()
    from_whatsapp = os.getenv("TWILIO_FROM_WHATSAPP", "").strip()

    if not account_sid or not auth_token:
        return {
            "success": False,
            "provider": "twilio",
            "detail": "Twilio not configured (set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)",
        }

    from_number = from_whatsapp if is_whatsapp else from_sms
    if not from_number:
        missing = "TWILIO_FROM_WHATSAPP" if is_whatsapp else "TWILIO_FROM_SMS"
        return {
            "success": False,
            "provider": "twilio",
            "detail": f"Twilio sender missing ({missing})",
        }

    to_value = to_number
    from_value = from_number
    if is_whatsapp:
        if not to_value.startswith("whatsapp:"):
            to_value = f"whatsapp:{to_value}"
        if not from_value.startswith("whatsapp:"):
            from_value = f"whatsapp:{from_value}"

    payload = urlencode({"To": to_value, "From": from_value, "Body": body}).encode(
        "utf-8"
    )
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    basic_auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode(
        "utf-8"
    )
    request = Request(url, data=payload, method="POST")
    request.add_header("Authorization", f"Basic {basic_auth}")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(request, timeout=20) as response:
            raw_body = response.read().decode("utf-8")
            parsed = json.loads(raw_body) if raw_body else {}
            sid = parsed.get("sid", "")
            return {
                "success": True,
                "provider": "twilio",
                "detail": "Sent via Twilio",
                "external_id": sid,
            }
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return {
            "success": False,
            "provider": "twilio",
            "detail": f"Twilio HTTP error {exc.code}: {detail}",
        }
    except URLError as exc:
        return {
            "success": False,
            "provider": "twilio",
            "detail": f"Twilio network error: {exc}",
        }
    except Exception as exc:
        return {
            "success": False,
            "provider": "twilio",
            "detail": f"Twilio send failed: {exc}",
        }


def send_channel_message(
    *,
    channel: str,
    client_name: str,
    client_email: str | None,
    client_phone: str | None,
    review_link: str,
    is_reminder: bool = False,
    reminder_number: int | None = None,
) -> dict[str, Any]:
    safe_name = client_name or "there"
    reminder_prefix = ""
    if is_reminder and reminder_number:
        reminder_prefix = f"Reminder #{reminder_number}: "

    message_text = (
        f"{reminder_prefix}Hi {safe_name}, please share your review for Urban Country Realty: "
        f"{review_link}"
    )

    channel_normalized = (channel or "").strip().lower()
    if channel_normalized not in {"email", "sms", "whatsapp"}:
        return {
            "success": False,
            "provider": "none",
            "detail": f"Unsupported channel: {channel}",
        }

    if channel_normalized == "email":
        if not client_email:
            return {
                "success": False,
                "provider": "smtp",
                "detail": "Client email required for email channel",
            }
        subject = "Urban Country Realty: Please share your review"
        if is_reminder and reminder_number:
            subject = f"Reminder #{reminder_number}: Please share your review"
        return _send_email_smtp(client_email, subject, message_text)

    if not client_phone:
        return {
            "success": False,
            "provider": "twilio",
            "detail": "Client phone required for SMS/WhatsApp channel",
        }

    return _send_twilio_message(
        to_number=client_phone,
        body=message_text,
        is_whatsapp=channel_normalized == "whatsapp",
    )


def send_admin_alert(subject: str, body: str) -> dict[str, Any]:
    recipients = [
        email.strip()
        for email in os.getenv("ADMIN_ALERT_EMAIL", "").split(",")
        if email.strip()
    ]
    if not recipients:
        return {
            "success": False,
            "provider": "smtp",
            "detail": "ADMIN_ALERT_EMAIL not configured",
        }

    results: list[dict[str, Any]] = []
    for recipient in recipients:
        results.append(_send_email_smtp(recipient, subject, body))

    all_sent = all(result.get("success") for result in results)
    return {
        "success": all_sent,
        "provider": "smtp",
        "detail": "All admin alerts sent" if all_sent else "One or more admin alerts failed",
        "results": results,
    }
