"""school + classroom tenancy tables with class_level backfill

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-06

S2.1: School, ClassRoom(school_id, class_level, section), ClassStudent,
ClassTeacher. Backfill: a single default school is created when students
exist, one classroom per distinct (class_level) with section 'GEN', and
every existing student is enrolled into the classroom matching its own
class_level. Teachers are NOT auto-assigned (no per-class teacher data
exists yet); stage 2 UI assigns them explicitly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_SCHOOL_CODE = "BGPT-DEFAULT"
DEFAULT_SECTION = "GEN"


def upgrade() -> None:
    op.create_table(
        "schools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_school_code"),
    )
    op.create_index(op.f("ix_schools_code"), "schools", ["code"], unique=False)

    op.create_table(
        "classrooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=8), server_default="GEN", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "class_level", "section", name="uq_classroom_school_level_section"),
    )
    op.create_index(op.f("ix_classrooms_school_id"), "classrooms", ["school_id"], unique=False)

    op.create_table(
        "class_students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("classroom_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("classroom_id", "student_id", name="uq_class_student"),
        sa.UniqueConstraint("student_id", name="uq_class_student_single_class"),
    )
    op.create_index(op.f("ix_class_students_classroom_id"), "class_students", ["classroom_id"], unique=False)
    op.create_index(op.f("ix_class_students_student_id"), "class_students", ["student_id"], unique=False)

    op.create_table(
        "class_teachers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("classroom_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"]),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("classroom_id", "teacher_id", "subject", name="uq_class_teacher"),
    )
    op.create_index(op.f("ix_class_teachers_classroom_id"), "class_teachers", ["classroom_id"], unique=False)
    op.create_index(op.f("ix_class_teachers_teacher_id"), "class_teachers", ["teacher_id"], unique=False)

    # --- backfill: default school + one GEN classroom per used class_level ---
    conn = op.get_bind()
    levels = [row[0] for row in conn.execute(sa.text("SELECT DISTINCT class_level FROM students ORDER BY class_level"))]
    if not levels:
        return
    conn.execute(
        sa.text("INSERT INTO schools (name, code, created_at) VALUES (:name, :code, CURRENT_TIMESTAMP)"),
        {"name": "Default School", "code": DEFAULT_SCHOOL_CODE},
    )
    school_id = conn.execute(
        sa.text("SELECT id FROM schools WHERE code = :code"), {"code": DEFAULT_SCHOOL_CODE}
    ).scalar_one()
    room_ids: dict[int, int] = {}
    for level in levels:
        conn.execute(
            sa.text(
                "INSERT INTO classrooms (school_id, class_level, section, created_at)"
                " VALUES (:sid, :lvl, :sec, CURRENT_TIMESTAMP)"
            ),
            {"sid": school_id, "lvl": level, "sec": DEFAULT_SECTION},
        )
        room_ids[level] = conn.execute(
            sa.text("SELECT id FROM classrooms WHERE school_id = :sid AND class_level = :lvl AND section = :sec"),
            {"sid": school_id, "lvl": level, "sec": DEFAULT_SECTION},
        ).scalar_one()
    for level, room_id in room_ids.items():
        conn.execute(
            sa.text(
                "INSERT INTO class_students (classroom_id, student_id, created_at)"
                " SELECT :rid, id, CURRENT_TIMESTAMP FROM students WHERE class_level = :lvl"
            ),
            {"rid": room_id, "lvl": level},
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_class_teachers_teacher_id"), table_name="class_teachers")
    op.drop_index(op.f("ix_class_teachers_classroom_id"), table_name="class_teachers")
    op.drop_table("class_teachers")
    op.drop_index(op.f("ix_class_students_student_id"), table_name="class_students")
    op.drop_index(op.f("ix_class_students_classroom_id"), table_name="class_students")
    op.drop_table("class_students")
    op.drop_index(op.f("ix_classrooms_school_id"), table_name="classrooms")
    op.drop_table("classrooms")
    op.drop_index(op.f("ix_schools_code"), table_name="schools")
    op.drop_table("schools")
