"""Users Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select

from bangla_gpt_api.auth import impersonation
from bangla_gpt_api.auth.security import verify_password
from bangla_gpt_api.caching import CacheUnavailable
from bangla_gpt_api.db.models import (
    Parent,
    ParentStudentLink,
    Student,
    User,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded, message
from bangla_gpt_api.schemas import (
    AccountDeleteConfirm,
    ConsentReconfirmIn,
    ConsentStatusOut,
    MeResponse,
    StudentResponse,
)
from bangla_gpt_api.security import write_audit
from bangla_gpt_api.services.gdpr import (
    _DataExportV2,
    build_data_export,
    erase_account_everything,
)

from .deps import (
    CONSENT_VERSION,
    Ctx,
    CurrentUser,
    DbSession,
    _assert_student_in_school,
    _build_me_response,
    authorize_student_access,
    forbid_impersonation,
    revocation_store_unavailable,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)

#: Stable version of the export payload. v1 was the original six sections
#: (profile/attempts/links/conversations/messages/activity); v2 (S-021) adds
#: every remaining per-user table. Clients pin this key to detect shape
#: changes without diffing every list.


@router.get("/users/me", response_model=MeResponse)
def read_me(app_ctx: Ctx, db: DbSession, user: CurrentUser) -> MeResponse:
    return _build_me_response(app_ctx, db, user)


@router.post("/users/me/sessions/revoke", status_code=204)
def revoke_my_sessions(
    app_ctx: Ctx, request: Request, db: DbSession, user: CurrentUser
) -> Response:
    """Sign out EVERYWHERE (S-011): stamps the token epoch, so every
    outstanding bearer token of this account fails the F-05 epoch check on
    its next request. DB-backed, so it holds even when the shared cache is
    unreachable and survives restarts — the account-wide counterpart to
    POST /auth/logout (which ends exactly one session).

    Refused from an impersonated session (F-146 scope limit): revoking the
    account's sessions is a destructive account-state change that outlives
    the 15-minute support window. Ending the ADMIN session also ends the
    impersonation windows it opened (the jti index in
    ``auth.impersonation``), which is why the presented token's jti is read
    here.
    """
    forbid_impersonation(request)
    user.sessions_invalidated_at = datetime.now(UTC)
    write_audit(
        db,
        action="sessions_revoked",
        actor_user_id=user.id,
        actor_role=user.role,
        target=f"user:{user.id}",
        detail={},
    )
    db.commit()
    # F-146: an account-wide revoke is the strongest "end this session"
    # there is, so the impersonation windows this session opened must not
    # survive it. Strict: a store outage must not answer 204 while an
    # impersonated token keeps working.
    claims = getattr(request.state, "jwt_claims", None) or {}
    jti = claims.get("jti")
    if isinstance(jti, str) and jti and claims.get("imp") is not True:
        try:
            ended = impersonation.revoke_session(app_ctx.cache, admin_jti=jti)
        except CacheUnavailable as exc:
            raise revocation_store_unavailable() from exc
        if ended:
            write_audit(
                db,
                action="impersonation",
                actor_user_id=user.id,
                actor_role=user.role,
                target=f"user:{user.id}",
                detail={"phase": "session_end", "revoked_sessions": ended},
            )
            db.commit()
    return Response(status_code=204)


@router.delete("/users/me", status_code=204, responses=coded(401, 409))
def delete_me(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    payload: AccountDeleteConfirm | None = None,
) -> Response:
    """GDPR-style self-service account deletion.

    Removes the account and every row owned by it: student/teacher/parent
    profile and ALL FK-children (Postgres enforces referential integrity --
    SQLite silently does not, so every child table must be cleaned here or
    the delete aborts mid-transaction on the production engine). The last
    remaining admin cannot delete their own account (409).

    F-142: erasure is irreversible, so the CURRENT PASSWORD must be
    re-supplied in the body — a bearer token alone (possibly a stolen
    60-minute one) used to be enough to destroy the account permanently.
    A missing body or wrong password is a coded 401, the same contract as
    /auth/mfa/disable; a body-stripping intermediary therefore fails SAFE
    (no deletion), never open.

    Refused from an impersonated session: a support session is 15 minutes
    and read-shaped, the erasure is forever, and the erased student cannot
    be restored to check what the admin saw.

    The erasure is the most destructive action in the product, so it leaves
    an audit row (actor + target) *before* the account rows go. AuditLog
    survives by design — its pointers to the erased account are anonymised
    inside erase_account_everything — which is what makes a DSR review or an
    incident post-mortem possible at all.
    """
    forbid_impersonation(request)
    if payload is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "bad_current_password",
                "message": "Current password is required to delete this account",
            },
        )
    if user.role == "admin":
        admins = db.execute(
            select(func.count()).select_from(User).where(User.role == "admin")
        ).scalar_one()
        if admins <= 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "last_admin_guard", "message": "Cannot delete the last admin"},
            )

    write_audit(
        db,
        action="account_erase",
        actor_user_id=user.id,
        actor_role=user.role,
        target=f"user:{user.id}",
        detail={"self_service": True},
    )
    # Flush before the cascade: the anonymisation inside
    # erase_account_everything is a Core UPDATE against the database, so it
    # only spares attribution rows that are already THERE. Left pending, this
    # row would insert after the users row was deleted and raise a foreign-key
    # violation — the erasure would fail because it tried to record itself.
    db.flush()
    erase_account_everything(db, user)
    db.commit()
    return Response(status_code=204)


@router.get("/users/me/export", response_model=_DataExportV2)
def export_me(response: Response, db: DbSession, user: CurrentUser) -> _DataExportV2:
    """Self-service data portability: everything stored about this account."""
    response.headers["Content-Disposition"] = 'attachment; filename="my-data-export.json"'
    return build_data_export(db, user)


@router.get("/students/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: DbSession, user: CurrentUser) -> StudentResponse:
    student = authorize_student_access(db, student_id, user)
    return StudentResponse(id=student.id, name=student.name, class_level=student.class_level)


@router.get("/students/{student_id}/consent", response_model=ConsentStatusOut)
def get_consent_status(student_id: int, db: DbSession, user: CurrentUser) -> ConsentStatusOut:
    """is the stored guardian consent current for this student?"""
    student = authorize_student_access(db, student_id, user)
    return ConsentStatusOut(
        student_id=student.id,
        current_version=CONSENT_VERSION,
        accepted_version=student.consent_version,
        accepted_at=student.consent_at,
        needs_reconfirm=student.consent_version != CONSENT_VERSION,
    )


@router.post(
    "/students/{student_id}/consent/reconfirm",
    response_model=ConsentStatusOut,
    responses={**coded(400), **message(403, 404)},
)
def post_consent_reconfirm(
    student_id: int,
    payload: ConsentReconfirmIn,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ConsentStatusOut:
    """re-confirm flow: student or linked guardian accepts the
    CURRENT consent text; evidence trail (at/ip/version) is refreshed."""
    if not payload.accepted:
        raise HTTPException(
            status_code=400,
            detail={"code": "consent_not_accepted", "message": "acceptance required"},
        )
    # align implementation with policy "student or linked guardian"
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(
            status_code=404, detail={"code": "student_not_found", "message": "Student not found"}
        )
    allowed = False
    if user.role == "student" and student.user_id == user.id:
        allowed = True
    elif user.role == "parent":
        parent = db.execute(select(Parent).where(Parent.user_id == user.id)).scalar_one_or_none()
        if parent is not None:
            link = db.execute(
                select(ParentStudentLink).where(
                    ParentStudentLink.parent_id == parent.id,
                    ParentStudentLink.student_id == student.id,
                )
            ).scalar_one_or_none()
            if link is not None:
                allowed = True
    elif user.role in ("admin", "teacher", "school_admin"):
        # Staff support path: teacher/school_admin stay behind the school
        # tenancy wall (same gate as GET /students/{id}/consent); admin is
        # platform-wide by design.
        if user.role != "admin":
            _assert_student_in_school(db, user, student)
        allowed = True
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={"code": "not_allowed", "message": "Not allowed to access this student"},
        )
    # reuse student already loaded
    student.consent_version = CONSENT_VERSION
    student.consent_at = datetime.now(UTC)
    student.consent_ip = request.client.host if request.client else None
    db.commit()
    return ConsentStatusOut(
        student_id=student.id,
        current_version=CONSENT_VERSION,
        accepted_version=student.consent_version,
        accepted_at=student.consent_at,
        needs_reconfirm=False,
    )
