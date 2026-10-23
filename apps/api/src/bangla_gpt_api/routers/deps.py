"""Shared application context, database/auth dependencies and tenancy guards.

Split from the main.py god-module. Everything here is imported by
the domain routers; nothing in this package may import ``main`` or any router
(one-way dependency: routers -> deps/common -> services).
"""

import calendar
from collections.abc import Callable, Generator
from typing import Annotated, Any

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.auth.security import decode_token
from bangla_gpt_api.caching import CacheUnavailable
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    ClassRoom,
    ClassStudent,
    Parent,
    School,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.schemas import MeResponse
from bangla_gpt_api.security import decrypt_pii
from bangla_gpt_api.services.tutor import TutorService


class AppContext:
    """Runtime handles built once in ``create_app`` and shared by all routers.

    Stored on ``app.state.ctx`` so every TestClient app instance keeps its own
    isolated context (no globals, no cross-test leakage).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        cache: Any,
        provider: LLMProvider | None,
        index: RankingIndex | None,
        tutor: TutorService | None,
        session_factory: Callable[[], Session],
        ai_job_tasks: set,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.provider = provider
        self.index = index
        self.tutor = tutor
        self.session_factory = session_factory
        # Strong references to fire-and-forget AiJob tasks (asyncio may
        # garbage-collect bare create_task handles).
        self.ai_job_tasks = ai_job_tasks


def get_ctx(request: Request) -> AppContext:
    """FastAPI dependency exposing the application context.

    ``app.state`` is an untyped attribute bag, so the value is cast here
    rather than leaking ``Any`` into every caller.
    """
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


def get_db(request: Request) -> Generator[Session, None, None]:
    db = request.app.state.ctx.session_factory()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]

bearer_scheme = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def revocation_store_unavailable() -> HTTPException:
    """503 used by every impersonation-revocation touch point (F-08).

    Revocation is a security write: when the shared store cannot be reached
    we refuse loudly instead of pretending the token was stopped. Ordinary
    caches stay fail-soft; this code path is deliberately not.
    """
    return HTTPException(
        status_code=503,
        detail={
            "code": "revocation_unavailable",
            "message": "session revocation store is unreachable; try again shortly",
        },
    )


# bumping this string makes every previously-consented student
# needs_reconfirm=true until they accept via POST /students/{id}/consent/reconfirm
# (see tests/test_compliance_v2.py for the flow).
CONSENT_VERSION = "2026-09-v2"

# Endpoints reachable while a mandatory password change is pending.
_FORCE_CHANGE_EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/live",
        "/ready",
        "/metrics",
        "/auth/change-password",
        "/auth/login",
        "/users/me",
    }
)

# Shared sandbox school for standalone (school-less) staff accounts.
_DEFAULT_SCHOOL_CODE = "BGPT-DEFAULT"


def get_current_user(
    request: Request,
    credentials: BearerCredentials,
    db: DbSession,
) -> User:
    ctx = request.app.state.ctx
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        payload = decode_token(credentials.credentials, settings=ctx.settings)
        user_id = int(payload["sub"])
    except (pyjwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise _unauthorized("Invalid or expired token") from exc
    # Every minted token carries a jti, and a logout (POST /auth/logout)
    # or an account-wide revoke parks it in the shared cache (Redis when
    # configured: revocation then holds across workers/restarts; memory
    # backend: per-worker) with a TTL that matches the token's own
    # remaining life — so a bearer token is revocable BEFORE its expiry
    # (S-011), not only via a password change that rotates the epoch for
    # every session at once. Impersonation tokens keep their own stricter
    # namespace (`imp_revoke:`, F-08). Both lookups are strict: if the
    # revocation store is unreachable we fail CLOSED — an uncheckable
    # session must not pass — and in production Redis is already a hard
    # dependency (the rate limiter fails closed on the same outage), so
    # this adds no new failure mode. Every other cache read stays soft.
    jti = payload.get("jti")
    if isinstance(jti, str):
        try:
            if payload.get("imp"):
                revoked = ctx.cache.get_json_strict(f"imp_revoke:{jti}")
            else:
                revoked = ctx.cache.get_json_strict(f"revoke:{jti}")
        except CacheUnavailable as exc:
            raise revocation_store_unavailable() from exc
        if revoked is True:
            if payload.get("imp"):
                raise _unauthorized("Impersonation session has ended")
            raise _unauthorized("Session ended; please log in again")
    # AUTH-001: MFA step-up tokens (mfa:true, token_type "mfa") are accepted
    # ONLY by POST /auth/mfa/challenge — never as API credentials.
    if payload.get("mfa") is True:
        raise _unauthorized("MFA verification required")
    request.state.jwt_claims = payload
    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("Invalid or expired token")
    # F-05 token epoch: a password change/reset refuses every token issued
    # in an EARLIER second than the rotation. The rotation response token is
    # minted naturally (PyJWT rejects future iat), so same-second mints
    # share the epoch second and stay valid — a sub-second boundary is not
    # expressible with integer iat; the residual window is <1s (previously
    # the whole TTL). Tokens without any ``iat`` (legacy mints) fail closed.
    invalidated = user.sessions_invalidated_at
    if invalidated is not None:
        inv_ts = (
            calendar.timegm(invalidated.timetuple())
            if invalidated.tzinfo is None
            else int(invalidated.timestamp())
        )
        iat = payload.get("iat")
        if not isinstance(iat, int) or iat < inv_ts:
            raise _unauthorized("Session expired; please log in again")
    if user.must_change_password and request.url.path not in _FORCE_CHANGE_EXEMPT_PATHS:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "password_change_required",
                "message": "Password change required. Use POST /auth/change-password first.",
            },
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str):
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail={"code": "insufficient_role", "message": "Insufficient role"},
            )
        return user

    return dependency


TeacherOrAdminUser = Annotated[User, Depends(require_roles("teacher", "admin"))]
ParentUser = Annotated[User, Depends(require_roles("parent"))]
AdminUser = Annotated[User, Depends(require_roles("admin"))]
SchoolStaffUser = Annotated[User, Depends(require_roles("school_admin", "admin"))]


def require_ai_budget(request: Request, db: DbSession, user: TeacherOrAdminUser) -> User:
    """Role check plus the monthly LLM spending cap.

    F-060: ``check_ai_budget`` was wired only into the three /tutor routes.
    Every teacher generation endpoint -- question papers, worksheets, lesson
    plans, answer keys -- calls the same provider and none of them consulted
    the budget, so a single teacher account could spend without limit by
    driving /teacher/qpapers instead of the tutor. The cap is a per-user
    policy; it does not belong to one family of routes.
    """
    # Imported here rather than at module scope: deps -> services is allowed
    # by the layering contract, but a top-level import would pull the whole
    # cost/service graph into every router import.
    from bangla_gpt_api.services.costs import check_ai_budget

    settings = getattr(request.app.state, "settings", None)
    check_ai_budget(db, user_id=user.id, settings=settings)
    return user


#: Dependency for any route that calls an LLM provider.
AIGenerationUser = Annotated[User, Depends(require_ai_budget)]


def _provider_lacks_vision(app_ctx: AppContext) -> bool:
    """the chat routes refuse vision turns for providers without eyes
    (mock, and openai-compatible text-only providers — A10); the honest
    refusal happens at the route, not inside the service, so the LLM
    pipeline never sees an unusable image."""
    tutor = app_ctx.tutor
    if tutor is None:
        return False
    return getattr(tutor.provider, "supports_vision", True) is not True


# --- school tenancy helpers -------------------------------------------
# Tenancy anchor is User.school_id. A student belongs to a school EXACTLY
# when one of their ClassRoom memberships carries that school_id. A teacher
# WITHOUT a school is anchored to the SHARED DEFAULT SCHOOL (the pre-
# school-layer home for standalone accounts — F-04): before this anchor
# they had NO tenancy wall and could read roster/analytics data of every
# real school platform-wide. Once a teacher is attached to a school,
# students and classrooms of OTHER schools stay invisible (403 other_school,
# same code the /school/* routes use).
def _default_school_id(db: Session) -> int:
    """Id of the shared default school, created lazily like common's
    get-or-create helper (kept local to avoid a deps -> common import)."""
    from sqlalchemy.exc import IntegrityError as _IntegrityError

    school = db.execute(
        select(School).where(School.code == _DEFAULT_SCHOOL_CODE)
    ).scalar_one_or_none()
    if school is None:
        school = School(name="Default School", code=_DEFAULT_SCHOOL_CODE)
        db.add(school)
        try:
            db.flush()
        except _IntegrityError:  # concurrent creation
            db.rollback()
            school = db.execute(
                select(School).where(School.code == _DEFAULT_SCHOOL_CODE)
            ).scalar_one()
    return int(school.id)


def _tenant_school_id(db: Session, user: User) -> int | None:
    if user.role == "admin":
        return None
    if user.role in ("teacher", "school_admin"):
        if user.school_id is not None:
            return user.school_id
        # F-04: standalone staff anchor to the shared default school so
        # their reads can never cross into a real school again.
        return _default_school_id(db)
    return None


def _student_in_school(db: Session, school_id: int, student_id: int) -> bool:
    """One EXISTS membership probe for the tenancy gate.

    Was: the school's ENTIRE roster loaded into a Python set per request —
    O(school enrollment) on every quiz submit/progress read. A 2,000-student
    school paid 2,000 rows to answer a one-row question.
    """
    return (
        db.scalar(
            select(func.exists())
            .select_from(ClassStudent)
            .join(ClassRoom, ClassRoom.id == ClassStudent.classroom_id)
            .where(ClassRoom.school_id == school_id, ClassStudent.student_id == student_id)
        )
        is True
    )


def _assert_student_in_school(db: Session, user: User, student: Student) -> Student:
    """Tenancy gate for per-student reads/writes (closes cross-school IDOR)."""
    school_id = _tenant_school_id(db, user)
    if school_id is None:
        return student
    if not _student_in_school(db, school_id, student.id):
        raise HTTPException(
            status_code=403,
            detail={"code": "other_school", "message": "Student is outside your school"},
        )
    return student


def _assert_room_in_school(db: Session, user: User, room: ClassRoom) -> ClassRoom:
    school_id = _tenant_school_id(db, user)
    if school_id is None:
        return room
    if room.school_id != school_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "other_school", "message": "Classroom is outside your school"},
        )
    return room


def authorize_student_access(db: Session, student_id: int, user: User) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(
            status_code=404, detail={"code": "student_not_found", "message": "Student not found"}
        )
    # school_admin gets school-scoped access (same as teacher), documented policy
    if user.role in ("teacher", "admin", "school_admin"):
        return _assert_student_in_school(db, user, student)
    if user.role == "student" and student.user_id == user.id:
        return student
    # linked guardian allowed via ParentStudentLink
    # This helper is intentionally broader — consent reconfirm checks link explicitly
    raise HTTPException(
        status_code=403,
        detail={"code": "not_allowed", "message": "Not allowed to access this student"},
    )


def _build_me_response(app_ctx: AppContext, db: Session, user: User) -> MeResponse:
    profile_id: int | None = None
    name: str | None = None
    class_level: int | None = None
    phone: str | None = None
    if user.role == "student":
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is not None:
            profile_id, name, class_level = student.id, student.name, student.class_level
    elif user.role == "teacher":
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
        if teacher is not None:
            profile_id, name = teacher.id, teacher.name
    elif user.role == "parent":
        parent = db.execute(select(Parent).where(Parent.user_id == user.id)).scalar_one_or_none()
        if parent is not None:
            profile_id, name = parent.id, parent.name
            # owner-only view of the decrypted guardian phone
            phone = decrypt_pii(parent.phone_enc, app_ctx.settings.pii_enc_key)
    return MeResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        profile_id=profile_id,
        name=name,
        class_level=class_level,
        phone=phone,
    )
