"""SQLAlchemy models: school (split out of db/models.py, C-03)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models.base import (  # noqa: F401
    _utcnow as _utcnow,
)
from bangla_gpt_api.db.types import UtcDateTime


class School(Base):
    """institution tenancy root; classrooms, teachers and students hang off it.

    The 2.1 migration backfills a single default school so pre-school-layer
    accounts keep working; stage 3 introduces school_admin-managed schools.
    """

    __tablename__ = "schools"
    __table_args__ = (UniqueConstraint("code", name="uq_school_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    #: uq_school_code already indexes this column; a second index was pure
    #: write overhead (H-04 prune).
    code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ClassRoom(Base):
    """a class (NCTB class_level + section) inside a school."""

    __tablename__ = "classrooms"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "class_level", "section", name="uq_classroom_school_level_section"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: school_id index pruned: uq_classroom_school_level_section leads with it.
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_level: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(8), default="GEN", server_default="GEN")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ClassStudent(Base):
    """enrollment linking a student to exactly one classroom (v1 rule)."""

    __tablename__ = "class_students"
    #: Both column-level indexes were redundant (H-04 prune): classroom_id is
    #: the prefix of uq_class_student, student_id is covered exactly by
    #: uq_class_student_single_class.
    __table_args__ = (
        UniqueConstraint("classroom_id", "student_id", name="uq_class_student"),
        UniqueConstraint("student_id", name="uq_class_student_single_class"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)


class ClassTeacher(Base):
    """teacher assignment to a classroom (optionally per subject)."""

    __tablename__ = "class_teachers"
    __table_args__ = (
        UniqueConstraint("classroom_id", "teacher_id", "subject", name="uq_class_teacher"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: classroom_id index pruned: uq_class_teacher leads with it (H-04).
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject: Mapped[str] = mapped_column(
        String(60), default="", server_default="", comment="'' means all subjects"
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_utcnow)
