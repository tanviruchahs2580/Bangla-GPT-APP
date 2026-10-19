"""SMTP mailer: transactional transport, template copy and the bounce path.

Transport contract (unchanged): :func:`send_mail` returns ``True`` when the
relay accepted the message and ``False`` (with one log line) on any SMTP or
socket failure. It never raises into a request handler, and a failed send is
the caller's decision to surface.

What this module adds (AUD-HI-17 / H-11):

* **Bilingual copy** -- :data:`EMAIL_TEMPLATES` holds subject and body for
  every mail the product sends, in ``bn`` and ``en``, selected per recipient
  (:func:`normalize_language` falls back to ``bn``); the audit found
  Bangladesh-first subjects with Bangla-only bodies and no way to serve an
  English-speaking guardian.
* **Suppression ledger** -- a recipient that hard-bounced is remembered in
  ``email_bounces`` (SHA-256 of the lowercased address, never the address
  itself) and :func:`send_mail_checked` refuses further bulk mail to it.
* **Bounce ingestion** -- :func:`parse_bounce_message` understands an RFC 3464
  multipart/report DSN and the ``X-Failed-Recipients`` header a
  provider-style bounce carries; :func:`ingest_bounce_message` records the
  failures; :func:`ingest_bounces_via_imap` polls the bounce mailbox with the
  standard library. A provider webhook can hand its raw payload to the same
  ingest function.

Only *bulk* mail is suppressed (the weekly digest). Transactional mail a user
explicitly asked for -- password reset, email verification -- is deliberately
NOT routed through the suppression check: a bounced address that later
recovers must not be locked out of a password reset.
"""

from __future__ import annotations

import hashlib
import imaplib
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email import message_from_bytes, message_from_string
from email.message import EmailMessage, Message
from email.policy import default as default_policy
from email.utils import parseaddr
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.clock import utcnow

logger = logging.getLogger(__name__)

#: Languages the templates cover; anything else falls back to Bengali.
SUPPORTED_LANGUAGES = ("bn", "en")
DEFAULT_LANGUAGE = "bn"


@dataclass(frozen=True)
class Template:
    subject: str
    body: str


#: name -> language -> template. ASCII-escaped Bengali keeps the module
#: byte-safe; the fields are ``str.format`` placeholders.
EMAIL_TEMPLATES: dict[str, dict[str, Template]] = {
    # Weekly parent digest (bulk mail; suppressed after a hard bounce). The
    # dynamic per-child lines are pre-rendered by services/parent_digest.py
    # and arrive as {children}; every other line is fixed copy and lives here
    # so both languages stay in one reviewable place.
    "parent_digest": {
        "bn": Template(
            subject="\u09b8\u09be\u09aa\u09cd\u09a4\u09be\u09b9\u09bf\u0995 "
            "\u0985\u09ad\u09bf\u09ad\u09be\u09ac\u0995 "
            "\u09b8\u09be\u09b0\u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa / Weekly parent digest",
            body="\u09aa\u09cd\u09b0\u09bf\u09af\u09bc {parent_name},\n\n"
            "\u0985\u09ad\u09bf\u09ad\u09be\u09ac\u0995 "
            "\u09b8\u09be\u09aa\u09cd\u09a4\u09be\u09b9\u09bf\u0995 "
            "\u09b8\u09be\u09b0\u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa ({week_label})\n"
            "\u0986\u09aa\u09a8\u09be\u09b0 "
            "\u09b8\u09a8\u09cd\u09a4\u09be\u09a8\u09c7\u09b0 \u098f "
            "\u09b8\u09aa\u09cd\u09a4\u09be\u09b9\u09c7\u09b0 "
            "\u09b8\u09be\u09b0\u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa "
            "\u09a8\u09bf\u099a\u09c7 \u09a6\u09c7\u0993\u09af\u09bc\u09be "
            "\u09b9\u09b2\u09cb\u0964\n\n{children}\n\n"
            "\u098f\u0987 \u09b8\u09be\u09b0\u09b8\u0982\u0995\u09cd\u09b7\u09c7\u09aa\u09c7 "
            "\u09b6\u09c1\u09a7\u09c1 "
            "\u09aa\u09b0\u09bf\u09b8\u0982\u0996\u09cd\u09af\u09be\u09a8 "
            "\u0986\u099b\u09c7\u0964 \u0986\u09aa\u09a8\u09be\u09b0 "
            "\u09b8\u09a8\u09cd\u09a4\u09be\u09a8\u09c7\u09b0 "
            "\u09ac\u09cd\u09af\u0995\u09cd\u09a4\u09bf\u0997\u09a4 "
            "\u099f\u09bf\u0989\u099f\u09b0 \u0986\u09b2\u09be\u09aa\n"
            "\u0995\u0996\u09a8\u09cb\u0987 \u098f\u09a4\u09c7 "
            "\u09af\u09cb\u0997 \u0995\u09b0\u09be \u09b9\u09af\u09bc "
            "\u09a8\u09be \u09ac\u09be \u09b6\u09c7\u09af\u09bc\u09be\u09b0 "
            "\u0995\u09b0\u09be \u09b9\u09af\u09bc \u09a8\u09be\u0964\n\n"
            "\u09ac\u09be\u0982\u09b2\u09be GPT",
        ),
        "en": Template(
            subject="Weekly parent digest",
            body="Dear {parent_name},\n\n"
            "Weekly parent digest ({week_label})\n"
            "Your child's summary for this week is below.\n\n{children}\n\n"
            "This summary contains statistics only. Your child's private tutoring\n"
            "conversations are never added to it or shared.\n\n"
            "Bangla GPT",
        ),
    },
    # Password reset (transactional; never suppressed).
    "password_reset": {
        "bn": Template(
            subject="\u09aa\u09be\u09b8\u0993\u09af\u09bc\u09be\u09b0\u09cd\u09a1 "
            "\u09b0\u09bf\u09b8\u09c7\u099f",
            body="\u09aa\u09be\u09b8\u0993\u09af\u09bc\u09be\u09b0\u09cd\u09a1 "
            "\u09b0\u09bf\u09b8\u09c7\u099f \u0995\u09b0\u09a4\u09c7 "
            "\u09a8\u09bf\u099a\u09c7\u09b0 \u099f\u09cb\u0995\u09c7\u09a8\u099f\u09bf "
            "\u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09c1\u09a8 "
            "({minutes} \u09ae\u09bf\u09a8\u09bf\u099f\u09c7\u09b0 \u099c\u09a8\u09cd\u09af "
            "\u09ac\u09c8\u09a7):\n\n{token}\n",
        ),
        "en": Template(
            subject="Password reset",
            body="Use the token below to reset your password "
            "(valid for {minutes} minutes):\n\n{token}\n",
        ),
    },
    # Email verification (transactional; never suppressed).
    "email_verification": {
        "bn": Template(
            subject="\u0987\u09ae\u09c7\u09b2 "
            "\u09af\u09be\u099a\u09be\u0987 \u0995\u09b0\u09c1\u09a8",
            body="\u0987\u09ae\u09c7\u09b2 "
            "\u09af\u09be\u099a\u09be\u0987 \u0995\u09b0\u09a4\u09c7 "
            "\u09a8\u09bf\u099a\u09c7\u09b0 \u099f\u09cb\u0995\u09c7\u09a8\u099f\u09bf "
            "\u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09c1\u09a8 "
            "({minutes} \u09ae\u09bf\u09a8\u09bf\u099f\u09c7\u09b0 \u099c\u09a8\u09cd\u09af "
            "\u09ac\u09c8\u09a7):\n\n{token}\n",
        ),
        "en": Template(
            subject="Verify your email",
            body="Use the token below to verify your email "
            "(valid for {minutes} minutes):\n\n{token}\n",
        ),
    },
}


def normalize_language(value: str | None) -> str:
    """Return a supported language code; unknown/empty falls back to ``bn``."""
    if value and value.strip().lower() in SUPPORTED_LANGUAGES:
        return value.strip().lower()
    return DEFAULT_LANGUAGE


def render(name: str, language: str | None, **fields: object) -> tuple[str, str]:
    """``(subject, body)`` for a template in ``language``; KeyError if unknown."""
    template = EMAIL_TEMPLATES[name][normalize_language(language)]
    return template.subject.format(**fields), template.body.format(**fields)


def subject(name: str, language: str | None, **fields: object) -> str:
    """The rendered subject alone (for callers with a dynamic body)."""
    return EMAIL_TEMPLATES[name][normalize_language(language)].subject.format(**fields)


def smtp_configured(settings: Settings) -> bool:
    return bool(settings.smtp_enabled and settings.smtp_host and settings.smtp_from)


def send_mail(settings: Settings, *, to: str, subject: str, body: str) -> bool:
    """Send an email over STARTTLS. Returns True when accepted by the relay."""
    if not smtp_configured(settings):
        return False
    host = settings.smtp_host or ""
    sender = settings.smtp_from or ""
    if not host or not sender:
        return False
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(host, settings.smtp_port, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.warning("smtp_delivery_failed", extra={"to_domain": to.split("@")[-1]})
        return False
    return True


# ── suppression ledger ────────────────────────────────────────────────


def recipient_hash(address: str) -> str:
    """SHA-256 of the normalized address -- what the ledger stores."""
    return hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()


def is_suppressed(db: Session, address: str) -> bool:
    """True when a hard bounce for this recipient is on the ledger."""
    from bangla_gpt_api.db.models import EmailBounce

    return (
        db.execute(
            select(EmailBounce.id).where(EmailBounce.recipient_hash == recipient_hash(address))
        ).scalar_one_or_none()
        is not None
    )


def record_bounce(db: Session, address: str, *, reason: str | None = None, now: Any = None) -> None:
    """Insert or re-stamp the suppression row. Does NOT commit (caller decides).

    ``reason`` is an operator-readable summary (status + diagnostic code),
    truncated to the column width; never a message body.
    """
    from bangla_gpt_api.db.models import EmailBounce

    stamp = now if now is not None else utcnow()
    digest = recipient_hash(address)
    row = db.execute(
        select(EmailBounce).where(EmailBounce.recipient_hash == digest)
    ).scalar_one_or_none()
    if row is None:
        db.add(
            EmailBounce(
                recipient_hash=digest,
                reason=(reason or None) and reason[:200],
                bounce_count=1,
                first_bounced_at=stamp,
                last_bounced_at=stamp,
            )
        )
        return
    row.bounce_count += 1
    row.last_bounced_at = stamp
    if reason:
        row.reason = reason[:200]


def send_mail_checked(db: Session, settings: Settings, *, to: str, subject: str, body: str) -> bool:
    """``send_mail`` for bulk mail: refuses a suppressed recipient.

    The refusal is logged with the same event name shape as a transport
    failure so an operator sees "why did this guardian stop receiving mail".
    """
    if is_suppressed(db, to):
        logger.warning("email_suppressed", extra={"to_domain": to.split("@")[-1], "kind": "bulk"})
        return False
    return send_mail(settings, to=to, subject=subject, body=body)


# ── bounce ingestion ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Bounce:
    """One failed recipient out of a DSN (or a provider bounce)."""

    address: str
    action: str  # ``failed`` for a hard bounce, ``delayed`` for a soft one
    status: str  # RFC 3463 status code, e.g. ``5.1.1``
    diagnostic: str  # relay's diagnostic text/code

    @property
    def is_hard(self) -> bool:
        return self.action == "failed" or self.status.startswith("5.")


def _address(value: str) -> str:
    """The bare address out of a DSN field or header value.

    RFC 3464 writes ``Final-Recipient: rfc822; user@example.com`` and
    ``parseaddr`` returns ``("", "")`` for that whole string -- the address
    type prefix must be dropped first. Header forms with a display name
    (``Name <user@example.com>``) go through ``parseaddr`` as usual.
    """
    candidate = value.strip()
    if ";" in candidate:
        candidate = candidate.split(";", 1)[1].strip()
    _name, addr = parseaddr(candidate)
    return addr or candidate.strip("<>").strip()


def _report_entries(message: Message) -> list[tuple[str, str, str, str]]:
    """(address, action, status, diagnostic) for every recipient a report names.

    Both shapes an operator meets are covered: the RFC 3464
    ``message/delivery-status`` blocks (per-recipient Action/Status) and the
    provider-style ``X-Failed-Recipients`` header, which carries no status.
    Soft notices are reported too, with ``action="delayed"`` -- the caller
    decides what a soft bounce means; only hard ones belong in the ledger.
    """
    entries: list[tuple[str, str, str, str]] = []

    header = message.get("X-Failed-Recipients")
    if header:
        for piece in str(header).split(","):
            addr = _address(piece)
            if addr:
                entries.append((addr, "failed", "", ""))

    for part in message.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        payload = part.get_payload()
        for block in payload if isinstance(payload, list) else []:
            if not hasattr(block, "get"):
                continue
            final = block.get("Final-Recipient")
            if not final:
                continue
            addr = _address(str(final))
            if not addr:
                continue
            action = str(block.get("Action") or "").strip().lower() or "failed"
            status = str(block.get("Status") or "").strip()
            diagnostic = str(block.get("Diagnostic-Code") or "").strip()
            entries.append((addr, action, status, diagnostic))
    return entries


def parse_bounce_message(raw: bytes | str) -> list[Bounce]:
    """Parse a raw bounce message into the recipients it names.

    Pure function: no DB, no network -- which is what makes the path testable
    with fixture DSNs in CI.
    """
    if isinstance(raw, bytes):
        message = message_from_bytes(raw, policy=default_policy)
    else:
        message = message_from_string(raw, policy=default_policy)
    return [
        Bounce(address=addr, action=action, status=status, diagnostic=diagnostic)
        for addr, action, status, diagnostic in _report_entries(message)
    ]


def ingest_bounce_message(db: Session, raw: bytes | str, *, now: Any = None) -> list[str]:
    """Record every failed recipient in ``raw``; commit; return the addresses.

    Hard bounces (``5.x``/``failed``) are suppressed. A soft bounce from this
    parser is not recorded -- the ledger is a hard-bounce list.
    """
    hard = [b for b in parse_bounce_message(raw) if b.is_hard]
    stamp = now if now is not None else utcnow()
    for bounce in hard:
        reason = " ".join(x for x in (bounce.status, bounce.diagnostic) if x) or bounce.action
        record_bounce(db, bounce.address, reason=reason, now=stamp)
    if hard:
        db.commit()
        logger.info("email_bounces_ingested", extra={"count": len(hard)})
    return [b.address for b in hard]


def ingest_bounces_via_imap(
    db: Session,
    *,
    host: str,
    user: str,
    password: str,
    port: int = 993,
    folder: str = "INBOX",
    limit: int = 50,
    server_factory: Any = None,
) -> list[str]:
    """Poll the bounce mailbox and ingest unread DSNs (stdlib imaplib).

    Ops runs this against the relay's bounce address; ``server_factory`` is
    the seam a test replaces with a fake IMAP server (process boundary).
    Messages are left in place and marked seen -- deletion is an operator
    decision, not this function's.
    """
    factory = server_factory or (lambda: imaplib.IMAP4_SSL(host, port))
    recorded: list[str] = []
    server = factory()
    try:
        server.login(user, password)
        server.select(folder)
        status, data = server.search(None, "UNSEEN")
        if status != "OK":
            logger.warning("imap_search_failed", extra={"folder": folder})
            return recorded
        # imaplib types message numbers as str (it encodes them itself);
        # SEARCH hands them back as bytes.
        message_ids = [raw.decode("ascii") for raw in (data[0] or b"").split()][:limit]
        for num in message_ids:
            status, fetched = server.fetch(num, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                continue
            payload = next((part[1] for part in fetched if isinstance(part, tuple)), None)
            if not payload:
                continue
            recorded.extend(ingest_bounce_message(db, payload))
            server.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            server.logout()
        except Exception:  # noqa: BLE001 - a failed logout must not mask the result
            logger.debug("imap_logout_failed")
    return recorded
