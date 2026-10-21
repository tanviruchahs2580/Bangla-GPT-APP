"""SQLAlchemy models: people (split out of db/models.py, C-03)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
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


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("class_level BETWEEN 1 AND 12", name="ck_students_class_level"),
        CheckConstraint("length(name) > 0", name="ck_students_name_not_blank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    class_level: Mapped[int] = mapped_column(Integer)
    # per-student learning preferences and the memory opt-out flag.
    # Both are additive; existing rows keep working via the server defaults.
    # the JSON payload is a keyed dict (whitelisted keys:
    # explanation_style, subject_focus) -- annotation-only change of the
    # stale 'list' annotation; the column itself is untyped JSON, so NO
    # migration is needed.
    learning_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=sa_true()
    )
    # Guardian-consent evidence trail (child-safety compliance, D20).
    consent_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # free-form teacher UI/workflow preferences (dict, additive).
    prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class Parent(Base):
    __tablename__ = "parents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # notified (Fernet) whenever PII_ENC_KEY is
    # configured; None when no phone was given. Never logged, never exported.
    phone_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: H-11: user-level email preference. The weekly digest is the only bulk
    #: email the product sends; a guardian can opt out per account
    #: (transactional mail -- resets, verification -- is unaffected) and picks
    #: the digest language (bn | en).
    digest_opt_out: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=sa_false()
    )
    digest_language: Mapped[str] = mapped_column(
        String(2), default="bn", nullable=False, server_default="bn"
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ParentStudentLink(Base):
    __tablename__ = "parent_student_links"
    #: parent_id index pruned: uq_parent_student leads with it (H-04).
    __table_args__ = (UniqueConstraint("parent_id", "student_id", name="uq_parent_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ParentInvite(Base):
    """Single-use invite code a student generates so a parent can link."""

    __tablename__ = "parent_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Only the SHA-256 hash of the code is persisted (same scheme as resets).
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: FK index added by H-04 (parent erasure scans this column).
    used_by_parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("parents.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class StudentInvite(Base):
    """claim code for a student account created by class CSV import.

    The code doubles as the initial password: the created user has
    must_change_password=True, so signing in with the code forces setting a
    personal password. Only the SHA-256 hash of the code is stored (same
    scheme as parent invites / resets); the plaintext is returned once.
    """

    __tablename__ = "student_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class SchoolInvite(Base):
    """single-use, time-limited staff invite code for a school.

    Only the SHA-256 of the (uppercased, stripped) code is stored; the
    plaintext is returned exactly once at creation. Redemption stamps
    used_by/used_at, so a code can never be redeemed twice, and
    ``expires_at`` bounds its usable lifetime. Rows whose ``expires_at`` is
    NULL (pre-expiry schema) fail closed and are rejected as expired.
    """

    __tablename__ = "school_invites"
    __table_args__ = (
        CheckConstraint("role IN ('teacher', 'school_admin')", name="ck_school_invites_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="teacher")
    #: FK indexes added by H-04: both are read by the invite audit path.
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
