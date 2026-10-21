"""Shared application context, database/auth dependencies and tenancy guards.

Split from the main.py god-module. Everything here is imported by
the domain routers; nothing in this package may import ``main`` or any router
(one-way dependency: routers -> deps/common -> services).
"""

import calendar
import logging
from collections.abc import Callable, Generator
from typing import Annotated, Any, Literal

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
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
from bangla_gpt_api.db.tenancy import set_tenant_context, tenant_filter_bypassed
from bangla_gpt_api.middleware import pseudonymous_tenant_ref
from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.schemas import MeResponse
from bangla_gpt_api.security import decrypt_pii
from bangla_gpt_api.services.tutor import TutorService

logger = logging.getLogger(__name__)


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
        # AUD-A2-10: the per-user concurrency limiter is built lazily by
        # routers.tutor (one per app instance, shared by every request);
        # declared here so the attribute is typed rather than dynamic.
        self.concurrency_limiter: Any | None = None


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


#: HTTP methods and path prefixes an impersonation session may never use
#: (AUD-B-02 / B-09). A support session is read-and-help only: it must not
#: erase the real user's data (DELETE) and must not take over the account by
#: changing its credentials (password or MFA factors). The check lives in
#: ``get_current_user`` rather than on individual routes because a per-route
#: guard is one forgotten decorator away from a second hole -- the audit's
#: original finding was exactly that (DELETE /users/me was reachable), and
#: the same refusal now covers every router, present and future.
_IMPERSONATION_FORBIDDEN_METHODS = frozenset({"DELETE"})
_IMPERSONATION_FORBIDDEN_PATH_PREFIXES = (
    "/auth/change-password",
    # enroll/verify/disable: adding or removing a factor is a credential change.
    "/auth/mfa",
)


def _refuse_impersonated_mutation(request: Request, payload: dict) -> None:
    """Central 403 for destructive or credential-mutating impersonated calls."""
    if not payload.get("imp"):
        return
    path = request.url.path
    if request.method in _IMPERSONATION_FORBIDDEN_METHODS or path.startswith(
        _IMPERSONATION_FORBIDDEN_PATH_PREFIXES
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "impersonation_readonly",
                "message": ("An impersonation session cannot change credentials or delete data"),
            },
        )


def _check_impersonation_revocation(payload: dict, ctx: AppContext) -> None:
    """Refuse a revoked impersonation session (strict: 503 when uncheckable).

    Impersonation tokens are privileged and short-lived, so the lookup fails
    CLOSED -- an uncheckable impersonation session must not pass -- while every
    other cache read in the app stays soft.
    """
    if not (payload.get("imp") and isinstance(payload.get("jti"), str)):
        return
    try:
        revoked = ctx.cache.get_json_strict(f"imp_revoke:{payload['jti']}")
    except CacheUnavailable as exc:
        raise revocation_store_unavailable() from exc
    if revoked is True:
        raise _unauthorized("Impersonation session has ended")


def _check_logout_denylist(payload: dict, ctx: AppContext) -> None:
    """Refuse a logged-out token (fail-soft: a cache blip must not lock everyone out).

    POST /auth/logout retires exactly one jti instead of leaving it live for
    the rest of its TTL. Unlike the impersonation list, this read is FAIL-SOFT:
    locking every student out because a cache blipped is a worse failure than a
    logged-out token staying valid for the rest of its 60-minute TTL, and the
    TTL plus the password-change epoch remain in force. The outage is logged,
    never silent (the documented cache posture).
    """
    jti = payload.get("jti")
    if not isinstance(jti, str):
        return
    try:
        revoked = ctx.cache.get_json_strict(f"token_revoke:{jti}")
    except CacheUnavailable:
        logger.warning(
            "token revocation store unreachable; deny-list read skipped "
            "(fail-soft posture; TTL and password epoch still apply)"
        )
        revoked = None
    if revoked is True:
        raise _unauthorized("Session ended; please log in again")


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
    # B-02: a refresh token is not an API credential. It exists to mint
    # access tokens at POST /auth/refresh and would otherwise be a 14-day
    # bearer token in the one place a leak is most damaging.
    if payload.get("typ") == "refresh":
        raise _unauthorized("Refresh tokens cannot be used as access tokens")
    _refuse_impersonated_mutation(request, payload)
    # impersonation tokens are revocable BEFORE their short expiry.
    # The jti lands in the shared cache (Redis when configured: revocation
    # then holds across workers/restarts; memory backend: per-worker) with
    # a TTL that matches the token's own remaining life. The lookup is
    # strict (F-08): if the revocation store is unreachable we fail CLOSED
    # for these privileged tokens — an uncheckable impersonation session
    # must not pass — while every other cache read in the app stays soft.
    _check_impersonation_revocation(payload, ctx)
    # AUD-B-04: logout revocation. Every token carries a ``jti``, so POST
    # /auth/logout retires exactly that token instead of leaving it live for
    # the rest of its TTL (client storage is cleared, but a bearer token
    # copied off the device would otherwise keep working). Unlike the
    # impersonation list above, this read is FAIL-SOFT: locking every student
    # out because a cache blipped is a worse failure than a logged-out token
    # staying valid for the rest of its 60-minute TTL, and the primary
    # revocation guarantees -- the TTL and the password-change epoch below --
    # remain in force. The outage is logged, never silent (the documented
    # cache posture: strict for privileged tokens, soft for everything else).
    _check_logout_denylist(payload, ctx)
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
            detail="Password change required. Use POST /auth/change-password first.",
        )
    # B-08: install the tenant on the request's session so every ORM select
    # against the tenancy anchors (Student / ClassRoom / ClassStudent) is
    # rewritten with the school predicate centrally, not only where a router
    # remembered the helper. Admin (None) and parent/student sessions stay
    # unscoped by design; see db/tenancy.py for the exact scope and the
    # documented Session.get() boundary.
    tenant_school = _tenant_school_id(db, user)
    set_tenant_context(db, tenant_school)
    # I-01 (R4-wsC): the access record's tenant handle, resolved here (tenancy
    # needs the DB-backed user; tokens carry no school claim). HMAC-pseudonymous
    # like user_ref; follows the request's school even where tenancy filtering
    # is deliberately unscoped (students carry their school on the user row,
    # staff anchor to the default school per F-04); only the cross-tenant
    # admin session and unauthenticated requests stay None.
    request.state.tenant_ref = pseudonymous_tenant_ref(
        tenant_school if tenant_school is not None else user.school_id,
        ctx.settings.jwt_secret,
    )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def forbid_impersonation(request: Request, user: CurrentUser) -> User:
    """Refuse actions an impersonation session must never perform.

    A support admin wearing a user's identity may look and help, but must
    not exercise the target's irreversible rights: erasing the account via
    DELETE /users/me destroyed the real user's data with no way back
    (AUD-B-02). The guard depends on ``CurrentUser`` so the decoded payload
    is always on ``request.state``; FastAPI caches that dependency per
    request, so there is no extra user lookup.

    B-09: this per-route dependency is now a second line of defence --
    ``get_current_user`` centrally refuses every DELETE and every
    credential-mutating path for ``imp`` tokens, so a future route that
    forgets this dependency is still covered. Keep both: this one documents
    the intent at the route, the central one guarantees it.
    """
    if (getattr(request.state, "jwt_claims", None) or {}).get("imp"):
        raise HTTPException(status_code=403, detail="Not available during an impersonation session")
    return user


NonImpersonatedUser = Annotated[User, Depends(forbid_impersonation)]


def require_roles(*roles: str):
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
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


def _school_student_id_set(db: Session, school_id: int) -> set[int]:
    rows = (
        db.execute(
            select(ClassStudent.student_id)
            .join(ClassRoom, ClassRoom.id == ClassStudent.classroom_id)
            .where(ClassRoom.school_id == school_id)
        )
        .scalars()
        .all()
    )
    return set(rows)


def _assert_student_in_school(db: Session, user: User, student: Student) -> Student:
    """Tenancy gate for per-student reads/writes (closes cross-school IDOR)."""
    school_id = _tenant_school_id(db, user)
    if school_id is None:
        return student
    if student.id not in _school_student_id_set(db, school_id):
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


def load_student_for_tenant(
    db: Session,
    student_id: int,
    user: User,
    *,
    missing_code: Literal["unknown_student"] | None = None,
    missing_message: str = "Student not found",
) -> Student:
    """Load a student by id and apply the tenant check explicitly (B-08).

    Reads through the central ORM filter on purpose: the filter hides
    out-of-tenant rows, and a hidden row would answer a bare 404 -- but the
    documented contract for a student of ANOTHER school is 403
    ``other_school`` (F-04), and existing clients branch on it. The
    pre-image read here is immediately followed by the same predicate the
    filter would have applied, so nothing is disclosed that the caller was
    not already allowed to learn (existence of the numeric id).

    404 is reserved for ids that match no student at all. ``missing_code`` is
    a typed code (not a free-form body) so the coded alternative stays visible
    to the error-contract scan: a body assembled from an arbitrary dict
    parameter would leave the code uncatalogued.
    """
    with tenant_filter_bypassed(db):
        student = db.get(Student, student_id)
    if student is None:
        if missing_code is not None:
            raise HTTPException(
                status_code=404,
                detail={"code": missing_code, "message": missing_message},
            )
        raise HTTPException(status_code=404, detail=missing_message)
    return _assert_student_in_school(db, user, student)


def authorize_student_access(db: Session, student_id: int, user: User) -> Student:
    # school_admin gets school-scoped access (same as teacher), documented policy
    if user.role in ("teacher", "admin", "school_admin"):
        return load_student_for_tenant(db, student_id, user)
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    if user.role == "student" and student.user_id == user.id:
        return student
    # linked guardian allowed via ParentStudentLink
    # This helper is intentionally broader — consent reconfirm checks link explicitly
    raise HTTPException(status_code=403, detail="Not allowed to access this student")


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
