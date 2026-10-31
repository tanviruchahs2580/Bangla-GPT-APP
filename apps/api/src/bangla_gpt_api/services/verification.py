"""Email-verification codes: one generator, one mail, every entry point.

Both account-creation paths must issue a code when SMTP delivery exists --
``/auth/register`` did, and ``/auth/join-school`` did not. The invited staff
member therefore got a working session and then a permanent 403
``email_unverified`` on every later sign-in, with no code ever sent.

The mail copy is selected by the caller's language (``lang``); an unresolved
language keeps the shipped bilingual subject so no account loses its Bangla
mail. The caller resolves the tag (request ``Accept-Language`` or a stored
preference) -- this module owns the copy, not the negotiation.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import EmailVerification, User
from bangla_gpt_api.services.mailer import send_mail

VERIFICATION_TTL_HOURS = 24

#: Subject for accounts whose language has not been resolved yet -- the
#: bilingual line every account received before language selection existed.
VERIFICATION_SUBJECT_UNRESOLVED = "ইমেইল যাচাই / Verify your email"


def verification_email_copy(lang: str | None, token: str) -> tuple[str, str]:
    """Subject and body for a verification code, in ``lang`` when supported.

    ``lang`` is a BCP 47 tag (``bn``, ``en``, ``bn-BD``); the region subtag is
    ignored. An English-preference account used to receive Bangla-only mail
    because a single module-level subject was mailed to everyone (F-107).
    A missing or unrecognised tag keeps the shipped bilingual subject and the
    Bangla body, so callers that have not resolved a language are unchanged.
    """
    tag = (lang or "").split("-")[0].lower()
    bangla_body = (
        "Bangla GPT Tutor-এ স্বাগতম! "
        "ইমেইল যাচাই করতে নিচের কোডটি "
        f"অ্যাপের ঘরে দিন ({VERIFICATION_TTL_HOURS} ঘণ্টা বৈধ):\n\n"
        f"{token}\n"
    )
    if tag == "en":
        return (
            "Verify your email",
            "Welcome to Bangla GPT Tutor! "
            "Enter this code in the app to verify your email "
            f"(valid for {VERIFICATION_TTL_HOURS} hours):\n\n"
            f"{token}\n",
        )
    if tag == "bn":
        return ("ইমেইল যাচাই", bangla_body)
    return (VERIFICATION_SUBJECT_UNRESOLVED, bangla_body)


def send_verification_email(
    db: Session, settings: Settings, user: User, *, lang: str | None = None
) -> None:
    """Issue a single-use code for ``user`` and mail it.

    Only the hash is stored; the plaintext code exists in the message and
    nowhere else. Delivery failures are the mailer's business (it logs and
    returns False), so the caller does not have to handle them.

    Any code still pending for this account is burned first, the way
    ``forgot_password`` already did for reset tokens. Without that, every
    ``/auth/resend-verification`` left another live 24-hour code behind and a
    code that leaked earlier stayed redeemable after the user asked for a fresh
    one -- so "resend" invalidated nothing. Doing it here covers every entry
    point at once (register, join-school, resend); for a first-time issue the
    pending set is empty and this is a no-op.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    pending = (
        db.execute(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.used_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    for row in pending:
        row.used_at = now

    token = secrets.token_urlsafe(32)
    db.add(
        EmailVerification(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=now + timedelta(hours=VERIFICATION_TTL_HOURS),
        )
    )
    db.commit()
    subject, body = verification_email_copy(lang, token)
    send_mail(
        settings,
        to=user.email,
        subject=subject,
        body=body,
    )
