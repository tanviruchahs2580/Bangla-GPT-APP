"""Email-verification codes: one generator, one mail, every entry point.

Both account-creation paths must issue a code when SMTP delivery exists --
``/auth/register`` did, and ``/auth/join-school`` did not. The invited staff
member therefore got a working session and then a permanent 403
``email_unverified`` on every later sign-in, with no code ever sent.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import EmailVerification, User
from bangla_gpt_api.services.mailer import send_mail

VERIFICATION_TTL_HOURS = 24
VERIFICATION_SUBJECT = "ইমেইল যাচাই / Verify your email"


def send_verification_email(db: Session, settings: Settings, user: User) -> None:
    """Issue a single-use code for ``user`` and mail it.

    Only the hash is stored; the plaintext code exists in the message and
    nowhere else. Delivery failures are the mailer's business (it logs and
    returns False), so the caller does not have to handle them.
    """
    token = secrets.token_urlsafe(32)
    db.add(
        EmailVerification(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(hours=VERIFICATION_TTL_HOURS),
        )
    )
    db.commit()
    send_mail(
        settings,
        to=user.email,
        subject=VERIFICATION_SUBJECT,
        body=(
            "Bangla GPT Tutor-এ স্বাগতম! "
            "ইমেইল যাচাই করতে নিচের কোডটি "
            f"অ্যাপের ঘরে দিন ({VERIFICATION_TTL_HOURS} ঘণ্টা বৈধ):\n\n"
            f"{token}\n"
        ),
    )
