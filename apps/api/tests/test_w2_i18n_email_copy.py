"""F-107: verification mail copy follows the account's language.

The subject was a single module constant and the body was Bangla-only, so an
English-preference account (teacher, admin, or the parent who reads English)
received a mail it could not read. These tests pin the selection, the
unresolved-language fallback, and the RFC 2047 encoding of the Bangla copy --
including a Bangla display name in the To header, which was correct but
untested.
"""

from __future__ import annotations

import email
import email.header
import email.policy
from typing import ClassVar

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.services import mailer
from bangla_gpt_api.services.verification import (
    VERIFICATION_SUBJECT_UNRESOLVED,
    verification_email_copy,
)

TOKEN = "tok_abcdefghijklmnopqrstuvwxyz012345"


def _decoded(header: str | None) -> str:
    """The header text a mail client displays (RFC 2047 whitespace rule)."""
    return str(email.header.make_header(email.header.decode_header(header or "")))


def test_bangla_copy_is_selected_for_bn_tags() -> None:
    for tag in ("bn", "bn-BD", "BN-bd"):
        subject, body = verification_email_copy(tag, TOKEN)
        assert subject == "ইমেইল যাচাই"
        assert "ইমেইল যাচাই করতে" in body
        assert TOKEN in body
        assert "24 ঘণ্টা" in body


def test_english_copy_is_selected_for_en_tags() -> None:
    for tag in ("en", "en-GB", "en-US"):
        subject, body = verification_email_copy(tag, TOKEN)
        assert subject == "Verify your email"
        assert "verify your email" in body
        assert TOKEN in body
        assert not any("\u0980" <= char <= "\u09ff" for char in subject + body)


def test_unresolved_language_keeps_the_shipped_bilingual_mail() -> None:
    for tag in (None, "", "fr", "bn_Bn"):
        subject, body = verification_email_copy(tag, TOKEN)
        assert subject == VERIFICATION_SUBJECT_UNRESOLVED
        assert "ইমেইল যাচাই করতে" in body


def test_unknown_tag_does_not_leak_into_the_subject() -> None:
    subject, _ = verification_email_copy("de-DE", TOKEN)
    assert "de" not in subject


class _CapturingSMTP:
    """SMTP stand-in that records the bytes ``send_message`` would transmit."""

    sent: ClassVar[list[bytes]] = []

    def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
        self.host = host
        self.port = port

    def __enter__(self) -> _CapturingSMTP:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self, context: object | None = None) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        return None

    def send_message(self, message: email.message.EmailMessage) -> None:
        _CapturingSMTP.sent.append(message.as_bytes())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        smtp_enabled=True,
        smtp_host="smtp.example.edu.bd",
        smtp_from="no-reply@example.edu.bd",
    )


def test_bangla_subject_and_name_are_rfc2047_encoded(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _CapturingSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _CapturingSMTP)
    subject, body = verification_email_copy("bn", TOKEN)

    assert mailer.send_mail(
        settings,
        to="মোছাম্মৎ নূরজাহান বেগম <nurjahan@example.edu.bd>",
        subject=subject,
        body=body,
    )

    raw = _CapturingSMTP.sent[0]
    assert b"=?utf-8?" in raw, raw[:200]
    parsed = email.message_from_bytes(raw)
    assert _decoded(parsed["Subject"]) == subject
    # Decode the name by the RFC 2047 display procedure: a long Bangla name is
    # split into several adjacent encoded words and the whitespace between them
    # is to be dropped. `email.policy.default` does not drop it (it returns
    # "নূরজাহ ান"), so asserting its string would pin a parser artefact
    # instead of the mail contract; make_header() implements the rule.
    assert _decoded(parsed["To"]) == "মোছাম্মৎ নূরজাহান বেগম <nurjahan@example.edu.bd>"
    decoded = parsed.get_payload(decode=True).decode("utf-8")
    assert TOKEN in decoded
    assert "স্বাগতম" in decoded


def test_english_subject_survives_the_wire(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _CapturingSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _CapturingSMTP)
    subject, body = verification_email_copy("en-US", TOKEN)

    assert mailer.send_mail(settings, to="teacher@example.edu.bd", subject=subject, body=body)

    parsed = email.message_from_bytes(_CapturingSMTP.sent[0])
    assert _decoded(parsed["Subject"]) == "Verify your email"
    assert TOKEN in parsed.get_payload(decode=True).decode("utf-8")
