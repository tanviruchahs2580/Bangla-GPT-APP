"""Platform-admin school endpoints (C-03 split of ``routers/school.py``).

Behaviour-identical move: same paths, validation and status codes. The
government aggregate export lives here because it is a platform-admin surface
(and one of the four documented write-on-GET handlers).
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from bangla_gpt_api.db.models import (
    ChapterContent,
    ClassRoom,
    ClassStudent,
    Conversation,
    School,
    SchoolInvite,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    AdminSchoolStatsOut,
    ContentVersionRowOut,
    SchoolCreateIn,
    SchoolInviteAdminOut,
    SchoolOut,
)
from bangla_gpt_api.security import write_audit
from bangla_gpt_api.services import govt_report

from ..deps import AdminUser, DbSession
from ._shared import _gen_school_code

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


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
    """school list with per-school counts (aggregates only, )."""
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
    """invite management list; plaintext codes/hashes are never returned."""
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
            expires_at=i.expires_at,
        )
        for i in invites
    ]


@router.delete("/admin/schools/{school_id}/invites/{invite_id}", status_code=204)
def admin_school_invite_revoke(
    school_id: int, invite_id: int, db: DbSession, admin: AdminUser
) -> None:
    """revoke an unused staff invite (redeemed ones stay for audit)."""
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
    """current version per (subject, class, chapter) + chain length."""
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
    min_cell: int = Query(
        default=govt_report.DEFAULT_MIN_CELL,
        ge=govt_report.MIN_CELL_FLOOR,
        le=50,
        description=(
            "k-anonymity threshold. Raising it suppresses more cells; values "
            f"below {govt_report.MIN_CELL_FLOOR} are refused rather than "
            "clamped, because the guarantee must not be the requester's to "
            "lower."
        ),
    ),
) -> Response:
    """anonymized aggregate export for government/authority
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
        # count only, never the offending content.
        json_log(
            logger,
            logging.ERROR,
            "aggregate_report_pii_blocked",
            categories=len(violations),
        )
        raise HTTPException(status_code=500, detail="aggregate report failed the PII safety check")
    # AUD-B-06: B-11 requires export ACCESS to be audited. Only an export that
    # passed the PII gate (above) writes a row, and the row lands in the same
    # transaction as the response decision -- detail holds ids and counts
    # only, never a district-level payload. A refused export is deliberately
    # not recorded as a successful one; the refusal itself is a log event
    # ("aggregate_report_pii_blocked") immediately above.
    write_audit(
        db,
        action="govt_export",
        actor_user_id=admin.id,
        actor_role=admin.role,
        target=f"district:{district or 'all'}",
        detail={
            "format": format,
            "district": district or None,
            "since_days": since_days,
            "min_cell": min_cell,
            "rows": len(export.rows),
            "students_included": export.meta.total_students_included,
            "suppressed_cells": export.meta.suppressed_cells,
        },
    )
    db.commit()
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
