"""School Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import json
import logging
import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.auth.security import (
    create_access_token,
    hash_password,
)
from bangla_gpt_api.db.models import (
    ChapterContent,
    ChapterProgress,
    ChatMessage,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    Conversation,
    DailyActivity,
    QuizAttempt,
    School,
    SchoolInvite,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.schemas import (
    AdminSchoolStatsOut,
    ClassRoomCreateIn,
    ClassRoomOut,
    ContentVersionRowOut,
    SchoolActiveDay,
    SchoolAnalyticsOut,
    SchoolAtRiskRow,
    SchoolClassRow,
    SchoolCoverageOut,
    SchoolCoverageRow,
    SchoolCreateIn,
    SchoolHealthOut,
    SchoolInviteAdminOut,
    SchoolInviteIn,
    SchoolInviteOut,
    SchoolJoinIn,
    SchoolOut,
    SchoolOverviewOut,
    SchoolStaffOut,
    SchoolStudentPage,
    SchoolStudentRow,
    SchoolTeacherRow,
    TokenResponse,
)
from bangla_gpt_api.services import (
    atrisk,
    govt_report,
)
from bangla_gpt_api.services.mailer import smtp_configured

from .common import (
    SCHOOL_CODE_ALPHABET,
    _attempt_percents,
    _default_school,
    _hash_invite,
    _record_analytics,
)
from .deps import (
    AdminUser,
    Ctx,
    DbSession,
    SchoolStaffUser,
)

router = APIRouter()

logger = logging.getLogger(__name__)

SCHOOL_STRONG_AVG = 70.0  # percent; at-risk rule comes from S2.7 (atrisk.py)


def _gen_school_code(db: Session, length: int = 8) -> str:
    while True:
        code = "".join(secrets.choice(SCHOOL_CODE_ALPHABET) for _ in range(length))
        clash = db.execute(select(School.id).where(School.code == code)).first()
        if clash is None:
            return code


def _school_or_403(user: User, school_id: int) -> None:
    """school_admin may act on their own school only; admin on any."""
    if user.role == "admin":
        return
    if user.role == "school_admin" and user.school_id == school_id:
        return
    raise HTTPException(
        status_code=403,
        detail={"code": "other_school", "message": "Scoped to your own school"},
    )


@router.post("/admin/schools", response_model=SchoolOut, status_code=201)
def admin_school_create(payload: SchoolCreateIn, db: DbSession, admin: AdminUser) -> SchoolOut:
    name = payload.name.strip()
    school = School(name=name, code=_gen_school_code(db))
    db.add(school)
    db.commit()
    db.refresh(school)
    json_log(logger, logging.INFO, "school_created", school_id=school.id, code=school.code)
    return SchoolOut(id=school.id, name=school.name, code=school.code, created_at=school.created_at)


@router.get("/admin/schools", response_model=list[SchoolOut])
def admin_school_list(db: DbSession, admin: AdminUser) -> list[SchoolOut]:
    schools = db.execute(select(School).order_by(School.id)).scalars().all()
    return [SchoolOut(id=s.id, name=s.name, code=s.code, created_at=s.created_at) for s in schools]


@router.get("/admin/schools/stats", response_model=list[AdminSchoolStatsOut])
def admin_school_stats(db: DbSession, admin: AdminUser) -> list[AdminSchoolStatsOut]:
    """S3.5: school list with per-school counts (aggregates only, R11)."""
    schools = db.execute(select(School).order_by(School.id)).scalars().all()
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    rows: list[AdminSchoolStatsOut] = []
    for school in schools:
        classrooms = int(
            db.execute(
                select(func.count(ClassRoom.id)).where(ClassRoom.school_id == school.id)
            ).scalar_one()
        )
        student_ids = [
            int(sid)
            for (sid,) in db.execute(
                select(ClassStudent.student_id)
                .join(ClassRoom, ClassRoom.id == ClassStudent.classroom_id)
                .where(ClassRoom.school_id == school.id)
                .distinct()
            )
        ]
        teachers = int(
            db.execute(
                select(func.count(User.id)).where(
                    User.school_id == school.id, User.role.in_(["teacher", "school_admin"])
                )
            ).scalar_one()
        )
        sessions_7d = 0
        if student_ids:
            sessions_7d = int(
                db.execute(
                    select(func.count(Conversation.id)).where(
                        Conversation.student_id.in_(student_ids),
                        Conversation.created_at >= since,
                    )
                ).scalar_one()
            )
        rows.append(
            AdminSchoolStatsOut(
                id=school.id,
                name=school.name,
                code=school.code,
                created_at=school.created_at,
                teachers=teachers,
                classrooms=classrooms,
                students=len(student_ids),
                sessions_7d=sessions_7d,
            )
        )
    return rows


@router.get("/admin/schools/{school_id}/invites", response_model=list[SchoolInviteAdminOut])
def admin_school_invite_list(
    school_id: int, db: DbSession, admin: AdminUser
) -> list[SchoolInviteAdminOut]:
    """S3.5: invite management list; plaintext codes/hashes are never returned (R7)."""
    if db.get(School, school_id) is None:
        raise HTTPException(status_code=404, detail="school not found")
    invites = (
        db.execute(
            select(SchoolInvite)
            .where(SchoolInvite.school_id == school_id)
            .order_by(SchoolInvite.id.desc())
        )
        .scalars()
        .all()
    )
    return [
        SchoolInviteAdminOut(
            id=i.id,
            school_id=i.school_id,
            role=i.role,
            used=i.used_by is not None,
            created_at=i.created_at,
            used_at=i.used_at,
        )
        for i in invites
    ]


@router.delete("/admin/schools/{school_id}/invites/{invite_id}", status_code=204)
def admin_school_invite_revoke(
    school_id: int, invite_id: int, db: DbSession, admin: AdminUser
) -> None:
    """S3.5: revoke an unused staff invite (redeemed ones stay for audit)."""
    invite = db.get(SchoolInvite, invite_id)
    if invite is None or invite.school_id != school_id:
        raise HTTPException(status_code=404, detail="invite not found")
    if invite.used_by is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "already_used", "message": "Invite already redeemed"},
        )
    db.delete(invite)
    db.commit()
    json_log(
        logger,
        logging.INFO,
        "school_invite_revoked",
        school_id=school_id,
        invite_id=invite_id,
    )


@router.get("/admin/content/versions", response_model=list[ContentVersionRowOut])
def admin_content_versions(db: DbSession, admin: AdminUser) -> list[ContentVersionRowOut]:
    """S3.5: current version per (subject, class, chapter) + chain length."""
    contents = (
        db.execute(
            select(ChapterContent).order_by(
                ChapterContent.subject,
                ChapterContent.class_level,
                ChapterContent.chapter,
                ChapterContent.version,
            )
        )
        .scalars()
        .all()
    )
    by_key: dict[tuple[str, int, str], list[ChapterContent]] = {}
    for c in contents:
        by_key.setdefault((c.subject, c.class_level, c.chapter), []).append(c)
    emails: dict[int, str] = {}
    creator_ids = {c.created_by for chain in by_key.values() for c in chain[-1:] if c.created_by}
    if creator_ids:
        for u in db.execute(select(User).where(User.id.in_(creator_ids))).scalars():
            emails[int(u.id)] = str(u.email)
    rows_out: list[ContentVersionRowOut] = []
    for (subject, level, chapter), chain in by_key.items():
        current = chain[-1]
        rows_out.append(
            ContentVersionRowOut(
                subject=subject,
                class_level=level,
                chapter=chapter,
                current_version=current.version,
                versions_total=len(chain),
                source=current.source,
                updated_at=current.created_at,
                updated_by_email=emails.get(current.created_by or 0),
            )
        )
    return rows_out


@router.get("/admin/reports/aggregate")
def admin_report_aggregate(
    db: DbSession,
    admin: AdminUser,
    format: str = Query(default="json", pattern="^(json|csv|pdf)$"),
    district: str = Query(default="", max_length=60),
    since_days: int | None = Query(default=None, ge=1, le=3650),
    min_cell: int = Query(default=5, ge=3, le=50),
) -> Response:
    """S6.5: anonymized aggregate export for government/authority
    requests. Cells below the k-anonymity threshold are suppressed, and
    the serialized payload is PII-scanned before it is handed out --
    any hit fails the request closed (never returns a partial export).
    ``district`` is only an export label supplied by the requester."""
    export = govt_report.aggregate(db, district=district, since_days=since_days, min_cell=min_cell)
    payload = govt_report.to_json_dict(export)
    violations = govt_report.pii_violations(
        json.dumps(payload, ensure_ascii=False) + "\n" + govt_report.to_csv(export)
    )
    if violations:
        # R11: count only, never the offending content.
        json_log(
            logger,
            logging.ERROR,
            "aggregate_report_pii_blocked",
            categories=len(violations),
        )
        raise HTTPException(status_code=500, detail="aggregate report failed the PII safety check")
    stamp = export.meta.generated_at[:10]
    if format == "pdf":
        content: bytes = govt_report.to_pdf(export)
        media_type = "application/pdf"
        filename = f"bangla-gpt-aggregate-{stamp}.pdf"
    elif format == "csv":
        content = govt_report.to_csv(export).encode("utf-8-sig")  # BOM: Excel + Bangla
        media_type = "text/csv; charset=utf-8"
        filename = f"bangla-gpt-aggregate-{stamp}.csv"
    else:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        media_type = "application/json"
        filename = f"bangla-gpt-aggregate-{stamp}.json"
    return Response(
        content=content,
        media_type=media_type,
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/schools/{school_id}/invites", response_model=SchoolInviteOut, status_code=201)
def school_invite_create(
    school_id: int, payload: SchoolInviteIn, db: DbSession, user: SchoolStaffUser
) -> SchoolInviteOut:
    """Single-use staff invite; plaintext code is returned exactly once."""
    if db.get(School, school_id) is None:
        raise HTTPException(status_code=404, detail="school not found")
    _school_or_403(user, school_id)
    code = "".join(secrets.choice(SCHOOL_CODE_ALPHABET) for _ in range(10))
    invite = SchoolInvite(
        code_hash=_hash_invite(code),
        school_id=school_id,
        role=payload.role,
        created_by=user.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    json_log(logger, logging.INFO, "school_invite_created", school_id=school_id, role=invite.role)
    return SchoolInviteOut(
        id=invite.id,
        school_id=school_id,
        role=invite.role,
        code=code,
        created_at=invite.created_at,
    )


@router.post("/auth/join-school", response_model=TokenResponse, status_code=201)
def auth_join_school(app_ctx: Ctx, payload: SchoolJoinIn, db: DbSession) -> TokenResponse:
    """Redeem a staff invite: create the account in the school and sign in.

    Invite codes are single-use; only their SHA-256 hash is stored (R7).
    """
    key = _hash_invite(payload.invite_code)
    invite = db.execute(
        select(SchoolInvite).where(SchoolInvite.code_hash == key)
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(
            status_code=404, detail={"code": "invalid_code", "message": "Invalid invite code"}
        )
    if invite.used_by is not None:
        raise HTTPException(
            status_code=409, detail={"code": "code_used", "message": "Invite already used"}
        )
    email = payload.email.strip().lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "email_taken", "message": "Email already registered"},
        )
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=invite.role,
        email_verified=not smtp_configured(app_ctx.settings),
        school_id=invite.school_id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent registration won the race
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "email_taken", "message": "Email already registered"},
        ) from exc
    profile = Teacher(name=payload.name.strip(), user_id=user.id)
    db.add(profile)
    invite.used_by = user.id
    invite.used_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    json_log(
        logger,
        logging.INFO,
        "school_staff_joined",
        school_id=invite.school_id,
        role=user.role,
    )
    return TokenResponse(access_token=create_access_token(user, settings=app_ctx.settings))


@router.get("/schools/mine", response_model=SchoolOverviewOut)
def school_my_overview(db: DbSession, user: SchoolStaffUser) -> SchoolOverviewOut:
    """Own-school overview for staff; admin without a school sees the default."""
    school = db.get(School, user.school_id) if user.school_id else None
    if school is None:
        school = _default_school(db)
    rooms = db.execute(select(ClassRoom).where(ClassRoom.school_id == school.id)).scalars().all()
    room_ids = [r.id for r in rooms]
    students = 0
    if room_ids:
        students = int(
            db.execute(
                select(func.count(func.distinct(ClassStudent.student_id))).where(
                    ClassStudent.classroom_id.in_(room_ids)
                )
            ).scalar_one()
        )
    staff_rows = list(
        db.execute(
            select(User, Teacher)
            .join(Teacher, Teacher.user_id == User.id)
            .where(User.school_id == school.id, User.role.in_(["teacher", "school_admin"]))
            .order_by(User.id)
        ).all()
    )
    counts: dict[int, int] = {}
    if staff_rows:
        rows = cast(
            CursorResult[Any],
            db.execute(
                select(ClassTeacher.teacher_id, func.count())
                .where(ClassTeacher.teacher_id.in_([p.id for _, p in staff_rows]))
                .group_by(ClassTeacher.teacher_id)
            ),
        )
        counts = {int(r[0]): int(r[1]) for r in rows.all()}
    staff = [
        SchoolStaffOut(
            id=u.id,
            name=p.name,
            email=u.email,
            role=u.role,
            classroom_count=counts.get(p.id, 0),
        )
        for u, p in staff_rows
    ]
    return SchoolOverviewOut(
        school_id=school.id,
        name=school.name,
        code=school.code,
        students=students,
        teachers=len(staff),
        classrooms=len(rooms),
        staff=staff,
    )


@router.post("/schools/{school_id}/classes", response_model=ClassRoomOut, status_code=201)
def school_class_register(
    school_id: int, payload: ClassRoomCreateIn, db: DbSession, user: SchoolStaffUser
) -> ClassRoomOut:
    if db.get(School, school_id) is None:
        raise HTTPException(status_code=404, detail="school not found")
    _school_or_403(user, school_id)
    section = (payload.section or "").strip().upper() or "GEN"
    room = ClassRoom(school_id=school_id, class_level=payload.class_level, section=section)
    db.add(room)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="classroom exists") from None
    db.refresh(room)
    json_log(logger, logging.INFO, "school_class_registered", school_id=school_id, room_id=room.id)
    return ClassRoomOut(
        id=room.id, class_level=room.class_level, section=room.section, student_count=0
    )


# ── S3.2: school dashboard (aggregate learning health, no per-message data) ──


@router.get("/school/overview", response_model=SchoolHealthOut)
def school_health_overview(
    db: DbSession, user: SchoolStaffUser, school_id: int | None = Query(default=None)
) -> SchoolHealthOut:
    """Whole-school counts + strong/support/risk buckets + at-risk list.

    Aggregates only: buckets and averages over graded attempts; chat data
    contributes nothing beyond a count of sessions started in the last
    7 days (R11: no message content ever leaves this endpoint).
    """
    if user.role == "school_admin":
        if school_id is not None and school_id != user.school_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "other_school", "message": "Scoped to your own school"},
            )
        school = db.get(School, user.school_id) if user.school_id else None
        if school is None:
            raise HTTPException(status_code=404, detail="school not found")
    else:  # admin: any school, default school when none requested
        school = db.get(School, school_id) if school_id else None
        if school is None:
            school = _default_school(db)
    rooms = db.execute(select(ClassRoom).where(ClassRoom.school_id == school.id)).scalars().all()
    room_ids = [r.id for r in rooms]
    students: list[Student] = []
    room_of: dict[int, ClassRoom] = {}
    if room_ids:
        room_by_id = {r.id: r for r in rooms}
        joins = db.execute(
            select(ClassStudent.student_id, ClassStudent.classroom_id)
            .where(ClassStudent.classroom_id.in_(room_ids))
            .order_by(ClassStudent.classroom_id, ClassStudent.student_id)
        ).all()
        for sid, rid in joins:
            room_of.setdefault(int(sid), room_by_id[int(rid)])
        ids = sorted(room_of)
        if ids:
            by_id = {
                s.id: s for s in db.execute(select(Student).where(Student.id.in_(ids))).scalars()
            }
            students = [by_id[i] for i in ids if i in by_id]
    student_ids = [s.id for s in students]
    teachers = int(
        db.execute(
            select(func.count(User.id)).where(
                User.school_id == school.id, User.role.in_(["teacher", "school_admin"])
            )
        ).scalar_one()
    )
    sessions_7d = 0
    if student_ids:
        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
        sessions_7d = int(
            db.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.student_id.in_(student_ids),
                    Conversation.created_at >= since,
                )
            ).scalar_one()
        )
    percents = _attempt_percents(db, student_ids)
    strong = support = risk = ungraded = 0
    at_risk_rows: list[SchoolAtRiskRow] = []
    for s in students:
        scores = percents.get(s.id, [])
        avg = atrisk.avg_pct(scores)
        trend = atrisk.score_trend(scores)
        room = room_of.get(s.id)
        class_level = room.class_level if room else (s.class_level or 0)
        section = room.section if room else ""
        if avg is None:
            ungraded += 1
            continue
        if atrisk.is_at_risk(avg, trend):
            risk += 1
            at_risk_rows.append(
                SchoolAtRiskRow(
                    student_id=s.id,
                    name=s.name,
                    class_level=class_level,
                    section=section,
                    attempts_graded=len(scores),
                    avg_score_pct=avg,
                    trend=trend,
                )
            )
        elif avg >= SCHOOL_STRONG_AVG:
            strong += 1
        else:
            support += 1
    graded = strong + support + risk

    def _pct(n: int) -> float:
        return round(100.0 * n / graded, 1) if graded else 0.0

    at_risk_rows.sort(key=lambda r: r.avg_score_pct if r.avg_score_pct is not None else 0.0)
    return SchoolHealthOut(
        school_id=school.id,
        name=school.name,
        code=school.code,
        students=len(students),
        teachers=teachers,
        classrooms=len(rooms),
        sessions_7d=sessions_7d,
        strong=strong,
        support=support,
        risk=risk,
        ungraded=ungraded,
        strong_pct=_pct(strong),
        support_pct=_pct(support),
        risk_pct=_pct(risk),
        at_risk=at_risk_rows,
    )


# ── Wave 2: school section (school_admin own school, admin platform-wide) ──


def _actor_school(db: Session, user: User, school_id: int | None) -> School:
    """Resolve the school a /school/* request is allowed to read.

    school_admin is hard-scoped to their own row; platform admin may name
    any school and falls back to the default school (same rule as
    /school/overview).
    """
    if user.role == "school_admin":
        if school_id is not None and school_id != user.school_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "other_school", "message": "Scoped to your own school"},
            )
        school = db.get(School, user.school_id) if user.school_id else None
        if school is None:
            raise HTTPException(status_code=404, detail="school not found")
        return school
    school = db.get(School, school_id) if school_id else None
    if school is None:
        school = _default_school(db)
    return school


def _school_rooms(db: Session, school_id: int) -> list[ClassRoom]:
    return list(
        db.execute(
            select(ClassRoom)
            .where(ClassRoom.school_id == school_id)
            .order_by(ClassRoom.class_level, ClassRoom.section, ClassRoom.id)
        ).scalars()
    )


def _school_students_by_room(
    db: Session, room_ids: list[int]
) -> tuple[list[Student], dict[int, int]]:
    """Enrolled students (school membership is classroom membership) plus
    the room each student belongs to (v1 rule: exactly one room)."""
    room_of: dict[int, int] = {}
    if not room_ids:
        return [], room_of
    for sid, rid in db.execute(
        select(ClassStudent.student_id, ClassStudent.classroom_id)
        .where(ClassStudent.classroom_id.in_(room_ids))
        .order_by(ClassStudent.classroom_id, ClassStudent.student_id)
    ).all():
        room_of.setdefault(int(sid), int(rid))
    ids = sorted(room_of)
    if not ids:
        return [], room_of
    rows = {s.id: s for s in db.execute(select(Student).where(Student.id.in_(ids))).scalars().all()}
    return [rows[i] for i in ids if i in rows], room_of


@router.get("/school/students", response_model=SchoolStudentPage)
def school_students(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
    class_level: Annotated[int | None, Query(ge=1, le=12)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SchoolStudentPage:
    """Paginated school roster: id, name, grade, section, approximate last
    activity and quiz-attempt count. NO email/phone ever (R11).

    "last_active" is the best honest signal available server-side: the
    newer of the last tracked activity day and the last quiz attempt.
    """
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, room_of = _school_students_by_room(db, [r.id for r in rooms])
    room_by_id = {r.id: r for r in rooms}
    if class_level is not None:
        students = [s for s in students if s.class_level == class_level]
    total = len(students)
    page = students[offset : offset + limit]
    ids = [s.id for s in page]
    last_day: dict[int, str] = {}
    attempts: dict[int, int] = {}
    if ids:
        for sid, day in db.execute(
            select(DailyActivity.student_id, func.max(DailyActivity.date))
            .where(DailyActivity.student_id.in_(ids))
            .group_by(DailyActivity.student_id)
        ).all():
            last_day[sid] = str(day)
        for sid, ts in db.execute(
            select(QuizAttempt.student_id, func.max(QuizAttempt.created_at))
            .where(QuizAttempt.student_id.in_(ids))
            .group_by(QuizAttempt.student_id)
        ).all():
            if ts is None:
                continue
            iso = str(ts)[:10]
            if sid not in last_day or iso > last_day[sid]:
                last_day[sid] = iso
        for sid, n in db.execute(
            select(QuizAttempt.student_id, func.count())
            .where(QuizAttempt.student_id.in_(ids))
            .group_by(QuizAttempt.student_id)
        ).all():
            attempts[sid] = int(n)
    items = [
        SchoolStudentRow(
            student_id=s.id,
            name=s.name,
            class_level=s.class_level,
            section=room_by_id[room_of[s.id]].section if s.id in room_of else "GEN",
            last_active=last_day.get(s.id),
            quiz_attempts=attempts.get(s.id, 0),
        )
        for s in page
    ]
    return SchoolStudentPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/school/teachers", response_model=list[SchoolTeacherRow])
def school_teachers(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
) -> list[SchoolTeacherRow]:
    """Staff roster of the school: accounts with a teacher profile plus
    the subjects/classrooms they are assigned (ClassTeacher '' = all)."""
    school = _actor_school(db, user, school_id)
    staff = db.execute(
        select(User, Teacher)
        .join(Teacher, Teacher.user_id == User.id)
        .where(
            User.school_id == school.id,
            User.role.in_(["teacher", "school_admin"]),
        )
        .order_by(User.id)
    ).all()
    teacher_ids = [t.id for _, t in staff]
    subjects: dict[int, set[str]] = defaultdict(set)
    rooms: dict[int, set[int]] = defaultdict(set)
    if teacher_ids:
        for tid, cid, subject in db.execute(
            select(ClassTeacher.teacher_id, ClassTeacher.classroom_id, ClassTeacher.subject).where(
                ClassTeacher.teacher_id.in_(teacher_ids)
            )
        ).all():
            subjects[int(tid)].add(subject or "all")
            rooms[int(tid)].add(int(cid))
    return [
        SchoolTeacherRow(
            teacher_id=t.id,
            name=t.name,
            subjects=sorted(subjects.get(t.id, set())),
            classrooms=len(rooms.get(t.id, set())),
        )
        for _, t in staff
    ]


@router.get("/school/classes", response_model=list[SchoolClassRow])
def school_classes(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
) -> list[SchoolClassRow]:
    """Per classroom: enrollment, attempt volume and graded accuracy."""
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, room_of = _school_students_by_room(db, [r.id for r in rooms])
    percents = _attempt_percents(db, [s.id for s in students])
    counts: dict[int, list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    for s in students:
        counts[room_of[s.id]][0] += 1
    # one grouped count + one grouped average instead of 2 queries/student
    ids = [s.id for s in students]
    if ids:
        for sid, n in db.execute(
            select(QuizAttempt.student_id, func.count())
            .where(QuizAttempt.student_id.in_(ids))
            .group_by(QuizAttempt.student_id)
        ).all():
            counts[room_of[int(sid)]][1] += int(n)
        for sid, pcts in percents.items():
            room_id = room_of[sid]
            counts[room_id][2] += len(pcts)
            counts[room_id][3] += sum(pcts)
    rows: list[SchoolClassRow] = []
    for r in rooms:
        students_n, att, graded, total_pct = counts[r.id]
        rows.append(
            SchoolClassRow(
                classroom_id=r.id,
                class_level=r.class_level,
                section=r.section,
                students=int(students_n),
                quiz_attempts=int(att),
                attempts_graded=int(graded),
                avg_quiz_accuracy=round(total_pct / graded, 2) if graded else None,
            )
        )
    return rows


@router.get("/school/coverage", response_model=SchoolCoverageOut)
def school_coverage(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
) -> SchoolCoverageOut:
    """Per grade the school runs: subjects the content library HAS versus
    the subjects this school's students actually practice, plus chapter
    read coverage. Empty lists are honest "no signal", never "covered".

    Practice proxy: ChatMessage rows carry no subject column, so asked
    subjects come from graded quiz attempts (documented deviation).
    """
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, _room_of = _school_students_by_room(db, [r.id for r in rooms])
    level_of = {s.id: s.class_level for s in students}
    levels = sorted({r.class_level for r in rooms})
    rows: list[SchoolCoverageRow] = []
    for level in levels:
        level_students = [sid for sid, lvl in level_of.items() if lvl == level]
        content = db.execute(
            select(ChapterContent.subject, ChapterContent.chapter).where(
                ChapterContent.class_level == level
            )
        ).all()
        content_subjects = sorted({str(subject) for subject, _ in content})
        asked: set[str] = set()
        if level_students:
            asked = {
                str(subject)
                for (subject,) in db.execute(
                    select(QuizAttempt.subject)
                    .where(
                        QuizAttempt.student_id.in_(level_students),
                        QuizAttempt.subject.is_not(None),
                    )
                    .distinct()
                ).all()
                if subject
            }
        read = completed = 0
        if level_students:
            read = int(
                db.execute(
                    select(func.count(ChapterProgress.id)).where(
                        ChapterProgress.student_id.in_(level_students),
                        ChapterProgress.class_level == level,
                    )
                ).scalar_one()
            )
            completed = int(
                db.execute(
                    select(func.count(ChapterProgress.id)).where(
                        ChapterProgress.student_id.in_(level_students),
                        ChapterProgress.class_level == level,
                        ChapterProgress.completed.is_(True),
                    )
                ).scalar_one()
            )
        rows.append(
            SchoolCoverageRow(
                class_level=level,
                content_subjects=content_subjects,
                asked_subjects=sorted(asked),
                uncovered_subjects=sorted(set(content_subjects) - asked),
                chapters_available=len({(s, c) for s, c in content}),
                chapters_read=read,
                chapters_completed=completed,
            )
        )
    return SchoolCoverageOut(rows=rows)


@router.get("/school/analytics", response_model=SchoolAnalyticsOut)
def school_analytics(
    db: DbSession,
    user: SchoolStaffUser,
    school_id: Annotated[int | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> SchoolAnalyticsOut:
    """K-anonymity-safe trend counts only: daily actives, questions asked
    and quiz volume. No per-student row, no message content ever (R11)."""
    school = _actor_school(db, user, school_id)
    rooms = _school_rooms(db, school.id)
    students, _room_of = _school_students_by_room(db, [r.id for r in rooms])
    student_ids = [s.id for s in students]
    now = datetime.now(UTC).replace(tzinfo=None)
    since = now - timedelta(days=days)
    since_day = since.strftime("%Y-%m-%d")
    active_by_date: list[SchoolActiveDay] = []
    questions_asked = 0
    attempts = graded = 0
    avg_score: float | None = None
    if student_ids:
        for day, n in db.execute(
            select(DailyActivity.date, func.count(func.distinct(DailyActivity.student_id)))
            .where(
                DailyActivity.student_id.in_(student_ids),
                DailyActivity.date >= since_day,
            )
            .group_by(DailyActivity.date)
            .order_by(DailyActivity.date)
        ).all():
            active_by_date.append(SchoolActiveDay(date=str(day), students=int(n)))
        conv_ids = select(Conversation.id).where(Conversation.student_id.in_(student_ids))
        questions_asked = int(
            db.execute(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.conversation_id.in_(conv_ids),
                    ChatMessage.role == "user",
                    ChatMessage.created_at >= since,
                )
            ).scalar_one()
        )
        attempts = int(
            db.execute(
                select(func.count(QuizAttempt.id)).where(
                    QuizAttempt.student_id.in_(student_ids),
                    QuizAttempt.created_at >= since,
                )
            ).scalar_one()
        )
        graded, avg = db.execute(
            select(func.count(QuizAttempt.id), func.avg(QuizAttempt.score_pct)).where(
                QuizAttempt.student_id.in_(student_ids),
                QuizAttempt.status == "graded",
                QuizAttempt.score_pct.is_not(None),
                QuizAttempt.created_at >= since,
            )
        ).one()
        graded = int(graded)
        avg_score = round(float(avg), 2) if avg is not None else None
    _record_analytics(db, user.id, user.role, "school_analytics_viewed", {"days": days})
    db.commit()
    daily_active_avg = (
        round(sum(d.students for d in active_by_date) / len(active_by_date), 2)
        if active_by_date
        else 0.0
    )
    return SchoolAnalyticsOut(
        days=days,
        active_by_date=active_by_date,
        daily_active_avg=daily_active_avg,
        questions_asked=questions_asked,
        quiz_attempts=attempts,
        attempts_graded=graded,
        avg_quiz_score_pct=avg_score,
    )
