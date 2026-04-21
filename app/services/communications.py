import base64
import json
import os
import ssl
import smtplib
from functools import lru_cache
from html import escape
from email.message import EmailMessage
from pathlib import Path
from string import Template
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi


def frontend_base_url() -> str:
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def public_review_request_url() -> str:
    return os.getenv(
        "PUBLIC_REVIEW_REQUEST_URL",
        f"{frontend_base_url()}/office/urban-country-management",
    ).strip()


def public_asset_base_url() -> str:
    configured_base = os.getenv("PUBLIC_ASSET_BASE_URL", "").strip().rstrip("/")
    if configured_base:
        return configured_base

    parsed_url = urlparse(public_review_request_url())
    if parsed_url.scheme and parsed_url.netloc:
        return f"{parsed_url.scheme}://{parsed_url.netloc}"

    return frontend_base_url()


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


@lru_cache(maxsize=1)
def _review_request_email_template() -> Template:
    template_path = Path(__file__).resolve().parent.parent / "templates" / "review_request_email.html"
    return Template(template_path.read_text(encoding="utf-8"))


def _review_request_email_html(
    *,
    review_link: str,
    is_reminder: bool = False,
    reminder_number: int | None = None,
) -> str:
    safe_link = escape(review_link, quote=True)
    logo_url = escape(f"{public_asset_base_url()}/urban-country-logo.png", quote=True)

    return _review_request_email_template().substitute(
        logo_url=logo_url,
        review_link=safe_link,
    )


def _send_email_smtp(
    to_email: str,
    subject: str,
    body: str,
    *,
    html_body: str | None = None,
) -> dict[str, Any]:
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
    if html_body:
        message.add_alternative(html_body, subtype="html")

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

    outbound_link = public_review_request_url()
    message_text = (
        f"{reminder_prefix}Dear Sir/Madam,\n\n"
        "Thank you for choosing Urban Country Management. Please share your experience with us using the link below:\n\n"
        f"{outbound_link}\n\n"
        "Your feedback helps us improve our service."
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
        subject = "Urban Country Management: Please share your experience"
        if is_reminder and reminder_number:
            subject = "Urban Country Management: Please share your experience"
        html_message = _review_request_email_html(
            review_link=outbound_link,
            is_reminder=is_reminder,
            reminder_number=reminder_number,
        )
        return _send_email_smtp(client_email, subject, message_text, html_body=html_message)

    if not client_phone:
        return {
            "success": False,
            "provider": "twilio",
            "detail": "Client phone required for SMS/WhatsApp channel",
        }

    return _send_twilio_message(
        to_number=client_phone,
        body=(
            f"{reminder_prefix}Dear Sir/Madam, please share your experience with Urban Country Management: "
            f"{outbound_link}"
        ),
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
