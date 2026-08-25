"""Minimal SMTP mailer for transactional email (password reset).

Delivery failures are logged and reported as ``False``; they never raise
into request handlers. When SMTP is not configured the caller decides on a
fallback (e.g. console delivery in non-production).
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from bangla_gpt_api.config import Settings

logger = logging.getLogger(__name__)


def smtp_configured(settings: Settings) -> bool:
    return bool(settings.smtp_enabled and settings.smtp_host and settings.smtp_from)


def send_mail(settings: Settings, *, to: str, subject: str, body: str) -> bool:
    """Send an email over STARTTLS. Returns True when accepted by the relay."""
    if not smtp_configured(settings):
        return False
    assert settings.smtp_host is not None
    assert settings.smtp_from is not None
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.warning("smtp_delivery_failed", extra={"to_domain": to.split("@")[-1]})
        return False
    return True
