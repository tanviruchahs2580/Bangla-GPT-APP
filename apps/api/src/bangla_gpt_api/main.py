import hashlib
import json
import logging
import secrets
from collections import defaultdict
from collections.abc import AsyncIterator, Generator
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any, cast

import jwt as pyjwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from bangla_gpt_api.auth.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from bangla_gpt_api.config import DEFAULT_JWT_SECRET, Settings, get_settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.db.models import (
    AnswerLog,
    ChatMessage,
    Conversation,
    EmailVerification,
    Feedback,
    Parent,
    ParentInvite,
    ParentStudentLink,
    PasswordReset,
    QuizAttempt,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.logging_config import configure_logging, json_log, request_id_var
from bangla_gpt_api.metrics import (
    REGISTRY,
    REQUEST_LATENCY_SECONDS,
    REQUESTS_TOTAL,
    UNHANDLED_EXCEPTIONS_TOTAL,
)
from bangla_gpt_api.providers import (
    ProviderError,
    ProviderNotConfigured,
    get_provider,
)
from bangla_gpt_api.ratelimit import (
    RateLimitBackendError,
    RateLimiter,
    build_limiter,
)
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.schemas import (
    AdminOverview,
    AdminUsersPage,
    AnalyticsEvent,
    AskRequest,
    AskResponse,
    ChangePasswordRequest,
    ChapterStat,
    ChatMessageOut,
    ChatSendRequest,
    ClassAnalytics,
    ConversationCreate,
    ConversationOut,
    DataExportResponse,
    FeedbackRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    ParentInviteLinkRequest,
    ParentLinkRequest,
    QuizQuestionPublic,
    QuizResult,
    QuizStarted,
    QuizStartRequest,
    QuizSubmitRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ReviewItem,
    RoleUpdateRequest,
    SourceRef,
    StudentBrief,
    StudentProgress,
    StudentResponse,
    TokenResponse,
    UserPublic,
    VerifyEmailRequest,
)
from bangla_gpt_api.services.learn import (
    ChapterContentOut,
    ChapterSummaryOut,
    SubjectOut,
    chapter_content,
    list_subjects,
    subject_chapters,
)
from bangla_gpt_api.services.mailer import send_mail, smtp_configured
from bangla_gpt_api.services.quiz import ClozeQuizGenerator, dump_quiz
from bangla_gpt_api.services.tutor import TutorService

logger = logging.getLogger(__name__)

# Canonical subject keys used by the corpus; aliases accepted from clients
# are normalized so 'math' and 'mathematics' both resolve (frontend bug fix).
_SUBJECT_ALIASES = {"math": "mathematics", "গণিত": "mathematics"}


def canonical_subject(subject: str | None) -> str | None:
    if subject is None:
        return None
    return _SUBJECT_ALIASES.get(subject.strip().lower(), subject.strip().lower())


CONSENT_VERSION = "2026-08-v1"

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
        "/users/me/export",
    }
)


def _safe_init_db(engine) -> None:
    """create_all tolerant of concurrent multi-worker boot (gunicorn -w N)."""
    try:
        init_db(engine)
    except OperationalError as exc:
        if "already exists" not in str(exc):
            raise


def enforce_production_safety(settings: Settings) -> None:
    """Refuse to boot in production with insecure configuration (B6)."""
    if not settings.is_production:
        return
    problems: list[str] = []
    if settings.jwt_secret == DEFAULT_JWT_SECRET or len(settings.jwt_secret) < 32:
        problems.append(
            "JWT_SECRET must be overridden in production with at least 32 random characters"
        )
    if not settings.admin_email or not settings.admin_password:
        problems.append("ADMIN_EMAIL and ADMIN_PASSWORD must be configured in production")
    elif len(settings.admin_password) < 12:
        problems.append("ADMIN_PASSWORD must be at least 12 characters in production")
    if settings.rate_limit_backend == "redis" and not settings.redis_url:
        problems.append("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
    if settings.llm_provider.strip().lower() == "gemini" and not settings.gemini_api_key:
        problems.append("LLM_PROVIDER=gemini requires GEMINI_API_KEY in production")
    if not settings.allowed_origins.strip():
        problems.append("ALLOWED_ORIGINS must be set in production (comma-separated allowlist)")
    elif "*" in settings.allowed_origins:
        problems.append("ALLOWED_ORIGINS must not contain wildcard '*' in production")
    # V8: an in-memory database in production silently gives each worker its
    # own isolated store -> sessions/records vanish across workers.
    if settings.database_url.strip() == "sqlite://":
        problems.append(
            "DATABASE_URL must be a persistent store in production "
            "(e.g. sqlite:////data/app.db or PostgreSQL)"
        )
    if problems:
        raise RuntimeError(
            "Refusing to start: insecure production configuration detected:\n- "
            + "\n- ".join(problems)
        )


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        import uuid

        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def _client_ip(request: Request, *, trust_proxy: bool) -> str:
    """Client identity for IP-scoped rate limits.

    Behind a trusted reverse proxy the real client IP arrives in
    X-Forwarded-For; enable only when the proxy overwrites (not appends)
    that header, otherwise clients can spoof it.
    """
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip() if forwarded else ""
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiting with IP and per-user scopes.

    Authenticated routes use a per-user key when a valid Bearer token is
    present (C15: one school NAT must not lock out a whole classroom), while
    an IP ceiling still guards against token-farm abuse.
    """

    def __init__(
        self, app, rules: dict[str, tuple[int, str]], limiter: "RateLimiter", settings: Settings
    ) -> None:
        super().__init__(app)
        self.rules = rules
        self.limiter = limiter
        self._settings = settings

    @staticmethod
    def _user_key(request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        try:
            payload = decode_token(auth[7:], settings=request.app.state.settings)
            return f"u:{payload['sub']}"
        except Exception:
            return None

    async def dispatch(self, request: Request, call_next):
        client_ip = _client_ip(request, trust_proxy=self._settings.trust_proxy_headers)
        for path_prefix, (limit, scope) in self.rules.items():
            if not request.url.path.startswith(path_prefix) or limit <= 0:
                continue
            if scope == "user":
                # Per-user budget so a shared school NAT cannot lock out a
                # classroom; unauthenticated callers fall back to their IP.
                user_key = self._user_key(request)
                key_source = user_key or f"ip:{client_ip}"
            else:
                key_source = f"ip:{client_ip}"
            try:
                allowed = self.limiter.check(f"{path_prefix}|{key_source}", limit)
            except RateLimitBackendError:
                return JSONResponse({"detail": "Rate limiter unavailable"}, status_code=503)
            if not allowed:
                return JSONResponse(
                    {"detail": {"code": "rate_limited", "message": "Rate limit exceeded"}},
                    status_code=429,
                )
            break
        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers on every API response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Count every request and observe latency, labeled by route template."""

    async def dispatch(self, request: Request, call_next):
        start = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            UNHANDLED_EXCEPTIONS_TOTAL.labels(
                method=request.method, path=self._route_path(request)
            ).inc()
            raise
        finally:
            elapsed = perf_counter() - start
            path = self._route_path(request)
            REQUESTS_TOTAL.labels(method=request.method, path=path, status=str(status_code)).inc()
            REQUEST_LATENCY_SECONDS.labels(path=path).observe(elapsed)

    @staticmethod
    def _route_path(request: Request) -> str:
        route = request.scope.get("route")
        return getattr(route, "path", request.url.path)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # S0.6: Sentry — no-op when DSN absent, safe for tests/dev
    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.sentry_env,
                traces_sample_rate=0.1,
            )
        except Exception:
            pass
    enforce_production_safety(settings)
    if settings.rate_limit_backend not in ("memory", "redis"):
        raise RuntimeError(
            f"RATE_LIMIT_BACKEND={settings.rate_limit_backend!r} is not supported; "
            "use 'memory' or 'redis'"
        )
    if settings.rate_limit_backend == "redis" and not settings.redis_url:
        raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL to be set")
    app = FastAPI(title=settings.app_name, version=settings.version)
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    try:
        provider = get_provider(settings)
    except ProviderNotConfigured:
        provider = None

    index: BM25Index | None = None
    tutor: TutorService | None = None
    if provider is not None:
        if settings.nctb_corpus_dir:
            from pathlib import Path as _Path

            from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

            corpus_root = _Path(settings.nctb_corpus_dir)
            nctb_chunks = load_nctb_corpus(
                corpus_root / "normalized",
                quality_report_path=corpus_root / "quality_report.json",
            )
            if nctb_chunks:
                index = BM25Index(nctb_chunks)
        if index is None:
            index = BM25Index(load_sample_corpus())
        tutor = TutorService(index=index, provider=provider)
        if hasattr(provider, "aclose"):
            app.router.on_shutdown.append(provider.aclose)

    engine = make_engine(settings)
    _safe_init_db(engine)
    session_factory = make_session_factory(engine)

    if settings.admin_email and settings.admin_password:
        force_change = settings.force_admin_password_change
        with session_factory() as bootstrap_db:
            admin_email = settings.admin_email.strip().lower()
            exists = bootstrap_db.execute(
                select(User).where(User.email == admin_email)
            ).scalar_one_or_none()
            if exists is None:
                bootstrap_db.add(
                    User(
                        email=admin_email,
                        password_hash=hash_password(settings.admin_password),
                        role="admin",
                        must_change_password=force_change,
                    )
                )
                try:
                    bootstrap_db.commit()
                except IntegrityError:
                    # Another worker bootstrapped the same admin concurrently.
                    bootstrap_db.rollback()

    app.add_middleware(
        RateLimitMiddleware,
        rules={
            "/auth/login": (settings.rate_limit_login_per_minute, "ip"),
            "/tutor/ask": (settings.rate_limit_tutor_per_minute, "user"),
            "/tutor/chat": (settings.rate_limit_tutor_per_minute, "user"),
            "/tutor": (settings.rate_limit_tutor_ip_per_minute, "ip"),
            "/auth/forgot": (settings.rate_limit_login_per_minute, "ip"),
            "/auth/reset": (settings.rate_limit_login_per_minute, "ip"),
            "/events": (60, "ip"),
        },
        limiter=build_limiter(settings),
        settings=settings,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(PrometheusMetricsMiddleware)

    def get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    DbSession = Annotated[Session, Depends(get_db)]

    bearer_scheme = HTTPBearer(auto_error=False)
    BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

    def get_current_user(
        request: Request,
        credentials: BearerCredentials,
        db: DbSession,
    ) -> User:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        try:
            payload = decode_token(credentials.credentials, settings=settings)
            user_id = int(payload["sub"])
        except (pyjwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise _unauthorized("Invalid or expired token") from exc
        user = db.get(User, user_id)
        if user is None:
            raise _unauthorized("Invalid or expired token")
        if user.must_change_password and request.url.path not in _FORCE_CHANGE_EXEMPT_PATHS:
            raise HTTPException(
                status_code=403,
                detail="Password change required. Use POST /auth/change-password first.",
            )
        return user

    CurrentUser = Annotated[User, Depends(get_current_user)]

    def require_roles(*roles: str):
        def dependency(user: CurrentUser) -> User:
            if user.role not in roles:
                raise HTTPException(status_code=403, detail="Insufficient role")
            return user

        return dependency

    TeacherOrAdminUser = Annotated[User, Depends(require_roles("teacher", "admin"))]
    ParentUser = Annotated[User, Depends(require_roles("parent"))]
    AdminUser = Annotated[User, Depends(require_roles("admin"))]

    # ── Learn catalog (read-only, grounded in the loaded corpus) ──────────
    @app.get("/learn/subjects", response_model=list[SubjectOut])
    def learn_subjects(
        user: CurrentUser,
        class_level: int | None = Query(default=None),
    ) -> list[SubjectOut]:
        return list_subjects(class_level)

    @app.get("/learn/subjects/{subject}/chapters", response_model=list[ChapterSummaryOut])
    def learn_subject_chapters(
        subject: str,
        user: CurrentUser,
        class_level: int | None = Query(default=None),
    ) -> list[ChapterSummaryOut]:
        chapters = subject_chapters(subject, class_level)
        if not chapters:
            raise HTTPException(status_code=404, detail="Subject not found")
        return chapters

    @app.get("/learn/subjects/{subject}/chapters/{chapter}", response_model=ChapterContentOut)
    def learn_chapter_content(
        subject: str,
        chapter: str,
        user: CurrentUser,
        class_level: int | None = Query(default=None),
    ) -> ChapterContentOut:
        content = chapter_content(subject, class_level, chapter)
        if content is None:
            raise HTTPException(status_code=404, detail="Chapter not found")
        return content

    def authorize_student_access(db: Session, student_id: int, user: User) -> Student:
        student = db.get(Student, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        if user.role in ("teacher", "admin"):
            return student
        if user.role == "student" and student.user_id == user.id:
            return student
        raise HTTPException(status_code=403, detail="Not allowed to access this student")

    def _build_me_response(db: Session, user: User) -> MeResponse:
        profile_id: int | None = None
        name: str | None = None
        class_level: int | None = None
        if user.role == "student":
            student = db.execute(
                select(Student).where(Student.user_id == user.id)
            ).scalar_one_or_none()
            if student is not None:
                profile_id, name, class_level = student.id, student.name, student.class_level
        elif user.role == "teacher":
            teacher = db.execute(
                select(Teacher).where(Teacher.user_id == user.id)
            ).scalar_one_or_none()
            if teacher is not None:
                profile_id, name = teacher.id, teacher.name
        elif user.role == "parent":
            parent = db.execute(
                select(Parent).where(Parent.user_id == user.id)
            ).scalar_one_or_none()
            if parent is not None:
                profile_id, name = parent.id, parent.name
        return MeResponse(
            user_id=user.id,
            email=user.email,
            role=user.role,
            profile_id=profile_id,
            name=name,
            class_level=class_level,
        )

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "env": settings.env,
        }

    @app.get("/live")
    async def live() -> dict:
        return {"status": "alive"}

    @app.get("/ready")
    async def ready(db: DbSession) -> dict:
        if provider is None:
            detail = (
                f"LLM_PROVIDER={settings.llm_provider!r} is not implemented yet. "
                "Set LLM_PROVIDER=mock or configure a supported provider."
            )
            raise HTTPException(status_code=503, detail=detail)
        try:
            db.execute(select(1))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"status": "ready", "provider": provider.name}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.post("/auth/register", response_model=RegisterResponse, status_code=201)
    def register(request: Request, payload: RegisterRequest, db: DbSession) -> RegisterResponse:
        email = payload.email.strip().lower()
        existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "email_taken", "message": "Email already registered"},
            )
        # Email verification is enforced only when SMTP delivery exists;
        # otherwise accounts are trusted as verified (dev/small deployments).
        verified = not smtp_configured(settings)
        user = User(
            email=email,
            password_hash=hash_password(payload.password),
            role=payload.role,
            email_verified=verified,
        )
        db.add(user)
        try:
            # Unique violation on users.email surfaces here when a concurrent
            # registration won the race between our check and this insert.
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"code": "email_taken", "message": "Email already registered"},
            ) from exc
        profile: Student | Teacher | Parent
        if payload.role == "student":
            consent_ip = request.client.host if request.client else None
            profile = Student(
                name=payload.name.strip(),
                class_level=payload.class_level,
                user_id=user.id,
                consent_ip=consent_ip,
                consent_at=datetime.now(UTC),
                consent_version=CONSENT_VERSION,
            )
        elif payload.role == "parent":
            profile = Parent(name=payload.name.strip(), user_id=user.id)
        else:
            profile = Teacher(name=payload.name.strip(), user_id=user.id)
        db.add(profile)
        db.commit()
        if not verified:
            _send_verification_email(db, settings, user)
        return RegisterResponse(user_id=user.id, role=user.role, profile_id=profile.id)

    def _send_verification_email(db: Session, settings: Settings, user: User) -> None:
        token = secrets.token_urlsafe(32)
        db.add(
            EmailVerification(
                user_id=user.id,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
            )
        )
        db.commit()
        send_mail(
            settings,
            to=user.email,
            subject="ইমেইল যাচাই / Verify your email",
            body=(
                "Bangla GPT Tutor-এ স্বাগতম! "
                "ইমেইল যাচাই করতে নিচের কোডটি "
                "অ্যাপের ঘরে দিন (২৪ ঘণ্টা বৈধ):\n\n"
                f"{token}\n"
            ),
        )

    @app.post("/auth/verify-email", response_model=TokenResponse)
    def verify_email(payload: VerifyEmailRequest, db: DbSession) -> TokenResponse:
        """Complete email verification with the token from the mail.

        On success the account is marked verified and a session is issued.
        """
        now = datetime.now(UTC).replace(tzinfo=None)
        row = db.execute(
            select(EmailVerification).where(
                EmailVerification.token_hash == hashlib.sha256(payload.token.encode()).hexdigest(),
                EmailVerification.used_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None or row.expires_at < now:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_token", "message": "Invalid or expired verification code"},
            )
        row.used_at = now
        user = db.get(User, row.user_id)
        if user is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_token", "message": "Invalid or expired verification code"},
            )
        user.email_verified = True
        db.commit()
        return TokenResponse(access_token=create_access_token(user, settings=settings))

    @app.post("/auth/resend-verification", status_code=202)
    def resend_verification(db: DbSession, user: CurrentUser) -> dict:
        if smtp_configured(settings) and not user.email_verified:
            _send_verification_email(db, settings, user)
        return {"status": "accepted"}

    @app.post("/auth/login", response_model=TokenResponse)
    def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
        email = payload.email.strip().lower()
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if (
            user is None
            or not verify_password(payload.password, user.password_hash)
            or not user.email_verified
        ):
            # Unverified accounts get the same generic 401 as bad credentials,
            # but with a machine-readable code so the UI can offer "resend".
            unverified = user is not None and not user.email_verified
            if unverified:
                raise HTTPException(
                    status_code=403,
                    detail={"code": "email_unverified", "message": "Email verification required"},
                )
            raise HTTPException(
                status_code=401,
                detail={"code": "bad_credentials", "message": "Incorrect email or password"},
            )
        token = create_access_token(user, settings=settings)
        return TokenResponse(access_token=token, must_change_password=user.must_change_password)

    def _hash_reset_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @app.post("/auth/forgot", status_code=202)
    def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> dict:
        """Start a password reset.

        Always returns 202 with a generic body so attackers cannot enumerate
        registered email addresses. Tokens are single-use, expire after
        ``password_reset_token_minutes`` and only their SHA-256 hash is stored.
        """
        email = payload.email.strip().lower()
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            return {"status": "accepted"}

        now = datetime.now(UTC).replace(tzinfo=None)
        pending = (
            db.execute(
                select(PasswordReset).where(
                    PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
                )
            )
            .scalars()
            .all()
        )
        for row in pending:
            row.used_at = now

        token = secrets.token_urlsafe(32)
        db.add(
            PasswordReset(
                user_id=user.id,
                token_hash=_hash_reset_token(token),
                expires_at=now + timedelta(minutes=settings.password_reset_token_minutes),
            )
        )
        db.commit()

        delivered = send_mail(
            settings,
            to=user.email,
            subject="পাসওয়ার্ড রিসেট / Password reset",
            body=(f"পাসওয়ার্ড রিসেট করতে নিচের টোকেনটি ব্যবহার করুন (৩০ মিনিটের জন্য বৈধ):\n\n{token}\n"),
        )
        if not delivered:
            if settings.is_production:
                json_log(
                    logger,
                    logging.WARNING,
                    "password_reset_email_undeliverable",
                    smtp_configured=smtp_configured(settings),
                )
            else:
                # Non-production convenience: the only place the raw token is
                # ever logged; never emitted when ENV=production.
                json_log(logger, logging.INFO, "password_reset_token_console", token=token)
        return {"status": "accepted"}

    @app.post("/auth/reset", response_model=TokenResponse)
    def reset_password(payload: ResetPasswordRequest, db: DbSession) -> TokenResponse:
        now = datetime.now(UTC).replace(tzinfo=None)
        row = db.execute(
            select(PasswordReset).where(
                PasswordReset.token_hash == _hash_reset_token(payload.token),
                PasswordReset.used_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None or row.expires_at < now:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        row.used_at = now
        user = db.get(User, row.user_id)
        if user is None:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = False
        db.commit()
        return TokenResponse(access_token=create_access_token(user, settings=settings))

    @app.post("/auth/change-password", response_model=TokenResponse)
    def change_password(
        payload: ChangePasswordRequest, db: DbSession, user: CurrentUser
    ) -> TokenResponse:
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if payload.current_password == payload.new_password:
            raise HTTPException(
                status_code=422, detail="New password must differ from the current one"
            )
        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = False
        db.commit()
        return TokenResponse(access_token=create_access_token(user, settings=settings))

    @app.post("/tutor/ask", response_model=AskResponse)
    async def ask(payload: AskRequest, user: CurrentUser) -> AskResponse:
        if tutor is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
            )
        try:
            return await tutor.ask(
                payload.question,
                payload.class_level,
                canonical_subject(payload.subject),
            )
        except ProviderError as exc:
            # Upstream LLM failure (timeout/exhausted retries/blocked) must be a
            # controlled 502, never an unhandled 500.
            raise HTTPException(
                status_code=502,
                detail={"code": "llm_unavailable", "message": "LLM provider unavailable"},
            ) from exc

    # ------------------------------------------------------------------
    # Multi-turn tutoring chat (A3)
    # ------------------------------------------------------------------

    def _student_profile(db: Session, user: User) -> Student:
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "no_student_profile", "message": "Student profile not found"},
            )
        return student

    def _own_conversation(db: Session, conversation_id: int, user: User) -> Conversation:
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "conversation_not_found", "message": "Conversation not found"},
            )
        owner = db.execute(
            select(Student).where(Student.id == conv.student_id)
        ).scalar_one_or_none()
        if owner is None or owner.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "not_allowed",
                    "message": "Not allowed to access this conversation",
                },
            )
        return conv

    @app.post("/tutor/conversations", response_model=ConversationOut, status_code=201)
    def create_conversation(payload: ConversationCreate, db: DbSession, user: CurrentUser):
        student = _student_profile(db, user)
        conv = Conversation(student_id=student.id, title=payload.title)
        db.add(conv)
        db.commit()
        return ConversationOut(
            id=conv.id, title=conv.title, created_at=conv.created_at, message_count=0
        )

    @app.get("/tutor/conversations", response_model=list[ConversationOut])
    def list_conversations(db: DbSession, user: CurrentUser) -> list[ConversationOut]:
        student = _student_profile(db, user)
        rows = (
            db.execute(
                select(Conversation)
                .where(Conversation.student_id == student.id)
                .order_by(Conversation.created_at.desc())
                .limit(100)
            )
            .scalars()
            .all()
        )
        out: list[ConversationOut] = []
        for conv in rows:
            count = db.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.conversation_id == conv.id)
            ).scalar_one()
            out.append(
                ConversationOut(
                    id=conv.id, title=conv.title, created_at=conv.created_at, message_count=count
                )
            )
        return out

    @app.get("/tutor/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
    def conversation_messages(
        conversation_id: int, db: DbSession, user: CurrentUser
    ) -> list[ChatMessageOut]:
        _own_conversation(db, conversation_id, user)
        rows = (
            db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.id)
            )
            .scalars()
            .all()
        )
        return [
            ChatMessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                grounded=m.grounded,
                refused_reason=m.refused_reason,
                sources=[SourceRef(**s) for s in (m.sources_json or [])],
                rating=m.rating,
                created_at=m.created_at,
            )
            for m in rows
        ]

    def _chat_history(db: Session, conversation_id: int) -> list[dict[str, str]]:
        rows = (
            db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.id.desc())
                .limit(settings.chat_history_messages)
            )
            .scalars()
            .all()
        )
        history = [{"role": m.role, "content": m.content} for m in reversed(rows)]
        return history

    @app.post("/tutor/conversations/{conversation_id}/messages", response_model=ChatMessageOut)
    async def send_chat_message(
        conversation_id: int, payload: ChatSendRequest, db: DbSession, user: CurrentUser
    ) -> ChatMessageOut:
        """Non-streaming chat turn: persists both sides and returns the reply."""
        if tutor is None:
            raise HTTPException(status_code=503, detail="Tutor service unavailable")
        conv = _own_conversation(db, conversation_id, user)
        student = _student_profile(db, user)
        class_level = payload.class_level or student.class_level or 6
        history = _chat_history(db, conv.id)

        user_msg = ChatMessage(conversation_id=conv.id, role="user", content=payload.message)
        db.add(user_msg)
        # Flush (not commit): the user turn must not survive a failed LLM call,
        # otherwise the provider error leaves an orphan message behind.
        db.flush()

        try:
            result = await tutor.ask(
                payload.message, class_level, canonical_subject(payload.subject), history
            )
        except ProviderError as exc:
            db.rollback()
            raise HTTPException(
                status_code=502,
                detail={"code": "llm_unavailable", "message": "LLM provider unavailable"},
            ) from exc

        assistant_msg = ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=result.answer,
            grounded=result.grounded,
            refused_reason=result.refused_reason,
            sources_json=[s.model_dump() for s in result.sources],
        )
        db.add(assistant_msg)
        if conv.title is None:
            conv.title = payload.message[:80]
        db.commit()
        return ChatMessageOut(
            id=assistant_msg.id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            grounded=assistant_msg.grounded,
            refused_reason=assistant_msg.refused_reason,
            sources=result.sources,
            rating=None,
            created_at=assistant_msg.created_at,
        )

    @app.post("/tutor/conversations/{conversation_id}/messages/stream")
    async def stream_chat_message(
        conversation_id: int, payload: ChatSendRequest, db: DbSession, user: CurrentUser
    ) -> StreamingResponse:
        """SSE streaming chat turn: token events, then one final JSON event."""
        if tutor is None:
            raise HTTPException(status_code=503, detail="Tutor service unavailable")
        conv = _own_conversation(db, conversation_id, user)
        student = _student_profile(db, user)
        class_level = payload.class_level or student.class_level or 6
        history = _chat_history(db, conv.id)

        user_msg = ChatMessage(conversation_id=conv.id, role="user", content=payload.message)
        db.add(user_msg)
        # Flush (not commit): committed only together with the assistant reply,
        # so a provider failure mid-stream cannot leave an orphan user turn.
        db.flush()

        async def event_stream() -> AsyncIterator[str]:
            try:
                final_response: AskResponse | None = None
                async for event in tutor.ask_stream(  # type: ignore[union-attr]
                    payload.message,
                    class_level,
                    canonical_subject(payload.subject),
                    history,
                ):
                    if event.type == "token":
                        token_payload = json.dumps({"text": event.text}, ensure_ascii=False)
                        yield f"event: token\ndata: {token_payload}\n\n"
                    elif event.response is not None:
                        final_response = event.response
                if final_response is None:  # never leak a naked 500 under -O
                    db.rollback()
                    yield (
                        "event: error\ndata: "
                        + json.dumps({"code": "llm_unavailable"}, ensure_ascii=False)
                        + "\n\n"
                    )
                    return
                assistant_msg = ChatMessage(
                    conversation_id=conv.id,
                    role="assistant",
                    content=final_response.answer,
                    grounded=final_response.grounded,
                    refused_reason=final_response.refused_reason,
                    sources_json=[s.model_dump() for s in final_response.sources],
                )
                db.add(assistant_msg)
                if conv.title is None:
                    conv.title = payload.message[:80]
                db.commit()
                done_payload = {
                    "user_message_id": user_msg.id,
                    "message_id": assistant_msg.id,
                    **final_response.model_dump(),
                }
                yield (
                    "event: done\ndata: " + json.dumps(done_payload, ensure_ascii=False) + "\n\n"
                )
            except ProviderError:
                db.rollback()
                yield (
                    "event: error\ndata: "
                    + json.dumps({"code": "llm_unavailable"}, ensure_ascii=False)
                    + "\n\n"
                )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # ------------------------------------------------------------------
    # Feedback & privacy-safe product analytics (B12)
    # ------------------------------------------------------------------

    @app.post("/feedback", status_code=201)
    def submit_feedback(payload: FeedbackRequest, db: DbSession, user: CurrentUser) -> dict:
        if payload.message_id is None and payload.attempt_id is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "missing_target", "message": "message_id or attempt_id required"},
            )
        row = Feedback(
            user_id=user.id,
            message_id=payload.message_id,
            attempt_id=payload.attempt_id,
            rating=payload.rating,
            comment=payload.comment,
        )
        if payload.message_id is not None:
            msg = db.get(ChatMessage, payload.message_id)
            if msg is not None and payload.rating in (-1, 1):
                msg.rating = payload.rating
        db.add(row)
        db.commit()
        return {"status": "recorded"}

    @app.post("/events", status_code=202)
    def record_event(payload: AnalyticsEvent, request: Request, user: CurrentUser) -> dict:
        # Privacy: log only which prop keys were sent, never their values —
        # props are arbitrary client input and may contain personal data.
        json_log(
            logger,
            logging.INFO,
            "product_event",
            name=payload.name,
            props_keys=sorted(payload.props.keys()),
            role=user.role,
        )
        return {"status": "accepted"}

    @app.get("/users/me", response_model=MeResponse)
    def read_me(db: DbSession, user: CurrentUser) -> MeResponse:
        return _build_me_response(db, user)

    @app.delete("/users/me", status_code=204)
    def delete_me(db: DbSession, user: CurrentUser) -> Response:
        """GDPR-style self-service account deletion.

        Removes the account and all owned profile data: student/teacher/parent
        profile, quiz attempts + answer logs, and parent-student links.
        The last remaining admin cannot delete their own account (409).
        """
        if user.role == "admin":
            admins = db.execute(
                select(func.count()).select_from(User).where(User.role == "admin")
            ).scalar_one()
            if admins <= 1:
                raise HTTPException(status_code=409, detail="Cannot delete the last admin")

        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        parent = db.execute(select(Parent).where(Parent.user_id == user.id)).scalar_one_or_none()
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()

        if parent is not None:
            db.execute(delete(ParentStudentLink).where(ParentStudentLink.parent_id == parent.id))
            db.delete(parent)
        if teacher is not None:
            db.delete(teacher)
        if student is not None:
            attempt_ids = (
                db.execute(select(QuizAttempt.id).where(QuizAttempt.student_id == student.id))
                .scalars()
                .all()
            )
            if attempt_ids:
                db.execute(delete(AnswerLog).where(AnswerLog.attempt_id.in_(attempt_ids)))
            conv_ids = (
                db.execute(select(Conversation.id).where(Conversation.student_id == student.id))
                .scalars()
                .all()
            )
            if conv_ids:
                db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids)))
            db.execute(delete(Conversation).where(Conversation.student_id == student.id))
            db.execute(delete(Feedback).where(Feedback.user_id == user.id))
            db.execute(delete(QuizAttempt).where(QuizAttempt.student_id == student.id))
            db.execute(delete(ParentStudentLink).where(ParentStudentLink.student_id == student.id))
            db.execute(delete(ParentInvite).where(ParentInvite.student_id == student.id))
            db.delete(student)

        db.delete(user)
        db.commit()
        return Response(status_code=204)

    @app.get("/users/me/export", response_model=DataExportResponse)
    def export_me(response: Response, db: DbSession, user: CurrentUser) -> DataExportResponse:
        """Self-service data portability: everything stored about this account."""
        response.headers["Content-Disposition"] = 'attachment; filename="my-data-export.json"'
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        teacher = db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
        parent = db.execute(select(Parent).where(Parent.user_id == user.id)).scalar_one_or_none()

        profile: dict
        attempt_rows: list[QuizAttempt] = []
        links: list[dict] = []
        if student is not None:
            profile = {
                "type": "student",
                "id": student.id,
                "name": student.name,
                "class_level": student.class_level,
                "consent_version": student.consent_version,
                "consent_at": student.consent_at.isoformat() if student.consent_at else None,
            }
            attempt_rows = list(
                db.execute(
                    select(QuizAttempt).where(QuizAttempt.student_id == student.id)
                ).scalars()
            )
            for link in db.execute(
                select(ParentStudentLink).where(ParentStudentLink.student_id == student.id)
            ).scalars():
                links.append({"direction": "linked_by", "parent_id": link.parent_id})
        elif teacher is not None:
            profile = {"type": "teacher", "id": teacher.id, "name": teacher.name}
        elif parent is not None:
            profile = {"type": "parent", "id": parent.id, "name": parent.name}
            for link in db.execute(
                select(ParentStudentLink).where(ParentStudentLink.parent_id == parent.id)
            ).scalars():
                links.append({"direction": "links", "student_id": link.student_id})
        else:
            profile = {"type": None}

        attempts = [
            {
                "id": a.id,
                "subject": a.subject,
                "class_level": a.class_level,
                "status": a.status,
                "total": a.total,
                "correct": a.correct,
                "score_pct": a.score_pct,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in attempt_rows
        ]
        return DataExportResponse(
            user={
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            profile=profile,
            quiz_attempts=attempts,
            parent_links=links,
        )

    @app.get("/students/{student_id}", response_model=StudentResponse)
    def get_student(student_id: int, db: DbSession, user: CurrentUser) -> StudentResponse:
        student = authorize_student_access(db, student_id, user)
        return StudentResponse(id=student.id, name=student.name, class_level=student.class_level)

    @app.post("/quizzes", response_model=QuizStarted)
    def start_quiz(payload: QuizStartRequest, db: DbSession, user: CurrentUser) -> QuizStarted:
        if index is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
            )
        student = authorize_student_access(db, payload.student_id, user)
        class_level = (
            payload.class_level if payload.class_level is not None else student.class_level
        )

        attempt = QuizAttempt(
            student_id=student.id, subject=payload.subject, class_level=class_level
        )
        db.add(attempt)
        db.flush()

        generator = ClozeQuizGenerator(index.chunks)
        questions = generator.generate(
            class_level=class_level,
            subject=canonical_subject(payload.subject),
            num=payload.num_questions,
            seed=attempt.id,
        )
        if not questions:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "no_quiz_for_filter",
                    "message": "No quiz could be generated for this class/subject yet",
                },
            )

        attempt.quiz_json = dump_quiz(questions)
        db.commit()

        note: str | None = None
        if len(questions) < payload.num_questions:
            # A4: never silently short-change the caller — surface a code the
            # UI can translate into an honest, localized notice.
            note = f"partial_quiz:{len(questions)}"

        return QuizStarted(
            attempt_id=attempt.id,
            requested=payload.num_questions,
            note=note,
            questions=[
                QuizQuestionPublic(id=q.id, question_text=q.question_text, options=list(q.options))
                for q in questions
            ],
        )

    @app.post("/quizzes/{attempt_id}/submit", response_model=QuizResult)
    def submit_quiz(
        attempt_id: int, payload: QuizSubmitRequest, db: DbSession, user: CurrentUser
    ) -> QuizResult:
        attempt = db.get(QuizAttempt, attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Attempt not found")
        authorize_student_access(db, attempt.student_id, user)

        # Atomic claim: exactly one concurrent submission may transition
        # open -> graded. Losers get a clean 400 instead of corrupting state.
        claim_stmt = (
            update(QuizAttempt)
            .where(QuizAttempt.id == attempt.id, QuizAttempt.status == "open")
            .values(status="graded")
        )
        claimed = cast(CursorResult[Any], db.execute(claim_stmt))
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=400, detail="Attempt already graded")

        questions = list(attempt.quiz_json)
        if len(payload.answers) != len(questions):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "answer_count_mismatch",
                    "message": "Answer count does not match question count",
                    "expected": len(questions),
                    "received": len(payload.answers),
                },
            )

        correct = 0
        review: list[ReviewItem] = []
        for seq, (question, chosen) in enumerate(zip(questions, payload.answers, strict=True)):
            is_correct = chosen == question["answer_index"]
            correct += is_correct
            db.add(
                AnswerLog(
                    attempt_id=attempt.id,
                    seq=seq,
                    question_text=question["question_text"],
                    chosen=chosen,
                    correct_index=question["answer_index"],
                    is_correct=is_correct,
                    chapter=question["chapter"],
                    book=question["book"],
                )
            )
            review.append(
                ReviewItem(
                    question_text=question["question_text"],
                    options=list(question["options"]),
                    chosen=chosen,
                    correct_index=question["answer_index"],
                    is_correct=is_correct,
                    chapter=question["chapter"],
                )
            )

        total = len(questions)
        attempt.status = "graded"
        attempt.total = total
        attempt.correct = correct
        attempt.score_pct = round(100.0 * correct / total, 2)
        db.commit()

        return QuizResult(
            attempt_id=attempt.id,
            score_pct=attempt.score_pct,
            correct=correct,
            total=total,
            review=review,
        )

    @app.get("/students/{student_id}/progress", response_model=StudentProgress)
    def get_progress(student_id: int, db: DbSession, user: CurrentUser) -> StudentProgress:
        student = authorize_student_access(db, student_id, user)

        attempts = (
            db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student_id))
            .scalars()
            .all()
        )
        graded = [a for a in attempts if a.status == "graded"]

        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        if graded:
            answer_rows = (
                db.execute(
                    select(AnswerLog).where(AnswerLog.attempt_id.in_([a.id for a in graded]))
                )
                .scalars()
                .all()
            )
            for row in answer_rows:
                stats[row.chapter][0] += 1
                stats[row.chapter][1] += row.is_correct

        by_chapter = sorted(
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
        weak_chapters = [s.chapter for s in by_chapter if s.accuracy < 60.0]
        avg_score = (
            round(sum(a.score_pct for a in graded if a.score_pct is not None) / len(graded), 2)
            if graded
            else None
        )

        return StudentProgress(
            student=StudentResponse(
                id=student.id, name=student.name, class_level=student.class_level
            ),
            attempts_graded=len(graded),
            avg_score_pct=avg_score,
            by_chapter=by_chapter,
            weak_chapters=weak_chapters,
        )

    def _load_class_students(db: Session, class_level: int | None) -> list[Student]:
        statement = select(Student).order_by(Student.id)
        if class_level is not None:
            statement = statement.where(Student.class_level == class_level)
        return list(db.execute(statement).scalars().all())

    def _student_briefs(db: Session, students: list[Student]) -> list[StudentBrief]:
        briefs: list[StudentBrief] = []
        for student in students:
            attempts = (
                db.execute(
                    select(QuizAttempt).where(
                        QuizAttempt.student_id == student.id, QuizAttempt.status == "graded"
                    )
                )
                .scalars()
                .all()
            )
            scores = [a.score_pct for a in attempts if a.score_pct is not None]
            avg = round(sum(scores) / len(scores), 2) if scores else None
            briefs.append(
                StudentBrief(
                    student_id=student.id,
                    name=student.name,
                    class_level=student.class_level,
                    attempts_graded=len(attempts),
                    avg_score_pct=avg,
                )
            )
        return briefs

    @app.get("/teacher/students", response_model=list[StudentBrief])
    def teacher_roster(
        db: DbSession, teacher: TeacherOrAdminUser, class_level: int | None = None
    ) -> list[StudentBrief]:
        students = _load_class_students(db, class_level)
        return _student_briefs(db, students)

    @app.get("/teacher/classes/{class_level}/analytics", response_model=ClassAnalytics)
    def teacher_analytics(
        class_level: int, db: DbSession, teacher: TeacherOrAdminUser
    ) -> ClassAnalytics:
        students = _load_class_students(db, class_level)
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

    @app.get("/admin/users", response_model=AdminUsersPage)
    def admin_list_users(
        db: DbSession,
        admin: AdminUser,
        q: str | None = Query(default=None, max_length=120),
        role: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> AdminUsersPage:
        """Paginated, searchable user list (C18)."""
        statement = select(User)
        count_stmt = select(func.count()).select_from(User)
        if q:
            like = f"%{q.strip().lower()}%"
            statement = statement.where(func.lower(User.email).like(like))
            count_stmt = count_stmt.where(func.lower(User.email).like(like))
        if role:
            statement = statement.where(User.role == role)
            count_stmt = count_stmt.where(User.role == role)
        total = db.execute(count_stmt).scalar_one()
        rows = db.execute(statement.order_by(User.id).offset(offset).limit(limit)).scalars().all()
        return AdminUsersPage(
            total=total,
            items=[
                UserPublic(id=u.id, email=u.email, role=u.role, created_at=u.created_at)
                for u in rows
            ],
        )

    @app.patch("/admin/users/{user_id}/role", response_model=UserPublic)
    def admin_update_role(
        user_id: int, payload: RoleUpdateRequest, db: DbSession, admin: AdminUser
    ) -> UserPublic:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if target.role == "admin" and payload.role != "admin":
            admins = db.execute(
                select(func.count()).select_from(User).where(User.role == "admin")
            ).scalar_one()
            if admins <= 1:
                raise HTTPException(status_code=409, detail="Cannot demote the last admin")
        target.role = payload.role
        db.commit()
        db.refresh(target)
        return UserPublic(
            id=target.id, email=target.email, role=target.role, created_at=target.created_at
        )

    @app.get("/admin/analytics/overview", response_model=AdminOverview)
    def admin_overview(db: DbSession, admin: AdminUser) -> AdminOverview:
        users = db.execute(select(User)).scalars().all()
        by_role: dict[str, int] = defaultdict(int)
        for u in users:
            by_role[u.role] += 1
        attempts = (
            db.execute(select(QuizAttempt).where(QuizAttempt.status == "graded")).scalars().all()
        )
        scores = [a.score_pct for a in attempts if a.score_pct is not None]
        return AdminOverview(
            users_total=len(users),
            students=by_role.get("student", 0),
            teachers=by_role.get("teacher", 0),
            admins=by_role.get("admin", 0),
            parents=by_role.get("parent", 0),
            quiz_attempts_graded=len(attempts),
            avg_score_pct=round(sum(scores) / len(scores), 2) if scores else None,
        )

    @app.post("/admin/maintenance/purge", response_model=dict)
    def admin_purge_expired(db: DbSession, admin: AdminUser) -> dict:
        """Retention sweep (D20): expired tokens, stale invites, old chats.

        Child-data minimization: conversations older than
        ``chat_retention_days`` are deleted with their messages.
        """
        now = datetime.now(UTC).replace(tzinfo=None)
        chat_cutoff = now - timedelta(days=settings.chat_retention_days)

        old_convs = (
            db.execute(select(Conversation.id).where(Conversation.created_at < chat_cutoff))
            .scalars()
            .all()
        )
        deleted_messages = 0
        if old_convs:
            deleted_messages = cast(
                CursorResult[Any],
                db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(old_convs))),
            ).rowcount
            db.execute(delete(Conversation).where(Conversation.id.in_(old_convs)))

        deleted_resets = cast(
            CursorResult[Any],
            db.execute(
                delete(PasswordReset).where(PasswordReset.expires_at < now - timedelta(days=30))
            ),
        ).rowcount
        deleted_verifications = cast(
            CursorResult[Any],
            db.execute(
                delete(EmailVerification).where(
                    EmailVerification.expires_at < now - timedelta(days=30)
                )
            ),
        ).rowcount
        deleted_invites = cast(
            CursorResult[Any],
            db.execute(
                delete(ParentInvite).where(
                    ParentInvite.expires_at < now - timedelta(days=30),
                    ParentInvite.used_at.isnot(None),
                )
            ),
        ).rowcount
        db.commit()
        return {
            "conversations_deleted": len(old_convs),
            "chat_messages_deleted": deleted_messages,
            "password_resets_deleted": deleted_resets,
            "email_verifications_deleted": deleted_verifications,
            "used_invites_deleted": deleted_invites,
        }

    @app.post("/parents/link", status_code=201)
    def parent_link(payload: ParentLinkRequest, db: DbSession, parent: ParentUser) -> dict:
        """Legacy direct-ID linking — disabled by default (V2 hardening).

        An unconsented parent could previously link ANY student_id and read
        their progress. The invite-code flow (`/parents/link/invite`) is the
        consented path; enable ALLOW_DIRECT_PARENT_LINK only for migrations.
        """
        if not settings.allow_direct_parent_link:
            raise HTTPException(
                status_code=410,
                detail={
                    "code": "direct_link_disabled",
                    "message": "Use the student's invite code via /parents/link/invite",
                },
            )
        parent_profile = db.execute(
            select(Parent).where(Parent.user_id == parent.id)
        ).scalar_one_or_none()
        if parent_profile is None:
            parent_profile = Parent(name=parent.email.split("@")[0], user_id=parent.id)
            db.add(parent_profile)
            db.flush()
        student = db.get(Student, payload.student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        existing = db.execute(
            select(ParentStudentLink).where(
                ParentStudentLink.parent_id == parent_profile.id,
                ParentStudentLink.student_id == student.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Already linked")
        db.add(ParentStudentLink(parent_id=parent_profile.id, student_id=student.id))
        try:
            db.commit()
        except IntegrityError as exc:
            # Lost a race against a concurrent duplicate link.
            db.rollback()
            raise HTTPException(status_code=409, detail="Already linked") from exc
        return {"linked": True, "parent_id": parent_profile.id, "student_id": student.id}

    # ------------------------------------------------------------------
    # Parent invite-code flow (C17): students generate a single-use code,
    # parents redeem it. No more bare student_id guessing.
    # ------------------------------------------------------------------

    def _hash_invite(code: str) -> str:
        return hashlib.sha256(code.strip().upper().encode()).hexdigest()

    @app.post("/students/me/invite-code", status_code=201)
    def create_parent_invite(db: DbSession, user: CurrentUser) -> dict:
        if user.role != "student":
            raise HTTPException(status_code=403, detail="Students only")
        student = _student_profile(db, user)
        active = (
            db.execute(
                select(ParentInvite).where(
                    ParentInvite.student_id == student.id,
                    ParentInvite.used_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        active = [i for i in active if i.expires_at > now]
        for stale in active[2:]:  # keep at most 3 live codes per student
            db.delete(stale)
        code = "BGPT-" + secrets.token_hex(4).upper()
        db.add(
            ParentInvite(
                code_hash=_hash_invite(code),
                student_id=student.id,
                expires_at=now + timedelta(minutes=settings.invite_ttl_minutes),
            )
        )
        db.commit()
        return {"code": code, "expires_in_minutes": settings.invite_ttl_minutes}

    @app.post("/parents/link/invite", status_code=201)
    def link_via_invite(
        payload: ParentInviteLinkRequest, db: DbSession, parent: ParentUser
    ) -> dict:
        now = datetime.now(UTC).replace(tzinfo=None)
        invite = db.execute(
            select(ParentInvite).where(ParentInvite.code_hash == _hash_invite(payload.code))
        ).scalar_one_or_none()
        if invite is None or invite.used_at is not None or invite.expires_at < now:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_invite", "message": "Invalid or expired invite code"},
            )
        parent_profile = db.execute(
            select(Parent).where(Parent.user_id == parent.id)
        ).scalar_one_or_none()
        if parent_profile is None:
            parent_profile = Parent(name=parent.email.split("@")[0], user_id=parent.id)
            db.add(parent_profile)
            db.flush()
        existing = db.execute(
            select(ParentStudentLink).where(
                ParentStudentLink.parent_id == parent_profile.id,
                ParentStudentLink.student_id == invite.student_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(ParentStudentLink(parent_id=parent_profile.id, student_id=invite.student_id))
        invite.used_at = now
        invite.used_by_parent_id = parent_profile.id
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Already linked") from exc
        return {
            "linked": True,
            "parent_id": parent_profile.id,
            "student_id": invite.student_id,
        }

    @app.get("/parents/me/children", response_model=list[StudentBrief])
    def parent_children(db: DbSession, parent: ParentUser) -> list[StudentBrief]:
        parent_profile = db.execute(
            select(Parent).where(Parent.user_id == parent.id)
        ).scalar_one_or_none()
        if parent_profile is None:
            return []
        links = (
            db.execute(
                select(ParentStudentLink).where(ParentStudentLink.parent_id == parent_profile.id)
            )
            .scalars()
            .all()
        )
        if not links:
            return []
        students = (
            db.execute(select(Student).where(Student.id.in_([link.student_id for link in links])))
            .scalars()
            .all()
        )
        return _student_briefs(db, list(students))

    @app.get("/parents/me/children/{student_id}/progress", response_model=StudentProgress)
    def parent_child_progress(
        student_id: int, db: DbSession, parent: ParentUser
    ) -> StudentProgress:
        parent_profile = db.execute(
            select(Parent).where(Parent.user_id == parent.id)
        ).scalar_one_or_none()
        if parent_profile is None:
            raise HTTPException(status_code=404, detail="Not linked to this student")
        link = db.execute(
            select(ParentStudentLink).where(
                ParentStudentLink.parent_id == parent_profile.id,
                ParentStudentLink.student_id == student_id,
            )
        ).scalar_one_or_none()
        if link is None:
            raise HTTPException(status_code=404, detail="Not linked to this student")
        student = db.get(Student, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        attempts = (
            db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student_id))
            .scalars()
            .all()
        )
        graded = [a for a in attempts if a.status == "graded"]
        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        if graded:
            rows = (
                db.execute(
                    select(AnswerLog).where(AnswerLog.attempt_id.in_([a.id for a in graded]))
                )
                .scalars()
                .all()
            )
            for row in rows:
                stats[row.chapter][0] += 1
                stats[row.chapter][1] += row.is_correct
        by_chapter = sorted(
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
        weak_chapters = [s.chapter for s in by_chapter if s.accuracy < 60.0]
        avg_score = (
            round(sum(a.score_pct for a in graded if a.score_pct is not None) / len(graded), 2)
            if graded
            else None
        )
        return StudentProgress(
            student=StudentResponse(
                id=student.id, name=student.name, class_level=student.class_level
            ),
            attempts_graded=len(graded),
            avg_score_pct=avg_score,
            by_chapter=by_chapter,
            weak_chapters=weak_chapters,
        )

    return app


app = create_app()
