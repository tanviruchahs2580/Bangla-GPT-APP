"""Teacher Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import csv
import logging
import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.auth.security import (
    hash_password,
)
from bangla_gpt_api.db.models import (
    AnswerLog,
    ClassRoom,
    ClassStudent,
    QuizAttempt,
    School,
    Student,
    StudentInvite,
    User,
)
from bangla_gpt_api.schemas import (
    ChapterStat,
    ClassAnalytics,
    ClassImportIn,
    ClassImportOut,
    ClassImportRowOut,
    ClassRoomCreateIn,
    ClassRoomOut,
    RosterEntryOut,
    StudentBrief,
)

from .common import (
    _classroom_or_404,
    _default_school,
    _hash_invite,
    _load_class_students,
    _student_briefs,
)
from .deps import (
    DbSession,
    TeacherOrAdminUser,
    _assert_room_in_school,
    _tenant_school_id,
)

router = APIRouter()

logger = logging.getLogger(__name__)

IMPORT_CODE_TTL_DAYS = 30
IMPORT_MAX_ROWS = 200


@router.get("/teacher/students", response_model=list[StudentBrief])
def teacher_roster(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    class_level: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[StudentBrief]:
    # S5.5: capped (class_level omitted used to pull the whole student table).
    # Wave 2 tenancy: school-bound teachers only ever see their own school.
    students = _load_class_students(
        db, class_level, limit=limit, school_id=_tenant_school_id(teacher)
    )
    return _student_briefs(db, students)


@router.get("/teacher/classes/{class_level}/analytics", response_model=ClassAnalytics)
def teacher_analytics(
    class_level: int, db: DbSession, teacher: TeacherOrAdminUser
) -> ClassAnalytics:
    students = _load_class_students(db, class_level, school_id=_tenant_school_id(teacher))
    briefs = _student_briefs(db, students)

    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    if students:
        attempt_ids = [
            a.id
            for a in db.execute(
                select(QuizAttempt).where(
                    QuizAttempt.student_id.in_([s.id for s in students]),
                    QuizAttempt.status == "graded",
                )
            )
            .scalars()
            .all()
        ]
        if attempt_ids:
            rows = (
                db.execute(select(AnswerLog).where(AnswerLog.attempt_id.in_(attempt_ids)))
                .scalars()
                .all()
            )
            for row in rows:
                stats[row.chapter][0] += 1
                stats[row.chapter][1] += row.is_correct

    chapters = sorted(
        (
            ChapterStat(
                chapter=chapter,
                asked=asked,
                correct=correct_count,
                accuracy=round(100.0 * correct_count / asked, 2),
            )
            for chapter, (asked, correct_count) in stats.items()
        ),
        key=lambda s: s.accuracy,
    )

    return ClassAnalytics(
        class_level=class_level,
        students=len(students),
        chapters=chapters,
        weak_chapters=[c.chapter for c in chapters if c.accuracy < 60.0],
        students_detail=briefs,
    )


# --- S2.2: classroom management + CSV bulk import -------------------------


def _room_counts(db: Session) -> dict[int, int]:
    rows = cast(
        CursorResult[Any],
        db.execute(
            select(ClassStudent.classroom_id, func.count()).group_by(ClassStudent.classroom_id)
        ),
    )
    return {int(row[0]): int(row[1]) for row in rows.all()}


@router.get("/teacher/classrooms", response_model=list[ClassRoomOut])
def teacher_list_classrooms(db: DbSession, teacher: TeacherOrAdminUser) -> list[ClassRoomOut]:
    """S2.2: all classrooms with enrollment counts.

    Wave 2 tenancy: a teacher attached to a school only sees that school's
    rooms; school-less teachers and platform admins keep the old view.
    """
    statement = select(ClassRoom).order_by(ClassRoom.class_level, ClassRoom.section)
    tenant = _tenant_school_id(teacher)
    if tenant is not None:
        statement = statement.where(ClassRoom.school_id == tenant)
    rooms = db.execute(statement).scalars().all()
    counts = _room_counts(db)
    return [
        ClassRoomOut(
            id=r.id,
            class_level=r.class_level,
            section=r.section,
            student_count=counts.get(r.id, 0),
        )
        for r in rooms
    ]


@router.post("/teacher/classrooms", response_model=ClassRoomOut, status_code=201)
def teacher_create_classroom(
    payload: ClassRoomCreateIn, db: DbSession, teacher: TeacherOrAdminUser
) -> ClassRoomOut:
    # S3.1: teachers with a school create rooms inside it; legacy
    # school-less teachers keep using the default school.
    school = db.get(School, teacher.school_id) if teacher.school_id else None
    if school is None:
        school = _default_school(db)
    section = (payload.section or "").strip().upper() or "GEN"
    room = ClassRoom(school_id=school.id, class_level=payload.class_level, section=section)
    db.add(room)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="classroom exists") from None
    db.refresh(room)
    return ClassRoomOut(
        id=room.id, class_level=room.class_level, section=room.section, student_count=0
    )


@router.get("/teacher/classrooms/{room_id}/roster", response_model=list[RosterEntryOut])
def classroom_roster(
    room_id: int, db: DbSession, teacher: TeacherOrAdminUser
) -> list[RosterEntryOut]:
    room = _assert_room_in_school(teacher, _classroom_or_404(db, room_id))
    students = list(
        db.execute(
            select(Student)
            .join(ClassStudent, ClassStudent.student_id == Student.id)
            .where(ClassStudent.classroom_id == room.id)
            .order_by(Student.id)
        )
        .scalars()
        .all()
    )
    briefs = {b.student_id: b for b in _student_briefs(db, students)}
    emails: dict[int, str] = {}
    user_ids = [s.user_id for s in students if s.user_id is not None]
    if user_ids:
        emails = {
            u.id: u.email
            for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
        }
    pending: set[int] = set()
    if students:
        pending = set(
            db.execute(
                select(StudentInvite.student_id).where(
                    StudentInvite.student_id.in_([s.id for s in students]),
                    StudentInvite.used_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
    out: list[RosterEntryOut] = []
    for s in students:
        b = briefs[s.id]
        out.append(
            RosterEntryOut(
                student_id=s.id,
                name=s.name,
                class_level=s.class_level,
                email=emails.get(s.user_id) if s.user_id is not None else None,
                invite_pending=s.id in pending,
                attempts_graded=b.attempts_graded,
                avg_score_pct=b.avg_score_pct,
            )
        )
    return out


@router.post("/teacher/classrooms/{room_id}/import", response_model=ClassImportOut)
def classroom_import(
    room_id: int, payload: ClassImportIn, db: DbSession, teacher: TeacherOrAdminUser
) -> ClassImportOut:
    """Bulk-enroll students from pasted 'name,email' CSV text.

    Each new account gets a random invite code as its initial password;
    must_change_password=True forces setting a personal password on first
    login (existing /auth change-password flow). The plaintext code is
    returned exactly once -- only its SHA-256 hash is stored. The school
    supplies guardian consent on behalf of imported minors (R11): consent
    is recorded with version 'CSV-IMPORT-1'.
    """
    room = _assert_room_in_school(teacher, _classroom_or_404(db, room_id))
    reader = csv.reader(payload.csv_text.splitlines())
    data_rows: list[list[str]] = []
    for i, row in enumerate(reader):
        cells = [c.strip() for c in row]
        if i == 0 and cells and cells[0].lower() == "name":
            continue  # header
        if any(cells):
            data_rows.append(cells)
    if not data_rows:
        raise HTTPException(status_code=422, detail="no data rows")
    if len(data_rows) > IMPORT_MAX_ROWS:
        raise HTTPException(status_code=422, detail=f"max {IMPORT_MAX_ROWS} rows per import")
    created = 0
    rows_out: list[ClassImportRowOut] = []
    now = datetime.now(UTC)
    for cells in data_rows:
        name = cells[0]
        email = cells[1].lower() if len(cells) > 1 else ""
        domain = email.split("@")[-1] if "@" in email else ""
        if not name or not email or "@" not in email or "." not in domain:
            rows_out.append(ClassImportRowOut(name=name, email=email, status="invalid"))
            continue
        existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing is not None:
            rows_out.append(ClassImportRowOut(name=name, email=email, status="duplicate_email"))
            continue
        code = secrets.token_urlsafe(9)
        user = User(
            email=email,
            password_hash=hash_password(code),
            role="student",
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        student = Student(
            user_id=user.id,
            name=name,
            class_level=room.class_level,
            consent_version="CSV-IMPORT-1",
            consent_at=now,
        )
        db.add(student)
        db.flush()
        db.add(ClassStudent(classroom_id=room.id, student_id=student.id))
        db.add(
            StudentInvite(
                code_hash=_hash_invite(code),
                email=email,
                classroom_id=room.id,
                student_id=student.id,
                expires_at=now + timedelta(days=IMPORT_CODE_TTL_DAYS),
            )
        )
        created += 1
        rows_out.append(
            ClassImportRowOut(name=name, email=email, status="created", invite_code=code)
        )
    db.commit()
    return ClassImportOut(created=created, failed=len(rows_out) - created, rows=rows_out)


# ── S3.1: school onboarding (admin -> school code -> staff invite) ────
