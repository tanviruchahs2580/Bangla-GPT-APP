"""SQLAlchemy models: identity (split out of db/models.py, C-03)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Mapped, mapped_column

from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models.base import (  # noqa: F401
    _utcnow as _utcnow,
)
from bangla_gpt_api.db.types import UtcDateTime


class User(Base):
    __tablename__ = "users"
    #: H-04: value invariants that lived only in Pydantic/routes, now enforced
    #: by the database so a script, migration or repair cannot write a row the
    #: API would then serve.
    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'teacher', 'parent', 'admin', 'school_admin')",
            name="ck_users_role",
        ),
        CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16))
    # school tenancy for staff accounts. NULL keeps pre-school-layer
    # accounts (and the shared default school) working unchanged.
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id"), nullable=True, index=True
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa_false()
    )
    # Email verification: only enforced when SMTP delivery is configured;
    # otherwise accounts are auto-verified at registration.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=sa_true()
    )
    # AUTH-001: TOTP secret (base32). NULL = MFA disabled. The secret is only
    # stored after the user proves possession (verify step), never at enroll.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # F-05 token epoch: set at password change/reset. Any access token whose
    # ``iat`` is <= this moment is refused by get_current_user, so existing
    # sessions cannot ride out a credential rotation.
    sessions_invalidated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # S-002: per-account failed-login lockout. ``failed_login_count`` counts
    # consecutive password failures (reset to 0 by a successful sign-in);
    # ``locked_until`` is naive UTC (the SQLite column has no tzinfo) and is
    # stamped once the counter crosses the threshold, doubling for every
    # further failure up to the cap.
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Only the SHA-256 hash of the single-use token is persisted.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class EmailVerification(Base):
    """Single-use email verification token (hash stored, like resets)."""

    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class AuditLog(Base):
    """append-only trail for the five privileged event types:
    role_change, data_export, purge, qp_finalize, impersonation.

    Privacy: only ids and outcome metadata live in ``detail`` --
    never message content, never PII. Rows are never updated or deleted,
    with ONE documented exception: account erasure (DELETE /users/me)
    anonymises ``actor_user_id`` to NULL so the event survives the account
    while the erased person is no longer attributable (the column is
    nullable by design for this case).
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class EmailBounce(Base):
    """H-11: suppression ledger for undeliverable recipients.

    Only the SHA-256 of the lowercased address is stored -- the ledger can
    suppress a bounced guardian without keeping a second copy of PII, and a
    hash is enough to match the recipient of every later send. ``reason`` is
    the operator-readable summary of the DSN status/diagnostic (never a
    message body). A row is never deleted by the app: suppression is the
    product decision, and the retention sweep leaves it alone.
    """

    __tablename__ = "email_bounces"
    __table_args__ = (
        UniqueConstraint("recipient_hash", name="uq_email_bounces_recipient_hash"),
        CheckConstraint("bounce_count >= 1", name="ck_email_bounces_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bounce_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    first_bounced_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    last_bounced_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
