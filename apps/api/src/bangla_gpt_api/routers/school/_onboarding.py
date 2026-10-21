"""School onboarding: staff invites, invite redemption, own-school view.

C-03 split of ``routers/school.py``; behaviour-identical move (same paths,
validation, status codes and audit/log lines).
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from bangla_gpt_api.auth.security import (
    create_access_token,
    hash_password,
)
from bangla_gpt_api.auth.single_use import claim_single_use, fetch_by_hash
from bangla_gpt_api.db.models import (
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    School,
    SchoolInvite,
    Teacher,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded
from bangla_gpt_api.schemas import (
    ClassRoomCreateIn,
    ClassRoomOut,
    SchoolInviteIn,
    SchoolInviteOut,
    SchoolJoinIn,
    SchoolOverviewOut,
    SchoolStaffOut,
    TokenResponse,
)
from bangla_gpt_api.services.mailer import smtp_configured
from bangla_gpt_api.services.verification import send_verification_email

from ..common import SCHOOL_CODE_ALPHABET, _default_school, _hash_invite
from ..deps import Ctx, DbSession, SchoolStaffUser
from ._shared import _school_or_403

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


@router.post("/schools/{school_id}/invites", response_model=SchoolInviteOut, status_code=201)
def school_invite_create(
    school_id: int,
    payload: SchoolInviteIn,
    db: DbSession,
    user: SchoolStaffUser,
    app_ctx: Ctx,
) -> SchoolInviteOut:
    """Single-use staff invite; plaintext code is returned exactly once."""
    if db.get(School, school_id) is None:
        raise HTTPException(status_code=404, detail="school not found")
    _school_or_403(user, school_id)
    code = "".join(secrets.choice(SCHOOL_CODE_ALPHABET) for _ in range(10))
    now = datetime.now(UTC).replace(tzinfo=None)
    # Computed once and used for both the row and the response. The column is
    # nullable only because pre-AUD-0046 rows have no expiry; a row this
    # function just created always does, so returning the local value is exact
    # rather than a guess (and it keeps SchoolInviteOut.expires_at required).
    expires_at = now + timedelta(minutes=app_ctx.settings.invite_ttl_minutes)
    invite = SchoolInvite(
        code_hash=_hash_invite(code),
        school_id=school_id,
        role=payload.role,
        created_by=user.id,
        expires_at=expires_at,
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
        expires_at=expires_at,
    )


@router.post(
    "/auth/join-school",
    response_model=TokenResponse,
    status_code=201,
    responses=coded(404, 409, 410),
)
def auth_join_school(app_ctx: Ctx, payload: SchoolJoinIn, db: DbSession) -> TokenResponse:
    """Redeem a staff invite: create the account in the school and sign in.

    Invite codes are single-use and time-limited; only their SHA-256 hash is
    stored, and redemption is atomic (AUD-0034).
    """
    key = _hash_invite(payload.invite_code)
    now = datetime.now(UTC).replace(tzinfo=None)
    # Claim the code before creating any user, so two racing redemptions
    # cannot both reach the insert. AUD-0034.
    if not claim_single_use(
        db,
        SchoolInvite,
        hash_column=SchoolInvite.code_hash,
        hash_value=key,
        now=now,
        require_unexpired=True,
    ):
        existing = fetch_by_hash(
            db, SchoolInvite, hash_column=SchoolInvite.code_hash, hash_value=key
        )
        if existing is None:
            raise HTTPException(
                status_code=404, detail={"code": "invalid_code", "message": "Invalid invite code"}
            )
        expired = (
            existing.expires_at is None or existing.expires_at < now
        ) and existing.used_at is None
        if expired:
            raise HTTPException(
                status_code=410,
                detail={"code": "invite_expired", "message": "Invite code has expired"},
            )
        raise HTTPException(
            status_code=409, detail={"code": "code_used", "message": "Invite already used"}
        )
    invite = fetch_by_hash(db, SchoolInvite, hash_column=SchoolInvite.code_hash, hash_value=key)
    if invite is None:
        raise HTTPException(
            status_code=404, detail={"code": "invalid_code", "message": "Invalid invite code"}
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
    # used_at was already stamped atomically by claim_single_use above.
    db.commit()
    if not user.email_verified:
        # Same contract as /auth/register: in an SMTP-enabled deployment the
        # account cannot sign in until the mailed code is redeemed, so the
        # code has to be issued here too -- the invited teacher otherwise got
        # a working session and then a permanent 403 on every later sign-in.
        send_verification_email(db, app_ctx.settings, user)
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
        # A school_admin without a school is a provisioning error — the
        # sibling school-health endpoint 404s the same shape. Only a platform
        # admin falls back to the default school.
        if user.role == "school_admin":
            raise HTTPException(
                status_code=404,
                detail={"code": "no_school", "message": "No school linked to this account"},
            )
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
        rows = (
            db.execute(
                select(ClassTeacher.teacher_id.label("tid"), func.count().label("cnt"))
                .where(ClassTeacher.teacher_id.in_([p.id for _, p in staff_rows]))
                .group_by(ClassTeacher.teacher_id)
            )
            .mappings()
            .all()
        )
        counts = {int(r["tid"]): int(r["cnt"]) for r in rows}
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
