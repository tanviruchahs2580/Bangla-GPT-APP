import asyncio
import csv
import hashlib
import json
import logging
import random
import secrets
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Generator
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any, cast
from urllib.parse import quote

import jwt as pyjwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from bangla_gpt_api import caching, jobs
from bangla_gpt_api.auth.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from bangla_gpt_api.config import DEFAULT_JWT_SECRET, Settings, get_settings
from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.db.models import (
    AnswerLog,
    Assignment,
    AuditLog,
    ChapterContent,
    ChapterProgress,
    ChatMessage,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    ConceptMastery,
    Conversation,
    DailyActivity,
    EmailVerification,
    Feedback,
    Parent,
    ParentInvite,
    ParentStudentLink,
    PasswordReset,
    QuestionBankEntry,
    QuestionPaper,
    QuizAttempt,
    RevisionItem,
    School,
    SchoolInvite,
    ShortTest,
    Student,
    StudentAbility,
    StudentInvite,
    SupportPlan,
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
    get_fast_provider,
    get_provider,
)
from bangla_gpt_api.ratelimit import (
    RateLimitBackendError,
    RateLimiter,
    build_limiter,
)
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.retrieval.bm25 import BM25Index, tokenize
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.schemas import (
    ActivityDay,
    ActivitySummary,
    AdminAuditPage,
    AdminOverview,
    AdminSchoolStatsOut,
    AdminUsersPage,
    AnalyticsEvent,
    AskRequest,
    AskResponse,
    AssignmentIn,
    AssignmentMineOut,
    AssignmentOut,
    AssignmentProgressRow,
    AuditRowOut,
    ChangePasswordRequest,
    ChapterContentEditIn,
    ChapterContentKey,
    ChapterContentVersionOut,
    ChapterProgressIn,
    ChapterProgressOut,
    ChapterSections,
    ChapterStat,
    ChatMessageOut,
    ChatSendRequest,
    ClassAnalytics,
    ClassImportIn,
    ClassImportOut,
    ClassImportRowOut,
    ClassRoomCreateIn,
    ClassRoomOut,
    ConsentReconfirmIn,
    ConsentStatusOut,
    ContentVersionRowOut,
    ContinueLearning,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    CoverageCell,
    CoverageOut,
    DashboardSummary,
    DataExportResponse,
    FeedbackAdminRow,
    FeedbackQueuePage,
    FeedbackRequest,
    ForgotPasswordRequest,
    ImpersonateOut,
    ImpersonateRequest,
    KgGapOut,
    KgGapsOut,
    KgRebuildOut,
    LessonPlanIn,
    LessonPlanOut,
    LoginRequest,
    MeResponse,
    MessageSearchHit,
    ParentInviteLinkRequest,
    ParentLinkRequest,
    QPDraftIn,
    QPOut,
    QPQuestion,
    QPReplaceIn,
    QPReviewIn,
    QuickAction,
    QuizQuestionPublic,
    QuizResult,
    QuizStarted,
    QuizStartRequest,
    QuizSubmitRequest,
    Recommendation,
    RefusalAuditOut,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ReteachCardOut,
    ReviewItem,
    RevisionDueOut,
    RevisionItemOut,
    RevisionReviewIn,
    RoleUpdateRequest,
    RosterEntryOut,
    SchoolAtRiskRow,
    SchoolCreateIn,
    SchoolHealthOut,
    SchoolInviteAdminOut,
    SchoolInviteIn,
    SchoolInviteOut,
    SchoolJoinIn,
    SchoolOut,
    SchoolOverviewOut,
    SchoolStaffOut,
    SearchHit,
    SearchResponse,
    ShortTestIn,
    ShortTestMineOut,
    ShortTestOut,
    SourceRef,
    StatusComponent,
    StatusOut,
    StudentBrief,
    StudentProgress,
    StudentResponse,
    SupportPlanIn,
    SupportPlanOut,
    TeacherContentOut,
    TokenResponse,
    TriageUpdate,
    UserPublic,
    VerifyEmailRequest,
    WeakCell,
    WeakMatrixOut,
    WeakStudent,
)
from bangla_gpt_api.security import decrypt_pii, encrypt_pii, write_audit
from bangla_gpt_api.services import (
    adaptive,
    atrisk,
    coverage,
    govt_report,
    knowledge,
    revision,
    weakness,
)
from bangla_gpt_api.services import teach_strategy as teach
from bangla_gpt_api.services.activity import (
    dhaka_date,
    heatmap_days,
    record_activity,
    streak_days,
)
from bangla_gpt_api.services.context import (
    RequestContext,
    history_summary,
    snapshot_mastery,
)
from bangla_gpt_api.services.generators import (
    generate_chapter_content,
    generate_lesson_plan,
    generate_question_paper,
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
from bangla_gpt_api.services.qp_pdf import render_qp_html, render_qp_pdf
from bangla_gpt_api.services.question_bank import (
    bank_keys,
    dedupe_key,
    find_reusable,
    store_reviewed,
)
from bangla_gpt_api.services.quiz import ClozeQuizGenerator, dump_quiz
from bangla_gpt_api.services.quiz_explain import quiz_explain_instruction
from bangla_gpt_api.services.retention import run_retention_sweep
from bangla_gpt_api.services.tutor import TutorService

logger = logging.getLogger(__name__)

# Canonical subject keys used by the corpus; aliases accepted from clients
# are normalized so 'math' and 'mathematics' both resolve (frontend bug fix).
_SUBJECT_ALIASES = {"math": "mathematics", "গণিত": "mathematics"}


def canonical_subject(subject: str | None) -> str | None:
    if subject is None:
        return None
    return _SUBJECT_ALIASES.get(subject.strip().lower(), subject.strip().lower())


# S1.11: interrogative Bangla words (written as escapes so the source stays
# ASCII-safe). Used both for question-like queries (ask-in-Tutor action) and
# for question-style textbook sections (trailing interrogative word).
_INTERROGATIVE_TOKENS = frozenset(
    {
        "\u0995\u09bf",  # ki
        "\u0995\u09c0",  # kii
        "\u0995\u09c7\u09a8",  # keno
        "\u0995\u0996\u09a8",  # kokhon
        "\u0995\u09a4",  # kot
        "\u0995\u09be\u09b0",  # kar
        "\u0995\u09cb\u09a5\u09be\u09df",  # kothay
        "\u0995\u09c7\u09ae\u09a8",  # kemon
        "\u0995\u09cb\u09a8",  # kon
        "\u0995\u09bf\u09ad\u09be\u09ac\u09c8",  # kibhabe
        "\u0995\u09bf\u09ad\u09be\u09ac\u09c7",  # ki vabe
    }
)


def _is_question_like(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith("?"):
        return True
    return any(token in _INTERROGATIVE_TOKENS for token in tokenize(stripped))


# S5.8: bumping this string makes every previously-consented student
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
    if not settings.pii_enc_key:
        problems.append("PII_ENC_KEY must be set in production (guardian phone encryption)")
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
        # S5.6: CSP with a per-response nonce. The API itself only returns
        # JSON (the nonce is belt-and-braces for any future HTML response).
        # The SPA ships no inline script at all (apps/web/public/theme-boot.js
        # is a static file), so Caddy serves it a plain script-src 'self'
        # policy -- the stock caddy:2-alpine image cannot mint nonces (verified
        # against v2.11.4). /docs and /redoc bootstrap with inline + CDN
        # scripts and are deliberately exempt (dev surfaces).
        if request.url.path not in ("/docs", "/redoc", "/openapi.json"):
            nonce = secrets.token_urlsafe(16)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'self'; "
                "form-action 'self'; frame-ancestors 'none'"
            )
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
    if settings.jobs_backend not in ("inline", "arq"):
        raise RuntimeError(
            f"JOBS_BACKEND={settings.jobs_backend!r} is not supported; use 'inline' or 'arq'"
        )
    app = FastAPI(title=settings.app_name, version=settings.version)
    app.state.settings = settings
    # S5.3: shared caches (Redis when backend=redis + REDIS_URL, else bounded
    # in-process memory cache; identical API either way).
    cache = caching.build_cache(settings)
    app.state.cache = cache

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

    def _build_index(chunks: list[Chunk]) -> RankingIndex:
        # S4.3 RAG v2: hybrid = BM25 lane + vector lane fused via RRF and
        # lexically reranked; "bm25" keeps the v1 lexical baseline.
        # S5.3: transparent query-result cache on top (hashed keys, R11;
        # class/subject stay part of the key so class-scope isolation holds).
        if settings.retrieval_mode.strip().lower() == "hybrid":
            inner: RankingIndex = HybridIndex(chunks, build_embedder(settings))
        else:
            inner = BM25Index(chunks)
        return caching.CachedRankingIndex(inner, cache, ttl=caching.RAG_CACHE_TTL_SECONDS)

    index: RankingIndex | None = None
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
                index = _build_index(nctb_chunks)
        if index is None:
            index = _build_index(load_sample_corpus())
        # S4.2: SIMPLE routes may ride a separate fast client; None (mock
        # mode or GEMINI_FAST_MODEL unset) keeps the main provider on all routes.
        fast_provider = None
        try:
            fast_provider = get_fast_provider(settings)
        except ProviderNotConfigured:
            fast_provider = None
        if fast_provider is not None and hasattr(fast_provider, "aclose"):
            app.router.on_shutdown.append(fast_provider.aclose)
        tutor = TutorService(index=index, provider=provider, fast_provider=fast_provider)
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
        # S5.10: impersonation tokens are revocable BEFORE their short expiry.
        # The jti lands in the shared cache (Redis when configured: revocation
        # then holds across workers/restarts; memory backend: per-worker) with
        # a TTL that matches the token's own remaining life.
        if payload.get("imp") and isinstance(payload.get("jti"), str):
            if app.state.cache.get_json(f"imp_revoke:{payload['jti']}") is True:
                raise _unauthorized("Impersonation session has ended")
        request.state.jwt_claims = payload
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
    SchoolStaffUser = Annotated[User, Depends(require_roles("school_admin", "admin"))]

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
        phone: str | None = None
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
                # owner-only view of the decrypted guardian phone (S5.6)
                phone = decrypt_pii(parent.phone_enc, settings.pii_enc_key)
        return MeResponse(
            user_id=user.id,
            email=user.email,
            role=user.role,
            profile_id=profile_id,
            name=name,
            class_level=class_level,
            phone=phone,
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

    @app.get("/status", response_model=StatusOut)
    def status(db: DbSession) -> StatusOut:
        """S5.10 public status page payload: booleans and presence only --
        no counts of users, no version/env disclosure, nothing an attacker
        or a curious child could profile (R11)."""
        components: list[StatusComponent] = []
        try:
            db.execute(select(1))
            components.append(
                StatusComponent(name="database", ok=True, detail="queries responding")
            )
        except Exception:
            components.append(StatusComponent(name="database", ok=False, detail="unreachable"))
        try:
            cache_ok = app.state.cache.ping()
        except Exception:
            cache_ok = False
        components.append(
            StatusComponent(
                name="cache",
                ok=cache_ok,
                detail="shared cache reachable" if cache_ok else "cache unreachable",
            )
        )
        assistant_ok = provider is not None
        components.append(
            StatusComponent(
                name="assistant",
                ok=assistant_ok,
                detail="provider configured" if assistant_ok else "no LLM provider configured",
            )
        )
        healthy = all(c.ok for c in components)
        return StatusOut(
            status="ok" if healthy else "degraded",
            components=components,
            checked_at=datetime.now(UTC),
        )

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
            phone = payload.phone.strip() if payload.phone and payload.phone.strip() else None
            profile = Parent(
                name=payload.name.strip(),
                user_id=user.id,
                # S5.6: guardian phone encrypted at rest when PII_ENC_KEY is set.
                phone_enc=encrypt_pii(phone, settings.pii_enc_key),
            )
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
    async def ask(payload: AskRequest, db: DbSession, user: CurrentUser) -> AskResponse:
        if tutor is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
            )
        try:
            explain_instruction = (
                quiz_explain_instruction(payload.explain) if payload.explain else None
            )
            # S1.7: retrieve on the quiz topic itself — the generic
            # 'explain this' phrasing carries no subject keywords. S4.5: the
            # phrasing is dropped from the RETRIEVE/gate query entirely (it
            # diluted coverage below the grounding gate); it stays in the
            # prompt so the model still sees the student's own words.
            question = payload.question
            search_query: str | None = None
            if payload.explain:
                question = f"{payload.question}\n{payload.explain.question}"
                search_query = payload.explain.question
            # S4.1: every AI call carries the central education context.
            ctx = _request_context(
                db,
                user,
                class_level=payload.class_level,
                subject=canonical_subject(payload.subject),
                chapter=payload.chapter,
                goal="quiz_explain" if payload.explain else "question",
            )
            return await tutor.ask(
                question,
                payload.class_level,
                canonical_subject(payload.subject),
                chapter=payload.chapter,
                extra_instruction=explain_instruction,
                low_data=payload.low_data,
                context=ctx,
                search_query=search_query,
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

    def _request_context(
        db: Session,
        user: User,
        *,
        class_level: int,
        subject: str | None = None,
        chapter: str | None = None,
        goal: str = "question",
        history: list | None = None,
        strategy: str | None = None,
    ) -> RequestContext:
        """S4.1: the ONE construction point of the education context that
        accompanies every AI call (tutor ask/stream + the three generators).

        Also logs it (event ``ai_request_context``) for eval/cost attribution:
        log_fields carries counts and ids only -- never message content (R11).
        """
        mastery: dict[str, float] = {}
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is not None:
            rows = db.execute(
                select(AnswerLog.chapter, AnswerLog.is_correct)
                .join(QuizAttempt, AnswerLog.attempt_id == QuizAttempt.id)
                .where(QuizAttempt.student_id == student.id)
            ).all()
            stats: dict[str, tuple[int, int]] = {}
            for chapter_name, is_ok in rows:
                asked, correct = stats.get(chapter_name, (0, 0))
                stats[chapter_name] = (asked + 1, correct + (1 if is_ok else 0))
            mastery = snapshot_mastery(
                {c: atrisk.cell_accuracy(asked, correct) for c, (asked, correct) in stats.items()}
            )
        ctx = RequestContext(
            role=user.role,
            class_level=class_level,
            subject=subject,
            chapter_id=chapter,
            goal=goal,
            history_summary=history_summary(len(history or []), strategy),
            mastery_snapshot=mastery,
        )
        json_log(logger, logging.INFO, "ai_request_context", **ctx.log_fields())
        return ctx

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
            id=conv.id,
            title=conv.title,
            last_strategy=conv.last_strategy,
            created_at=conv.created_at,
            message_count=0,
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
        # S5.5: one grouped COUNT for the whole page (was 1+N per conversation).
        counts = {
            int(cid): int(n)
            for cid, n in db.execute(
                select(ChatMessage.conversation_id, func.count())
                .where(ChatMessage.conversation_id.in_([c.id for c in rows]))
                .group_by(ChatMessage.conversation_id)
            )
        }
        out: list[ConversationOut] = []
        for conv in rows:
            out.append(
                ConversationOut(
                    id=conv.id,
                    title=conv.title,
                    last_strategy=conv.last_strategy,
                    created_at=conv.created_at,
                    message_count=counts.get(conv.id, 0),
                )
            )
        return out

    @app.get("/tutor/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
    def conversation_messages(
        conversation_id: int,
        db: DbSession,
        user: CurrentUser,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[ChatMessageOut]:
        _own_conversation(db, conversation_id, user)
        # S5.5: cap the payload (was unbounded -- one row per message ever).
        # Newest N are fetched but returned chronological, so existing clients
        # see the same ordering.
        newest = (
            select(ChatMessage.id)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .subquery()
        )
        rows = (
            db.execute(
                select(ChatMessage)
                .where(ChatMessage.id.in_(select(newest.c.id)))
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

    # ------------------------------------------------------------------
    # S1.8: history search + conversation rename/delete
    # ------------------------------------------------------------------

    @app.patch("/tutor/conversations/{conversation_id}", response_model=ConversationOut)
    def rename_conversation(
        conversation_id: int,
        payload: ConversationUpdate,
        db: DbSession,
        user: CurrentUser,
    ) -> ConversationOut:
        conv = _own_conversation(db, conversation_id, user)
        new_title = payload.title.strip()
        if new_title:
            conv.title = new_title
        db.commit()
        count = db.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.conversation_id == conv.id)
        ).scalar_one()
        return ConversationOut(
            id=conv.id,
            title=conv.title,
            last_strategy=conv.last_strategy,
            created_at=conv.created_at,
            message_count=count,
        )

    @app.delete("/tutor/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: int, db: DbSession, user: CurrentUser) -> None:
        conv = _own_conversation(db, conversation_id, user)
        db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conv.id))
        db.delete(conv)
        db.commit()

    @app.get("/tutor/messages/search", response_model=list[MessageSearchHit])
    def search_messages(
        q: Annotated[str, Query(min_length=2, max_length=100)],
        db: DbSession,
        user: CurrentUser,
    ) -> list[MessageSearchHit]:
        student = _student_profile(db, user)
        conv_ids = select(Conversation.id).where(Conversation.student_id == student.id)
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = db.execute(
            select(ChatMessage, Conversation)
            .join(Conversation, ChatMessage.conversation_id == Conversation.id)
            .where(ChatMessage.conversation_id.in_(conv_ids))
            .where(ChatMessage.content.ilike(f"%{escaped}%", escape="\\"))
            .order_by(ChatMessage.id.desc())
            .limit(25)
        ).all()
        hits: list[MessageSearchHit] = []
        for msg, conv in rows:
            text = msg.content
            pos = text.lower().find(q.lower())
            start = max(0, pos - 40) if pos >= 0 else 0
            snippet = text[start : start + 160]
            hits.append(
                MessageSearchHit(
                    conversation_id=conv.id,
                    conversation_title=conv.title,
                    message_id=msg.id,
                    role=msg.role,
                    snippet=snippet,
                    created_at=msg.created_at,
                )
            )
        return hits

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

        # S1.5 'আমি বুঝিন': swap to the next explanation strategy and remember it.
        reteach_instruction: str | None = None
        if payload.reteach:
            strategy_key, reteach_instruction = teach.reteach_instruction(conv.last_strategy)
            conv.last_strategy = strategy_key

        user_msg = ChatMessage(conversation_id=conv.id, role="user", content=payload.message)
        db.add(user_msg)
        # Flush (not commit): the user turn must not survive a failed LLM call,
        # otherwise the provider error leaves an orphan message behind.
        db.flush()

        try:
            result = await tutor.ask(
                payload.message,
                class_level,
                canonical_subject(payload.subject),
                history,
                chapter=payload.chapter,
                extra_instruction=reteach_instruction,
                low_data=payload.low_data,
                context=_request_context(
                    db,
                    user,
                    class_level=class_level,
                    subject=canonical_subject(payload.subject),
                    chapter=payload.chapter,
                    goal="reteach" if payload.reteach else "chat",
                    history=history,
                    strategy=conv.last_strategy,
                ),
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
        # S1.9: one question ≈ one minute of study for the daily counters.
        record_activity(db, conv.student_id, questions=1, minutes=1)
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

        # S1.5 'আমি বুঝিন': swap to the next explanation strategy and remember it.
        reteach_instruction: str | None = None
        if payload.reteach:
            strategy_key, reteach_instruction = teach.reteach_instruction(conv.last_strategy)
            conv.last_strategy = strategy_key

        user_msg = ChatMessage(conversation_id=conv.id, role="user", content=payload.message)
        db.add(user_msg)
        # Flush (not commit): committed only together with the assistant reply,
        # so a provider failure mid-stream cannot leave an orphan user turn.
        db.flush()
        # S4.1: build the context before streaming so the log line lands once.
        ctx = _request_context(
            db,
            user,
            class_level=class_level,
            subject=canonical_subject(payload.subject),
            chapter=payload.chapter,
            goal="reteach" if payload.reteach else "chat",
            history=history,
            strategy=conv.last_strategy,
        )

        async def event_stream() -> AsyncIterator[str]:
            try:
                final_response: AskResponse | None = None
                async for event in tutor.ask_stream(  # type: ignore[union-attr]
                    payload.message,
                    class_level,
                    canonical_subject(payload.subject),
                    history,
                    chapter=payload.chapter,
                    extra_instruction=reteach_instruction,
                    low_data=payload.low_data,
                    context=ctx,
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
                record_activity(db, conv.student_id, questions=1, minutes=1)
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

    @app.get("/admin/feedback", response_model=FeedbackQueuePage)
    def admin_feedback_queue(
        db: DbSession,
        admin: AdminUser,
        status: str = Query(default="open", pattern="^(open|all)$"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> FeedbackQueuePage:
        """S5.10 triage queue: oldest un-triaged feedback first. Rows carry
        the complaint and nothing more -- reporter identity beyond the id is
        deliberately withheld (R11)."""
        stmt = select(Feedback, User.role).join(User, User.id == Feedback.user_id)
        count_stmt = select(func.count()).select_from(Feedback)
        if status == "open":
            stmt = stmt.where(Feedback.triaged.is_(False))
            count_stmt = count_stmt.where(Feedback.triaged.is_(False))
        total = db.execute(count_stmt).scalar_one()
        open_count = db.execute(
            select(func.count()).select_from(Feedback).where(Feedback.triaged.is_(False))
        ).scalar_one()
        rows = db.execute(stmt.order_by(Feedback.id.asc()).limit(limit).offset(offset)).all()
        return FeedbackQueuePage(
            rows=[
                FeedbackAdminRow(
                    id=fb.id,
                    user_id=fb.user_id,
                    role=role,
                    rating=fb.rating,
                    comment=fb.comment,
                    message_id=fb.message_id,
                    attempt_id=fb.attempt_id,
                    triaged=fb.triaged,
                    triaged_at=fb.triaged_at,
                    note=fb.triage_note,
                    created_at=fb.created_at,
                )
                for fb, role in rows
            ],
            total=total,
            open_count=open_count,
            limit=limit,
            offset=offset,
        )

    @app.patch("/admin/feedback/{feedback_id}", response_model=FeedbackAdminRow)
    def admin_feedback_triage(
        feedback_id: int, payload: TriageUpdate, db: DbSession, admin: AdminUser
    ) -> FeedbackAdminRow:
        """Mark a queue item triaged/un-triaged with an optional internal
        note. The note is admin-authored and never returned to end users."""
        fb = db.get(Feedback, feedback_id)
        if fb is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "feedback_not_found", "message": "Feedback not found"},
            )
        fb.triaged = payload.triaged
        fb.triaged_at = datetime.now(UTC).replace(tzinfo=None) if payload.triaged else None
        if payload.note is not None:
            fb.triage_note = payload.note
        db.commit()
        role = db.execute(select(User.role).where(User.id == fb.user_id)).scalar_one()
        return FeedbackAdminRow(
            id=fb.id,
            user_id=fb.user_id,
            role=role,
            rating=fb.rating,
            comment=fb.comment,
            message_id=fb.message_id,
            attempt_id=fb.attempt_id,
            triaged=fb.triaged,
            triaged_at=fb.triaged_at,
            note=fb.triage_note,
            created_at=fb.created_at,
        )

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

        Removes the account and every row owned by it: student/teacher/parent
        profile and ALL FK-children (Postgres enforces referential integrity --
        SQLite silently does not, so every child table must be cleaned here or
        the delete aborts mid-transaction on the production engine). The last
        remaining admin cannot delete their own account (409).
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
            # Redeemed invites keep their history; only the pointer to the
            # erased parent is dropped (nullable FK).
            db.execute(
                update(ParentInvite)
                .where(ParentInvite.used_by_parent_id == parent.id)
                .values(used_by_parent_id=None)
            )
            db.delete(parent)
        if teacher is not None:
            db.execute(delete(ClassTeacher).where(ClassTeacher.teacher_id == teacher.id))
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
            db.execute(delete(QuizAttempt).where(QuizAttempt.student_id == student.id))
            db.execute(delete(ParentStudentLink).where(ParentStudentLink.student_id == student.id))
            db.execute(delete(ParentInvite).where(ParentInvite.student_id == student.id))
            # S1.2/S1.9/S1.10 + S2/S4 children added after the original flow:
            # skipping any of these breaks deletion under Postgres (BUG-4).
            db.execute(delete(ChapterProgress).where(ChapterProgress.student_id == student.id))
            db.execute(delete(DailyActivity).where(DailyActivity.student_id == student.id))
            db.execute(delete(RevisionItem).where(RevisionItem.student_id == student.id))
            db.execute(delete(ClassStudent).where(ClassStudent.student_id == student.id))
            db.execute(delete(StudentInvite).where(StudentInvite.student_id == student.id))
            db.execute(delete(SupportPlan).where(SupportPlan.student_id == student.id))
            db.execute(delete(ConceptMastery).where(ConceptMastery.student_id == student.id))
            db.execute(delete(StudentAbility).where(StudentAbility.student_id == student.id))
            db.delete(student)

        # User-scoped rows (any role), removed before the users row itself.
        db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
        db.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
        db.execute(delete(Feedback).where(Feedback.user_id == user.id))
        db.execute(delete(QuestionPaper).where(QuestionPaper.teacher_id == user.id))
        db.execute(delete(ShortTest).where(ShortTest.teacher_id == user.id))
        db.execute(delete(Assignment).where(Assignment.teacher_id == user.id))
        db.execute(delete(QuestionBankEntry).where(QuestionBankEntry.teacher_id == user.id))
        db.execute(delete(SupportPlan).where(SupportPlan.teacher_id == user.id))
        # Invites this account created go with it (redeemed staff links are
        # kept as evidence in the User row itself); redemption pointers to this
        # account are nulled.
        db.execute(delete(SchoolInvite).where(SchoolInvite.created_by == user.id))
        db.execute(update(SchoolInvite).where(SchoolInvite.used_by == user.id).values(used_by=None))
        # Shared artifacts survive their author, losing only the author pointer:
        db.execute(
            update(ChapterContent)
            .where(ChapterContent.created_by == user.id)
            .values(created_by=None)
        )
        # Audit rows are append-only and never deleted: the event survives the
        # account, only the attribution to an erased account is anonymised
        # (actor_user_id is nullable by design for exactly this erasure case).
        db.execute(
            update(AuditLog).where(AuditLog.actor_user_id == user.id).values(actor_user_id=None)
        )

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
        # S5.6 audit event 2/5: data_export (self-service; only the fact is
        # logged -- the payload itself never touches logs or audit rows).
        write_audit(
            db,
            action="data_export",
            actor_user_id=user.id,
            actor_role=user.role,
            target=f"user:{user.id}",
            detail={"format": "json"},
        )
        db.commit()
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

    @app.get("/students/{student_id}/consent", response_model=ConsentStatusOut)
    def get_consent_status(student_id: int, db: DbSession, user: CurrentUser) -> ConsentStatusOut:
        """S5.8: is the stored guardian consent current for this student?"""
        student = authorize_student_access(db, student_id, user)
        return ConsentStatusOut(
            student_id=student.id,
            current_version=CONSENT_VERSION,
            accepted_version=student.consent_version,
            accepted_at=student.consent_at,
            needs_reconfirm=student.consent_version != CONSENT_VERSION,
        )

    @app.post("/students/{student_id}/consent/reconfirm", response_model=ConsentStatusOut)
    def post_consent_reconfirm(
        student_id: int,
        payload: ConsentReconfirmIn,
        request: Request,
        db: DbSession,
        user: CurrentUser,
    ) -> ConsentStatusOut:
        """S5.8 re-confirm flow: student or linked guardian accepts the
        CURRENT consent text; evidence trail (at/ip/version) is refreshed."""
        if not payload.accepted:
            raise HTTPException(
                status_code=400,
                detail={"code": "consent_not_accepted", "message": "acceptance required"},
            )
        student = authorize_student_access(db, student_id, user)
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
        # S4.5: generate a wider pool, then hand the student the questions
        # whose rated difficulty sits nearest ability + 0.5 sigma.
        pool = generator.generate(
            class_level=class_level,
            subject=canonical_subject(payload.subject),
            chapter=payload.chapter,
            num=min(payload.num_questions * adaptive.POOL_MULTIPLIER, adaptive.POOL_CAP),
            seed=attempt.id,
        )
        questions = adaptive.pick_questions(
            db,
            pool,
            student_id=student.id,
            subject=canonical_subject(payload.subject),
            class_level=class_level,
            num=payload.num_questions,
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
            # S4.5: open KG gaps arrive as re-teach cards BEFORE the next Q.
            reteach=[
                ReteachCardOut(**card)
                for card in adaptive.open_reteach_cards(db, index.chunks, student.id)
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
        record_activity(db, attempt.student_id, quizzes=1, minutes=1)
        # S1.10: quiz outcomes seed/refresh the spaced-revision queue.
        revision.record_quiz_result(
            db, attempt.student_id, review, attempt.subject, attempt.class_level
        )
        # S4.4: the same graded answers update per-concept mastery in the
        # knowledge graph (chapter roots seeded lazily from the curriculum).
        reteach_cards: list[ReteachCardOut] = []
        if index is not None:
            knowledge.ensure_concepts(db, index.chunks)
            knowledge.record_quiz_result(db, attempt.student_id, review, attempt.class_level)
            # S4.5: Elo ratings follow the graded answers; every wrong answer
            # runs the KG gap check, and surfaced gaps become re-teach cards.
            adaptive.apply_review(
                db,
                student_id=attempt.student_id,
                class_level=attempt.class_level,
                graded=[
                    (str(question["id"]), question["chapter"], item.is_correct)
                    for question, item in zip(questions, review, strict=True)
                ],
            )
            reteach_cards = [
                ReteachCardOut(**card)
                for card in adaptive.wrong_answer_reteach_cards(
                    db,
                    index.chunks,
                    attempt.student_id,
                    [
                        question["chapter"]
                        for question, item in zip(questions, review, strict=True)
                        if not item.is_correct
                    ],
                )
            ]

        return QuizResult(
            attempt_id=attempt.id,
            score_pct=attempt.score_pct,
            correct=correct,
            total=total,
            review=review,
            reteach=reteach_cards,
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
        weak_chapters = weakness.weak_names(db, student.id)
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

    @app.get("/students/{student_id}/activity", response_model=ActivitySummary)
    def get_activity(
        student_id: int,
        db: DbSession,
        user: CurrentUser,
        days: Annotated[int, Query(ge=7, le=370)] = 91,
    ) -> ActivitySummary:
        """S1.9: streak + GitHub-style daily heatmap (Asia/Dhaka days)."""
        authorize_student_access(db, student_id, user)
        today = dhaka_date(datetime.now(UTC))
        rows = (
            db.execute(
                select(DailyActivity)
                .where(DailyActivity.student_id == student_id)
                .order_by(DailyActivity.date)
            )
            .scalars()
            .all()
        )
        window = heatmap_days(list(rows), today, days)
        date_axis = [
            (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).date().isoformat()
            for i in range(days - 1, -1, -1)
        ]
        active = {r.date for r in rows if (r.questions or r.quizzes or r.minutes)}
        return ActivitySummary(
            streak=streak_days(active, today),
            today=today,
            days=[ActivityDay(date=d, **c) for d, c in zip(date_axis, window, strict=True)],
        )

    # ------------------------------------------------------------------
    # S1.10: spaced revision queue (SM-2-lite)
    # ------------------------------------------------------------------

    def _revision_out(row: RevisionItem) -> RevisionItemOut:
        return RevisionItemOut(
            id=row.id,
            question=row.question,
            options=list(row.options_json or []),
            correct_index=row.correct_index,
            chapter=row.chapter,
            reps=row.reps,
            interval_days=row.interval_days,
            ease_factor=row.ease_factor,
            due_date=row.due_date,
        )

    @app.get("/revision/due", response_model=RevisionDueOut)
    def get_revision_due(
        db: DbSession, user: CurrentUser, limit: Annotated[int, Query(ge=1, le=50)] = 20
    ) -> RevisionDueOut:
        student = _student_profile(db, user)
        today = dhaka_date(datetime.now(UTC))
        rows = revision.due_items(db, student.id, today, limit=limit)
        return RevisionDueOut(
            today=today,
            due_count=revision.due_count(db, student.id, today),
            items=[_revision_out(r) for r in rows],
        )

    @app.post("/revision/{item_id}/review", response_model=RevisionItemOut)
    def review_revision_item(
        item_id: int, payload: RevisionReviewIn, db: DbSession, user: CurrentUser
    ) -> RevisionItemOut:
        student = _student_profile(db, user)
        row = db.get(RevisionItem, item_id)
        if row is None or row.student_id != student.id:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "Revision item not found"},
            )
        quality = 5 if payload.chosen == row.correct_index else 1
        reps, interval, ease = revision.next_schedule(
            row.reps, row.interval_days, row.ease_factor, quality
        )
        row.reps, row.interval_days, row.ease_factor = reps, interval, ease
        today = dhaka_date(datetime.now(UTC))
        row.due_date = today if quality < 3 else revision.add_days(today, interval)
        db.commit()
        db.refresh(row)
        return _revision_out(row)

    # ------------------------------------------------------------------
    # S4.4: knowledge graph — concept gaps from mastery + prerequisites
    # ------------------------------------------------------------------

    @app.get("/kg/gaps", response_model=KgGapsOut)
    def kg_gaps(db: DbSession, user: CurrentUser) -> KgGapsOut:
        """Weak-concept gaps: missing/weak prerequisites of concepts this
        student has practiced (transitive, depth-ordered)."""
        student = _student_profile(db, user)
        if index is not None:
            knowledge.ensure_concepts(db, index.chunks)
        gaps = knowledge.student_gaps(db, student.id)
        return KgGapsOut(
            weak_threshold_pct=knowledge.WEAK_THRESHOLD_PCT,
            min_attempts=knowledge.MIN_ATTEMPTS,
            gaps=[
                KgGapOut(
                    concept=g.concept,
                    prereq=g.prereq,
                    prereq_pct=g.prereq_pct,
                    prereq_total=g.prereq_total,
                    depth=g.depth,
                )
                for g in gaps
            ],
        )

    @app.post("/kg/rebuild", response_model=KgRebuildOut)
    async def kg_rebuild(
        db: DbSession,
        user: AdminUser,
        llm: Annotated[bool, Query()] = False,
    ) -> KgRebuildOut:
        """Admin: rebuild chapter-root concepts + curated prerequisite edges.
        With llm=true, also attempt corpus-verified LLM concept extraction."""
        if index is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
            )
        active_provider = provider
        if llm and active_provider is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "provider_unavailable", "message": "LLM provider not configured"},
            )
        stats = await knowledge.rebuild_concepts(db, index.chunks, active_provider, llm=llm)
        return KgRebuildOut(**stats)

    # ------------------------------------------------------------------
    # S1.11: global search over subjects + chapters + questions (BM25)
    # ------------------------------------------------------------------

    @app.get("/search", response_model=SearchResponse)
    def global_search(
        user: CurrentUser,
        q: Annotated[str, Query(min_length=1, max_length=100)],
    ) -> SearchResponse:
        """S1.11: one search box for the whole curriculum.

        Question-like queries set ``ask_action`` so the UI can offer the
        ask-in-Tutor action; chapter and question-section hits are deduped
        per chapter (the question hit is the more specific pointer).
        """
        if index is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
            )
        query = q.strip()
        if not query:
            raise HTTPException(
                status_code=422,
                detail={"code": "empty_query", "message": "Query must not be blank"},
            )
        ask = _is_question_like(query)
        hits = index.search(query, top_k=24, min_score=0.5)

        out: list[SearchHit] = []
        # Subject entries match the slug or the Bangla book title directly.
        norm = query.casefold()
        subjects_seen: set[str] = set()
        for chunk in index.chunks:
            slug = chunk.meta.subject
            if slug in subjects_seen:
                continue
            book = chunk.meta.book or slug
            if norm == slug.casefold() or norm in slug or norm in book.casefold():
                subjects_seen.add(slug)
                out.append(
                    SearchHit(
                        kind="subject",
                        title=book,
                        subtitle=slug,
                        href="/student/learn",
                        score=1000.0,
                    )
                )
            if len(subjects_seen) >= 3:
                break

        def chapter_href(subject: str, chapter: str, class_level: int) -> str:
            return f"/student/learn/{quote(subject)}/{quote(chapter)}?class={class_level}"

        chapters: dict[tuple[str, str, int], SearchHit] = {}
        questions: dict[tuple[str, str, int, str], SearchHit] = {}
        for hit in hits:
            meta = hit.chunk.meta
            href = chapter_href(meta.subject, meta.chapter, meta.class_level)
            section = meta.section or ""
            qkey = (meta.subject, meta.chapter, meta.class_level, section)
            if section and _is_question_like(section) and qkey not in questions:
                questions[qkey] = SearchHit(
                    kind="question",
                    title=section,
                    subtitle=f"{meta.chapter} \u00b7 {meta.book or meta.subject}",
                    href=href,
                    score=hit.score,
                )
            ckey = (meta.subject, meta.chapter, meta.class_level)
            if ckey not in chapters:
                chapters[ckey] = SearchHit(
                    kind="chapter",
                    title=meta.chapter,
                    subtitle=meta.book or meta.subject,
                    href=href,
                    score=hit.score,
                )
        question_chapters = {(s, c, cl) for (s, c, cl, _sec) in questions}
        merged = sorted(
            list(questions.values())
            + [hit for key, hit in chapters.items() if key not in question_chapters],
            key=lambda h: h.score,
            reverse=True,
        )
        out.extend(merged[:10])
        return SearchResponse(query=query, ask_action=ask, hits=out)

    @app.get("/dashboard/summary", response_model=DashboardSummary)
    def dashboard_summary(request: Request, db: DbSession, user: CurrentUser) -> DashboardSummary:
        """S5.3: per-user 60s cache over the S1.1 summary (shared Redis cache
        when RATE_LIMIT_BACKEND=redis + REDIS_URL, memory cache otherwise)."""
        today = datetime.now(UTC).date().isoformat()
        summary_cache = request.app.state.cache
        key = f"summary:{user.id}:{today}"
        cached = summary_cache.get_json(key)
        if cached is not None:
            try:
                cached_summary = DashboardSummary(**cached)
            except (TypeError, ValueError):  # stale shape -> recompute below
                pass
            else:
                caching.CACHE_EVENTS_TOTAL.labels(cache="summary", result="hit").inc()
                return cached_summary
        caching.CACHE_EVENTS_TOTAL.labels(cache="summary", result="miss").inc()
        summary = _build_dashboard_summary(db, user, today)
        summary_cache.set_json(
            key, summary.model_dump(mode="json"), caching.SUMMARY_CACHE_TTL_SECONDS
        )
        return summary

    def _build_dashboard_summary(db: Session, user: User, today: str) -> DashboardSummary:
        me = _build_me_response(db, user)
        quick_actions = [
            QuickAction(label="পাঠ্যবই পড়ুন", to="/student/learn", icon="book"),
            QuickAction(label="AI-কে প্রশ্ন করুন", to="/student/tutor", icon="zap"),
            QuickAction(label="কুইজ দিন", to="/student/quiz", icon="graduation"),
        ]
        if user.role != "student":
            return DashboardSummary(
                user=me,
                today=today,
                continue_learning=None,
                quick_actions=quick_actions,
                recommendation=None,
                progress=None,
            )
        # Student progress (reuse logic minimally)
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is None:
            return DashboardSummary(
                user=me,
                today=today,
                quick_actions=quick_actions,
                recommendation=None,
                progress=None,
            )
        # Compute progress
        attempts = (
            db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student.id))
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
            for r in rows:
                stats[r.chapter][0] += 1
                stats[r.chapter][1] += r.is_correct
        by_chapter = sorted(
            (
                ChapterStat(
                    chapter=k, asked=v[0], correct=v[1], accuracy=round(100.0 * v[1] / v[0], 2)
                )
                for k, v in stats.items()
            ),
            key=lambda s: s.accuracy,
        )
        weak = weakness.weak_names(db, student.id)
        avg_score = (
            round(sum(a.score_pct for a in graded if a.score_pct is not None) / len(graded), 2)
            if graded
            else None
        )
        progress = StudentProgress(
            student=StudentResponse(
                id=student.id, name=student.name, class_level=student.class_level
            ),
            attempts_graded=len(graded),
            avg_score_pct=avg_score,
            by_chapter=by_chapter,
            weak_chapters=weak,
        )
        # Continue: last graded attempt's first question chapter
        continue_learning = None
        if graded:
            last = sorted(graded, key=lambda a: a.created_at or datetime.min, reverse=True)[0]
            if last.quiz_json:
                first = (
                    last.quiz_json[0]
                    if isinstance(last.quiz_json, list) and last.quiz_json
                    else None
                )
                if first and isinstance(first, dict) and first.get("chapter"):
                    continue_learning = ContinueLearning(
                        subject=last.subject,
                        chapter=first["chapter"],
                        class_level=last.class_level,
                        excerpt=first.get("question_text", "")[:120],
                    )
        # Recommendation: weak first, else general
        recommendation = None
        if weak:
            # Find subject for weak chapter via last attempt or default science
            subj = None
            for a in graded:
                if a.quiz_json and any(
                    q.get("chapter") == weak[0] for q in a.quiz_json if isinstance(q, dict)
                ):
                    subj = a.subject
                    break
            recommendation = Recommendation(
                type="weak_quiz", subject=subj or "science", chapter=weak[0], reason="দুর্বল অধ্যায়"
            )
        elif graded:
            recommendation = Recommendation(type="general", reason="নতুন কুইজ চেষ্টা করুন")
        return DashboardSummary(
            user=me,
            today=today,
            continue_learning=continue_learning,
            quick_actions=quick_actions,
            recommendation=recommendation,
            progress=progress,
        )

    @app.get("/learn/progress", response_model=list[ChapterProgressOut])
    def get_learn_progress(
        db: DbSession, user: CurrentUser, subject: str | None = None, class_level: int | None = None
    ) -> list[ChapterProgressOut]:
        """S1.2: List chapter progress for current student."""
        if user.role != "student":
            return []
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is None:
            return []
        q = select(ChapterProgress).where(ChapterProgress.student_id == student.id)
        if subject:
            q = q.where(ChapterProgress.subject == subject)
        if class_level:
            q = q.where(ChapterProgress.class_level == class_level)
        rows = db.execute(q.order_by(ChapterProgress.updated_at.desc())).scalars().all()
        return [
            ChapterProgressOut(
                subject=r.subject,
                chapter=r.chapter,
                class_level=r.class_level,
                read_pct=r.read_pct,
                completed=r.completed,
                bookmarked=r.bookmarked,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    @app.post("/learn/progress", response_model=ChapterProgressOut)
    def upsert_learn_progress(
        payload: ChapterProgressIn, db: DbSession, user: CurrentUser
    ) -> ChapterProgressOut:
        """S1.2: Upsert progress/bookmark for a chapter."""
        if user.role != "student":
            raise HTTPException(status_code=403, detail="Only students")
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        # Import here to avoid circular
        from bangla_gpt_api.db.models import ChapterProgress

        row = db.execute(
            select(ChapterProgress).where(
                ChapterProgress.student_id == student.id,
                ChapterProgress.subject == payload.subject,
                ChapterProgress.chapter == payload.chapter,
                ChapterProgress.class_level == payload.class_level,
            )
        ).scalar_one_or_none()
        if row is None:
            row = ChapterProgress(
                student_id=student.id,
                subject=payload.subject,
                chapter=payload.chapter,
                class_level=payload.class_level,
                read_pct=payload.read_pct or 0,
                completed=payload.completed or False,
                bookmarked=payload.bookmarked or False,
            )
            db.add(row)
        else:
            if payload.read_pct is not None:
                row.read_pct = payload.read_pct
            if payload.completed is not None:
                row.completed = payload.completed
            if payload.bookmarked is not None:
                row.bookmarked = payload.bookmarked
            row.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
        return ChapterProgressOut(
            subject=row.subject,
            chapter=row.chapter,
            class_level=row.class_level,
            read_pct=row.read_pct,
            completed=row.completed,
            bookmarked=row.bookmarked,
            updated_at=row.updated_at,
        )

    def _load_class_students(
        db: Session, class_level: int | None, limit: int | None = None
    ) -> list[Student]:
        statement = select(Student).order_by(Student.id)
        if class_level is not None:
            statement = statement.where(Student.class_level == class_level)
        if limit is not None:
            statement = statement.limit(limit)
        return list(db.execute(statement).scalars().all())

    def _student_briefs(db: Session, students: list[Student]) -> list[StudentBrief]:
        # S5.5: one grouped aggregate for the whole roster (was 1 query per
        # student, each pulling every attempt row as a full ORM object).
        # avg() ignores NULL score_pct, matching the previous Python average.
        stats: dict[int, tuple[int, float | None]] = {}
        ids = [s.id for s in students]
        for i in range(0, len(ids), 500):  # chunked: safe under SQLITE_MAX_VARIABLES
            chunk = ids[i : i + 500]
            for sid, n, avg in db.execute(
                select(QuizAttempt.student_id, func.count(), func.avg(QuizAttempt.score_pct))
                .where(
                    QuizAttempt.student_id.in_(chunk),
                    QuizAttempt.status == "graded",
                )
                .group_by(QuizAttempt.student_id)
            ):
                stats[sid] = (n, float(avg) if avg is not None else None)
        briefs: list[StudentBrief] = []
        for student in students:
            n, avg = stats.get(student.id, (0, None))
            briefs.append(
                StudentBrief(
                    student_id=student.id,
                    name=student.name,
                    class_level=student.class_level,
                    attempts_graded=n,
                    avg_score_pct=round(avg, 2) if avg is not None else None,
                )
            )
        return briefs

    @app.get("/teacher/students", response_model=list[StudentBrief])
    def teacher_roster(
        db: DbSession,
        teacher: TeacherOrAdminUser,
        class_level: int | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> list[StudentBrief]:
        # S5.5: capped (class_level omitted used to pull the whole student table).
        students = _load_class_students(db, class_level, limit=limit)
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

    # --- S2.2: classroom management + CSV bulk import -------------------------

    DEFAULT_SCHOOL_CODE = "BGPT-DEFAULT"
    IMPORT_CODE_TTL_DAYS = 30
    IMPORT_MAX_ROWS = 200

    def _default_school(db: Session) -> School:
        school = db.execute(
            select(School).where(School.code == DEFAULT_SCHOOL_CODE)
        ).scalar_one_or_none()
        if school is None:
            school = School(name="Default School", code=DEFAULT_SCHOOL_CODE)
            db.add(school)
            try:
                db.flush()
            except IntegrityError:  # concurrent creation
                db.rollback()
                school = db.execute(
                    select(School).where(School.code == DEFAULT_SCHOOL_CODE)
                ).scalar_one()
        return school

    def _classroom_or_404(db: Session, room_id: int) -> ClassRoom:
        room = db.get(ClassRoom, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="classroom not found")
        return room

    def _room_counts(db: Session) -> dict[int, int]:
        rows = cast(
            CursorResult[Any],
            db.execute(
                select(ClassStudent.classroom_id, func.count()).group_by(ClassStudent.classroom_id)
            ),
        )
        return {int(row[0]): int(row[1]) for row in rows.all()}

    @app.get("/teacher/classrooms", response_model=list[ClassRoomOut])
    def teacher_list_classrooms(db: DbSession, teacher: TeacherOrAdminUser) -> list[ClassRoomOut]:
        """S2.2: all classrooms with enrollment counts (school scoping arrives in S3.1)."""
        rooms = (
            db.execute(select(ClassRoom).order_by(ClassRoom.class_level, ClassRoom.section))
            .scalars()
            .all()
        )
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

    @app.post("/teacher/classrooms", response_model=ClassRoomOut, status_code=201)
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

    @app.get("/teacher/classrooms/{room_id}/roster", response_model=list[RosterEntryOut])
    def classroom_roster(
        room_id: int, db: DbSession, teacher: TeacherOrAdminUser
    ) -> list[RosterEntryOut]:
        room = _classroom_or_404(db, room_id)
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

    @app.post("/teacher/classrooms/{room_id}/import", response_model=ClassImportOut)
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
        room = _classroom_or_404(db, room_id)
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

    SCHOOL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O/0, I/1

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

    @app.post("/admin/schools", response_model=SchoolOut, status_code=201)
    def admin_school_create(payload: SchoolCreateIn, db: DbSession, admin: AdminUser) -> SchoolOut:
        name = payload.name.strip()
        school = School(name=name, code=_gen_school_code(db))
        db.add(school)
        db.commit()
        db.refresh(school)
        json_log(logger, logging.INFO, "school_created", school_id=school.id, code=school.code)
        return SchoolOut(
            id=school.id, name=school.name, code=school.code, created_at=school.created_at
        )

    @app.get("/admin/schools", response_model=list[SchoolOut])
    def admin_school_list(db: DbSession, admin: AdminUser) -> list[SchoolOut]:
        schools = db.execute(select(School).order_by(School.id)).scalars().all()
        return [
            SchoolOut(id=s.id, name=s.name, code=s.code, created_at=s.created_at) for s in schools
        ]

    @app.get("/admin/schools/stats", response_model=list[AdminSchoolStatsOut])
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

    @app.get("/admin/schools/{school_id}/invites", response_model=list[SchoolInviteAdminOut])
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

    @app.delete("/admin/schools/{school_id}/invites/{invite_id}", status_code=204)
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

    @app.get("/admin/content/versions", response_model=list[ContentVersionRowOut])
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
        creator_ids = {
            c.created_by for chain in by_key.values() for c in chain[-1:] if c.created_by
        }
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

    @app.get("/admin/reports/aggregate")
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
        export = govt_report.aggregate(
            db, district=district, since_days=since_days, min_cell=min_cell
        )
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
            raise HTTPException(
                status_code=500, detail="aggregate report failed the PII safety check"
            )
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

    @app.post("/schools/{school_id}/invites", response_model=SchoolInviteOut, status_code=201)
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
        json_log(
            logger, logging.INFO, "school_invite_created", school_id=school_id, role=invite.role
        )
        return SchoolInviteOut(
            id=invite.id,
            school_id=school_id,
            role=invite.role,
            code=code,
            created_at=invite.created_at,
        )

    @app.post("/auth/join-school", response_model=TokenResponse, status_code=201)
    def auth_join_school(payload: SchoolJoinIn, db: DbSession) -> TokenResponse:
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
            email_verified=not smtp_configured(settings),
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
        return TokenResponse(access_token=create_access_token(user, settings=settings))

    @app.get("/schools/mine", response_model=SchoolOverviewOut)
    def school_my_overview(db: DbSession, user: SchoolStaffUser) -> SchoolOverviewOut:
        """Own-school overview for staff; admin without a school sees the default."""
        school = db.get(School, user.school_id) if user.school_id else None
        if school is None:
            school = _default_school(db)
        rooms = (
            db.execute(select(ClassRoom).where(ClassRoom.school_id == school.id)).scalars().all()
        )
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

    @app.post("/schools/{school_id}/classes", response_model=ClassRoomOut, status_code=201)
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
        json_log(
            logger, logging.INFO, "school_class_registered", school_id=school_id, room_id=room.id
        )
        return ClassRoomOut(
            id=room.id, class_level=room.class_level, section=room.section, student_count=0
        )

    # ── S3.2: school dashboard (aggregate learning health, no per-message data) ──

    SCHOOL_STRONG_AVG = 70.0  # percent; at-risk rule comes from S2.7 (atrisk.py)

    @app.get("/school/overview", response_model=SchoolHealthOut)
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
        rooms = (
            db.execute(select(ClassRoom).where(ClassRoom.school_id == school.id)).scalars().all()
        )
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
                    s.id: s
                    for s in db.execute(select(Student).where(Student.id.in_(ids))).scalars()
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

    def _content_next_version(db: Session, subject: str, class_level: int, chapter: str) -> int:
        current = db.execute(
            select(func.max(ChapterContent.version)).where(
                ChapterContent.subject == subject,
                ChapterContent.class_level == class_level,
                ChapterContent.chapter == chapter,
            )
        ).scalar_one_or_none()
        return (current or 0) + 1

    def _content_current(
        db: Session, subject: str, class_level: int, chapter: str
    ) -> ChapterContent | None:
        return db.execute(
            select(ChapterContent)
            .where(
                ChapterContent.subject == subject,
                ChapterContent.class_level == class_level,
                ChapterContent.chapter == chapter,
            )
            .order_by(ChapterContent.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _content_out(
        row: ChapterContent, sources: list[SourceRef] | None = None
    ) -> TeacherContentOut:
        return TeacherContentOut(
            class_level=row.class_level,
            subject=row.subject,
            chapter=row.chapter,
            version=row.version,
            source=row.source,
            sections=ChapterSections.model_validate(row.payload),
            sources=sources or [],
        )

    @app.post("/teacher/content/generate", response_model=TeacherContentOut)
    async def teacher_content_generate(
        payload: ChapterContentKey, db: DbSession, teacher: TeacherOrAdminUser
    ) -> TeacherContentOut:
        """S2.3: one retrieval + one AI call fills all seven sections."""
        if tutor is None:
            raise HTTPException(status_code=503, detail="provider not configured")
        try:
            sections, sources = await generate_chapter_content(
                tutor.index,
                tutor.provider,
                class_level=payload.class_level,
                subject=payload.subject,
                chapter=payload.chapter,
                context=_request_context(
                    db,
                    teacher,
                    class_level=payload.class_level,
                    subject=payload.subject,
                    chapter=payload.chapter,
                    goal="chapter_content",
                ),
            )
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail="content generation failed") from exc
        version = _content_next_version(db, payload.subject, payload.class_level, payload.chapter)
        row = ChapterContent(
            subject=payload.subject,
            class_level=payload.class_level,
            chapter=payload.chapter,
            version=version,
            source="ai",
            payload=sections,
            created_by=teacher.id,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Concurrent generation for the same chapter: take the next slot.
            db.rollback()
            row.version = _content_next_version(
                db, payload.subject, payload.class_level, payload.chapter
            )
            db.add(row)
            db.commit()
        db.refresh(row)
        return _content_out(row, sources)

    @app.get("/teacher/content/history", response_model=list[ChapterContentVersionOut])
    def teacher_content_history(
        db: DbSession,
        teacher: TeacherOrAdminUser,
        class_level: int,
        subject: str,
        chapter: str,
    ) -> list[ChapterContentVersionOut]:
        rows = (
            db.execute(
                select(ChapterContent)
                .where(
                    ChapterContent.subject == subject,
                    ChapterContent.class_level == class_level,
                    ChapterContent.chapter == chapter,
                )
                .order_by(ChapterContent.version.desc())
            )
            .scalars()
            .all()
        )
        return [
            ChapterContentVersionOut(
                class_level=r.class_level,
                subject=r.subject,
                chapter=r.chapter,
                version=r.version,
                source=r.source,
                created_at=r.created_at,
                created_by=r.created_by,
            )
            for r in rows
        ]

    @app.get("/teacher/content", response_model=TeacherContentOut)
    def teacher_content_get(
        db: DbSession,
        teacher: TeacherOrAdminUser,
        class_level: int,
        subject: str,
        chapter: str,
    ) -> TeacherContentOut:
        row = _content_current(db, subject, class_level, chapter)
        if row is None:
            raise HTTPException(status_code=404, detail="content not found")
        return _content_out(row)

    @app.put("/teacher/content", response_model=TeacherContentOut)
    def teacher_content_edit(
        payload: ChapterContentEditIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> TeacherContentOut:
        """S2.3: teacher edits append a new version (append-only chain)."""
        if _content_current(db, payload.subject, payload.class_level, payload.chapter) is None:
            raise HTTPException(status_code=404, detail="content not found")
        row = ChapterContent(
            subject=payload.subject,
            class_level=payload.class_level,
            chapter=payload.chapter,
            version=_content_next_version(
                db, payload.subject, payload.class_level, payload.chapter
            ),
            source="teacher",
            payload=payload.sections.model_dump(),
            created_by=teacher.id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _content_out(row)

    # --- S2.4: question papers (AI draft -> teacher review -> FINAL) --------

    def _qp_or_404(db: Session, qp_id: int, teacher: User) -> QuestionPaper:
        qp = db.get(QuestionPaper, qp_id)
        if qp is None or (qp.teacher_id != teacher.id and teacher.role != "admin"):
            raise HTTPException(status_code=404, detail="question paper not found")
        return qp

    def _qp_out(qp: QuestionPaper) -> QPOut:
        return QPOut(
            id=qp.id,
            class_level=qp.class_level,
            subject=qp.subject,
            exam_type=qp.exam_type,
            marks=qp.marks,
            duration_min=qp.duration_min,
            difficulty=dict(qp.difficulty),
            chapters=list(qp.chapters),
            status=qp.status,
            questions=[QPQuestion.model_validate(q) for q in qp.questions],
            meta=dict(qp.meta or {}),
            reviewed_at=qp.reviewed_at,
            finalized_at=qp.finalized_at,
            created_at=qp.created_at,
        )

    async def _qp_fresh_draft(
        class_level: int,
        subject: str,
        chapters: list[str],
        marks: int,
        difficulty: dict[str, int],
        context: RequestContext | None = None,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        if tutor is None:
            raise HTTPException(status_code=503, detail="provider not configured")
        try:
            return await generate_question_paper(
                tutor.index,
                tutor.provider,
                class_level=class_level,
                subject=subject,
                chapters=chapters,
                marks=marks,
                difficulty_pct=difficulty,
                context=context,
            )
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail="question paper generation failed") from exc

    @app.post("/teacher/qpapers", response_model=QPOut, status_code=201)
    async def teacher_qp_create(
        payload: QPDraftIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> QPOut:
        """Draft = one retrieval + one AI call behind three validation gates."""
        difficulty = payload.difficulty.model_dump()
        started = time.perf_counter()
        questions, meta = await _qp_fresh_draft(
            payload.class_level,
            payload.subject,
            payload.chapters,
            payload.marks,
            difficulty,
            context=_request_context(
                db,
                teacher,
                class_level=payload.class_level,
                subject=payload.subject,
                chapter=",".join(payload.chapters),
                goal="question_paper",
            ),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        # S2.9 reuse metric: how much of the fresh draft is already banked?
        keys = bank_keys(db, class_level=payload.class_level)
        bank_matches = sum(1 for q in questions if dedupe_key(str(q["text"])) in keys)
        qp = QuestionPaper(
            teacher_id=teacher.id,
            class_level=payload.class_level,
            subject=payload.subject,
            exam_type=payload.exam_type,
            marks=payload.marks,
            duration_min=payload.duration_min,
            difficulty=difficulty,
            chapters=payload.chapters,
            status="draft",
            questions=questions,
            meta=meta,
        )
        db.add(qp)
        db.commit()
        db.refresh(qp)
        json_log(
            logger,
            logging.INFO,
            "qp_draft",
            qp_id=qp.id,
            teacher_id=teacher.id,
            question_count=len(questions),
            elapsed_ms=elapsed_ms,
            # S2.9 reuse metric: drafted questions already reviewed & banked.
            bank_size=len(keys),
            bank_matches=bank_matches,
            reuse_pct=round(100 * bank_matches / len(questions)) if questions else 0,
        )
        return _qp_out(qp)

    @app.get("/teacher/qpapers", response_model=list[QPOut])
    def teacher_qp_list(
        db: DbSession,
        teacher: TeacherOrAdminUser,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[QPOut]:
        # S5.5: newest-first page; QPOut carries the full questions JSON, so
        # unbounded was the largest payload-per-request risk here.
        rows = (
            db.execute(
                select(QuestionPaper)
                .where(QuestionPaper.teacher_id == teacher.id)
                .order_by(QuestionPaper.created_at.desc(), QuestionPaper.id.desc())
                .offset(offset)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [_qp_out(row) for row in rows]

    @app.get("/teacher/qpapers/{qp_id}", response_model=QPOut)
    def teacher_qp_get(qp_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> QPOut:
        return _qp_out(_qp_or_404(db, qp_id, teacher))

    def _qp_editable(qp: QuestionPaper) -> None:
        if qp.status == "final":
            raise HTTPException(status_code=409, detail="paper is already finalised")

    @app.post("/teacher/qpapers/{qp_id}/regenerate", response_model=QPOut)
    async def teacher_qp_regenerate(
        qp_id: int, db: DbSession, teacher: TeacherOrAdminUser
    ) -> QPOut:
        """New AI draft under the same spec; review flags reset."""
        qp = _qp_or_404(db, qp_id, teacher)
        _qp_editable(qp)
        started = time.perf_counter()
        questions, meta = await _qp_fresh_draft(
            qp.class_level,
            qp.subject,
            list(qp.chapters),
            qp.marks,
            dict(qp.difficulty),
            context=_request_context(
                db,
                teacher,
                class_level=qp.class_level,
                subject=qp.subject,
                chapter=",".join(str(c) for c in qp.chapters),
                goal="question_paper",
            ),
        )
        qp.questions = questions
        qp.meta = meta
        qp.reviewed_at = None
        db.commit()
        db.refresh(qp)
        json_log(
            logger,
            logging.INFO,
            "qp_regenerate",
            qp_id=qp.id,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return _qp_out(qp)

    @app.post("/teacher/qpapers/{qp_id}/shuffle", response_model=QPOut)
    def teacher_qp_shuffle(qp_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> QPOut:
        """Reorder questions; review flags reset because positions changed."""
        qp = _qp_or_404(db, qp_id, teacher)
        _qp_editable(qp)
        questions = [dict(q) for q in qp.questions]
        if len(questions) > 1:
            identity = list(range(len(questions)))
            order = identity.copy()
            random.shuffle(order)
            while order == identity:
                random.shuffle(order)
            questions = [questions[i] for i in order]
        for q in questions:
            q["reviewed"] = False
        qp.questions = questions
        qp.reviewed_at = None
        db.commit()
        db.refresh(qp)
        return _qp_out(qp)

    @app.post("/teacher/qpapers/{qp_id}/review", response_model=QPOut)
    def teacher_qp_review(
        qp_id: int, payload: QPReviewIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> QPOut:
        """Accept/edit per question; reviewed_at lands once ALL are reviewed."""
        qp = _qp_or_404(db, qp_id, teacher)
        _qp_editable(qp)
        questions = [dict(q) for q in qp.questions]
        by_ref = {str(q["ref"]): q for q in questions}
        for decision in payload.decisions:
            question = by_ref.get(decision.ref)
            if question is None:
                raise HTTPException(status_code=400, detail=f"unknown question ref: {decision.ref}")
            if decision.action == "edit":
                question["text"] = decision.text
                if decision.options is not None:
                    question["options"] = list(decision.options)
                if decision.answer_index is not None:
                    question["answer_index"] = decision.answer_index
            question["reviewed"] = True
        # S2.9: every reviewed question enters the bank (deduped by content).
        bank_added = 0
        for question in questions:
            if not bool(question.get("reviewed")):
                continue
            answer_index_raw = question.get("answer_index")
            _row, created = store_reviewed(
                db,
                teacher_id=teacher.id,
                text=str(question["text"]),
                options=[str(o) for o in question.get("options", [])],
                answer_index=(int(answer_index_raw) if isinstance(answer_index_raw, int) else None),
                subject=qp.subject,
                chapter=str(question.get("chapter", "")),
                class_level=qp.class_level,
            )
            bank_added += 1 if created else 0
        qp.questions = questions
        if all(bool(q.get("reviewed")) for q in questions):
            qp.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(qp)
        json_log(
            logger,
            logging.INFO,
            "question_bank_reviewed",
            qp_id=qp.id,
            bank_added=bank_added,
            bank_total=sum(1 for q in questions if bool(q.get("reviewed"))),
        )
        return _qp_out(qp)

    @app.post("/teacher/qpapers/{qp_id}/replace", response_model=QPOut)
    async def teacher_qp_replace(
        qp_id: int, payload: QPReplaceIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> QPOut:
        """Swap ONE question for a freshly generated one; still needs review."""
        qp = _qp_or_404(db, qp_id, teacher)
        _qp_editable(qp)
        questions = [dict(q) for q in qp.questions]
        target = next((q for q in questions if str(q["ref"]) == payload.ref), None)
        if target is None:
            raise HTTPException(status_code=400, detail=f"unknown question ref: {payload.ref}")
        label = payload.difficulty or str(target["difficulty"])
        chapter = payload.chapter or str(target["chapter"])
        started = time.perf_counter()
        reuse_source = "ai"
        # S2.9: reuse a reviewed bank question when one fits (MCQ-complete,
        # not already on the paper); the AI draft path stays the fallback.
        replacement: dict[str, object] | None = None
        for row in find_reusable(
            db,
            class_level=qp.class_level,
            subject=qp.subject,
            chapter=chapter,
            exclude_texts=[str(q["text"]) for q in questions],
            limit=8,
        ):
            idx = row.answer_index
            if len(row.options) != 4 or not isinstance(idx, int) or isinstance(idx, bool):
                continue
            if not 0 <= idx <= 3:
                continue
            row.times_reused += 1
            replacement = {
                "ref": str(target["ref"]),
                "text": row.question_text,
                "options": [str(o) for o in row.options],
                "answer_index": idx,
                "marks": int(target["marks"]),
                "difficulty": label,
                "chapter": chapter,
                "reviewed": False,
            }
            reuse_source = "bank"
            break
        if replacement is None:
            fresh, _meta = await _qp_fresh_draft(
                qp.class_level,
                qp.subject,
                list(qp.chapters),
                qp.marks,
                dict(qp.difficulty),
                context=_request_context(
                    db,
                    teacher,
                    class_level=qp.class_level,
                    subject=qp.subject,
                    chapter=chapter,
                    goal="question_paper_replace",
                ),
            )
            used = {str(q["text"]) for q in questions}
            candidates = (
                [
                    q
                    for q in fresh
                    if str(q["text"]) not in used
                    and str(q["difficulty"]) == label
                    and str(q["chapter"]) == chapter
                ]
                or [q for q in fresh if str(q["text"]) not in used and str(q["chapter"]) == chapter]
                or [q for q in fresh if str(q["text"]) not in used]
            )
            replacement = candidates[0] if candidates else None
        if replacement is None:
            raise HTTPException(status_code=502, detail="no distinct replacement question")
        if reuse_source == "ai":
            replacement["ref"] = str(target["ref"])
            replacement["difficulty"] = label
            replacement["chapter"] = chapter
            replacement["reviewed"] = False
        questions[questions.index(target)] = replacement
        qp.questions = questions
        qp.reviewed_at = None
        db.commit()
        db.refresh(qp)
        json_log(
            logger,
            logging.INFO,
            "qp_replace",
            qp_id=qp.id,
            ref=payload.ref,
            reuse_source=reuse_source,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return _qp_out(qp)

    @app.post("/teacher/qpapers/{qp_id}/finalize", response_model=QPOut)
    def teacher_qp_finalize(qp_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> QPOut:
        """FINAL is an explicit teacher action, blocked until every question reviewed."""
        qp = _qp_or_404(db, qp_id, teacher)
        if qp.status == "final":
            raise HTTPException(status_code=409, detail="already finalised")
        unreviewed = [str(q["ref"]) for q in qp.questions if not q.get("reviewed")]
        if unreviewed:
            raise HTTPException(
                status_code=409,
                detail={"code": "review_required", "unreviewed": unreviewed},
            )
        qp.status = "final"
        qp.finalized_at = datetime.now(UTC).replace(tzinfo=None)
        # S5.6 audit event 4/5: qp_finalize (exam-paper finalisation is
        # irreversible for the teacher; ids only in the trail)
        write_audit(
            db,
            action="qp_finalize",
            actor_user_id=teacher.id,
            actor_role=teacher.role,
            target=f"qp:{qp.id}",
            detail={"class_level": qp.class_level, "subject": qp.subject},
        )
        db.commit()
        db.refresh(qp)
        return _qp_out(qp)

    @app.get("/teacher/qpapers/{qp_id}/pdf")
    def teacher_qp_pdf(
        qp_id: int, db: DbSession, teacher: TeacherOrAdminUser, kind: str = "paper"
    ) -> Response:
        if kind not in ("paper", "answer"):
            raise HTTPException(status_code=400, detail="kind must be paper or answer")
        qp = _qp_or_404(db, qp_id, teacher)
        paper = {
            "exam_type": qp.exam_type,
            "class_level": qp.class_level,
            "subject": qp.subject,
            "marks": qp.marks,
            "duration_min": qp.duration_min,
            "chapters": list(qp.chapters),
            "questions": [dict(q) for q in qp.questions],
        }
        try:
            data = render_qp_pdf(paper, kind)
        except Exception:  # shaping libs unavailable -> HTML print view fallback
            return HTMLResponse(render_qp_html(paper, kind))
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="qp-{qp.id}-{kind}.pdf"'},
        )

    # --- S2.6: lesson plan copilot (8 sections, editable + printable) ---------

    @app.post("/teacher/lesson-plans", response_model=LessonPlanOut)
    async def teacher_lesson_plan(
        payload: LessonPlanIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> LessonPlanOut:
        """S2.6: one retrieval + one AI call drafts an eight-section plan.

        Stateless by design: the teacher edits and prints it in the browser,
        so nothing is persisted (see spec: editable + printable only).
        """
        if tutor is None:
            raise HTTPException(status_code=503, detail="provider not configured")
        started = time.perf_counter()
        try:
            sections, sources = await generate_lesson_plan(
                tutor.index,
                tutor.provider,
                class_level=payload.class_level,
                subject=payload.subject,
                chapter=payload.chapter,
                minutes=payload.minutes,
                level=payload.level,
                context=_request_context(
                    db,
                    teacher,
                    class_level=payload.class_level,
                    subject=payload.subject,
                    chapter=payload.chapter,
                    goal="lesson_plan",
                ),
            )
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail="lesson plan generation failed") from exc
        json_log(
            logger,
            logging.INFO,
            "lesson_plan",
            teacher_id=teacher.id,
            class_level=payload.class_level,
            subject=payload.subject,
            plan_level=payload.level,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return LessonPlanOut(
            sections=sections,
            sources=sources,
            class_level=payload.class_level,
            subject=payload.subject,
            chapter=payload.chapter,
            minutes=payload.minutes,
            level=payload.level,
        )

    # --- S2.5: short tests (class+chapter ultra-fast, whole classroom) ------

    def _st_questions(st: ShortTest) -> list[QuizQuestionPublic]:
        return [
            QuizQuestionPublic(
                id=str(q["id"]),
                question_text=str(q["question_text"]),
                options=[str(o) for o in q["options"]],
            )
            for q in st.questions
        ]

    def _st_out(st: ShortTest) -> ShortTestOut:
        return ShortTestOut(
            id=st.id,
            classroom_id=st.classroom_id,
            teacher_id=st.teacher_id,
            subject=st.subject,
            chapter=st.chapter,
            num_questions=st.num_questions,
            duration_min=st.duration_min,
            questions=_st_questions(st),
            attempts=[dict(a) for a in st.attempts],
            created_at=st.created_at,
        )

    @app.post("/teacher/shorttests", response_model=ShortTestOut, status_code=201)
    def teacher_shorttest_create(
        payload: ShortTestIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> ShortTestOut:
        """Generate ONE rule-based set, open an attempt per enrolled student.

        Rule-based (no LLM) so generate->assign stays far below the 10s p95
        target; the wall time is logged as ``shorttest_assigned.elapsed_ms``.
        """
        if index is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
            )
        room = _classroom_or_404(db, payload.classroom_id)
        roster = list(
            db.execute(
                select(Student)
                .join(ClassStudent, ClassStudent.student_id == Student.id)
                .where(ClassStudent.classroom_id == room.id)
                .order_by(Student.id)
            )
            .scalars()
            .all()
        )
        if not roster:
            raise HTTPException(
                status_code=422,
                detail={"code": "empty_roster", "message": "Classroom has no students yet"},
            )
        started = time.perf_counter()
        generator = ClozeQuizGenerator(index.chunks)
        questions = generator.generate(
            class_level=room.class_level,
            subject=canonical_subject(payload.subject),
            chapter=payload.chapter,
            num=payload.num_questions,
            seed=random.randrange(1_000_000_000),
        )
        if not questions:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "no_quiz_for_filter",
                    "message": "No questions for this class/subject/chapter yet",
                },
            )
        dump = dump_quiz(questions)
        attempts: list[dict[str, int]] = []
        for student in roster:
            attempt = QuizAttempt(
                student_id=student.id,
                subject=payload.subject,
                class_level=room.class_level,
                quiz_json=dump,
            )
            db.add(attempt)
            db.flush()
            attempts.append({"student_id": student.id, "attempt_id": attempt.id})
        st = ShortTest(
            classroom_id=room.id,
            teacher_id=teacher.id,
            subject=payload.subject,
            chapter=payload.chapter,
            num_questions=payload.num_questions,
            duration_min=payload.duration_min,
            questions=dump,
            attempts=attempts,
        )
        db.add(st)
        db.commit()
        db.refresh(st)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        json_log(
            logger,
            logging.INFO,
            "shorttest_assigned",
            short_test_id=st.id,
            classroom_id=room.id,
            teacher_id=teacher.id,
            students=len(attempts),
            question_count=len(questions),
            elapsed_ms=elapsed_ms,
        )
        return _st_out(st)

    @app.get("/teacher/shorttests", response_model=list[ShortTestOut])
    def teacher_shorttest_list(
        db: DbSession,
        teacher: TeacherOrAdminUser,
        classroom_id: int | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[ShortTestOut]:
        q = select(ShortTest)
        if teacher.role != "admin":
            q = q.where(ShortTest.teacher_id == teacher.id)
        if classroom_id is not None:
            q = q.where(ShortTest.classroom_id == classroom_id)
        rows = (
            db.execute(
                q.order_by(ShortTest.created_at.desc(), ShortTest.id.desc())
                .offset(offset)
                .limit(limit)  # S5.5: page the list (payload carries questions)
            )
            .scalars()
            .all()
        )
        return [_st_out(row) for row in rows]

    @app.get("/shorttests/mine", response_model=list[ShortTestMineOut])
    def shorttests_mine(
        db: DbSession,
        user: CurrentUser,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[ShortTestMineOut]:
        """Assigned short tests for the signed-in student (duration soft:
        ``expired`` is advisory; submitting after it is still allowed so no
        completed work is lost)."""
        if user.role != "student":
            return []
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is None:
            return []
        room_ids = list(
            db.execute(
                select(ClassStudent.classroom_id).where(ClassStudent.student_id == student.id)
            )
            .scalars()
            .all()
        )
        if not room_ids:
            return []
        rows = (
            db.execute(
                select(ShortTest)
                .where(ShortTest.classroom_id.in_(room_ids))
                .order_by(ShortTest.created_at.desc(), ShortTest.id.desc())
                .limit(limit)  # S5.5: cap per-request payload
            )
            .scalars()
            .all()
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        out: list[ShortTestMineOut] = []
        for st in rows:
            expires_at = st.created_at + timedelta(minutes=st.duration_min)
            own = {int(a["student_id"]): int(a["attempt_id"]) for a in st.attempts}
            out.append(
                ShortTestMineOut(
                    id=st.id,
                    classroom_id=st.classroom_id,
                    attempt_id=own.get(student.id),
                    subject=st.subject,
                    chapter=st.chapter,
                    num_questions=st.num_questions,
                    duration_min=st.duration_min,
                    questions=_st_questions(st),
                    created_at=st.created_at,
                    expires_at=expires_at,
                    expired=now >= expires_at,
                )
            )
        return out

    # --- S2.7: weak heatmap + at-risk detection + support plan ----------------

    def _attempt_percents(db: Session, student_ids: list[int]) -> dict[int, list[float]]:
        """Chronological graded score percentages per student (trend input)."""
        out: dict[int, list[float]] = defaultdict(list)
        if not student_ids:
            return out
        rows = db.execute(
            select(QuizAttempt.student_id, QuizAttempt.score_pct)
            .where(
                QuizAttempt.student_id.in_(student_ids),
                QuizAttempt.status == "graded",
                QuizAttempt.score_pct.is_not(None),
            )
            .order_by(QuizAttempt.student_id, QuizAttempt.created_at.asc())
        ).all()
        for sid, pct in rows:
            out[sid].append(float(pct))
        return out

    def _answer_cells(db: Session, student_ids: list[int]) -> dict[int, dict[str, list[int]]]:
        """(asked, correct) per student x concept from graded quiz answers."""
        cells: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        if not student_ids:
            return cells
        rows = db.execute(
            select(QuizAttempt.student_id, AnswerLog.chapter, AnswerLog.is_correct)
            .join(AnswerLog, AnswerLog.attempt_id == QuizAttempt.id)
            .where(QuizAttempt.student_id.in_(student_ids), QuizAttempt.status == "graded")
        ).all()
        for sid, chapter, ok in rows:
            cell = cells[sid][chapter]
            cell[0] += 1
            cell[1] += int(ok)
        return cells

    def _read_chapters(db: Session, student_ids: list[int]) -> dict[int, set[str]]:
        """Tutor/reading signal: chapters the student has opened in the reader."""
        out: dict[int, set[str]] = defaultdict(set)
        if not student_ids:
            return out
        rows = db.execute(
            select(ChapterProgress.student_id, ChapterProgress.chapter).where(
                ChapterProgress.student_id.in_(student_ids)
            )
        ).all()
        for sid, chapter in rows:
            out[sid].add(chapter)
        return out

    def _weak_matrix(db: Session, class_level: int) -> WeakMatrixOut:
        students = _load_class_students(db, class_level)
        ids = [s.id for s in students]
        cells = _answer_cells(db, ids)
        percents = _attempt_percents(db, ids)
        read = _read_chapters(db, ids)
        weak_map = weakness.weak_names_for(db, ids)

        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for per_student in cells.values():
            for ch, (asked, correct) in per_student.items():
                totals[ch][0] += asked
                totals[ch][1] += correct
        concepts = sorted(totals, key=lambda c: (atrisk.cell_accuracy(*totals[c]) or 0.0, c))

        out_students = [
            WeakStudent(
                student_id=s.id,
                name=s.name,
                avg_score_pct=atrisk.avg_pct(percents.get(s.id, [])),
                attempts_graded=len(percents.get(s.id, [])),
                trend=atrisk.score_trend(percents.get(s.id, [])),
                at_risk=atrisk.is_at_risk(
                    atrisk.avg_pct(percents.get(s.id, [])),
                    atrisk.score_trend(percents.get(s.id, [])),
                ),
                weak_concepts=weak_map.get(s.id, []),
                cells={
                    ch: WeakCell(
                        asked=a,
                        correct=c,
                        accuracy=atrisk.cell_accuracy(a, c),
                        read=ch in read.get(s.id, ()),
                    )
                    for ch, (a, c) in cells.get(s.id, {}).items()
                },
            )
            for s in students
        ]
        return WeakMatrixOut(class_level=class_level, concepts=concepts, students=out_students)

    def _support_plan_out(row: SupportPlan) -> SupportPlanOut:
        return SupportPlanOut(
            id=row.id,
            student_id=row.student_id,
            teacher_id=row.teacher_id,
            class_level=row.class_level,
            focus_concepts=list(row.focus_concepts),
            plan=dict(row.plan),
            created_at=row.created_at,
        )

    @app.get("/teacher/weak-matrix", response_model=WeakMatrixOut)
    def teacher_weak_matrix(
        db: DbSession, teacher: TeacherOrAdminUser, class_level: int
    ) -> WeakMatrixOut:
        """Concept x student accuracy grid with at-risk flags for a class."""
        return _weak_matrix(db, class_level)

    @app.get("/teacher/curriculum-coverage", response_model=CoverageOut)
    def teacher_curriculum_coverage(db: DbSession, teacher: TeacherOrAdminUser) -> CoverageOut:
        """S3.3: class x subject grid -- taught / practiced / mastered (>=70%).

        Taught = chapter content exists for the grade-subject or a
        ClassTeacher row assigns it ('' covers all subjects); practiced =
        quiz attempts by students of that class; mastered = graded mean
        >= coverage.MASTERED_MIN_PCT. Derivation lives in services.coverage
        (pure, unit-tested).
        """
        room_stmt = select(ClassRoom).order_by(ClassRoom.class_level, ClassRoom.section)
        if teacher.role != "admin":
            school = db.get(School, teacher.school_id) if teacher.school_id else None
            if school is None:
                school = _default_school(db)
            room_stmt = room_stmt.where(ClassRoom.school_id == school.id)
        rooms = db.execute(room_stmt).scalars().all()
        room_ids = [r.id for r in rooms]

        # v1 rule: one classroom per student, so this map is unambiguous.
        room_of: dict[int, int] = {}
        if room_ids:
            for cid, sid in db.execute(
                select(ClassStudent.classroom_id, ClassStudent.student_id).where(
                    ClassStudent.classroom_id.in_(room_ids)
                )
            ).all():
                room_of[sid] = cid

        # quiz activity aggregated per (classroom, subject)
        attempts: dict[tuple[int, str], int] = defaultdict(int)
        graded: dict[tuple[int, str], list[float]] = defaultdict(list)
        if room_of:
            rows = db.execute(
                select(
                    QuizAttempt.student_id,
                    QuizAttempt.subject,
                    QuizAttempt.status,
                    QuizAttempt.score_pct,
                ).where(QuizAttempt.student_id.in_(list(room_of)))
            ).all()
            for sid, subject, status, pct in rows:
                if not subject or sid not in room_of:
                    continue
                key = (room_of[sid], subject)
                attempts[key] += 1
                if status == "graded" and pct is not None:
                    graded[key].append(float(pct))

        # assignment signals: chapter content + per-subject teacher rows
        content: dict[int, set[str]] = defaultdict(set)
        for level, subject in db.execute(
            select(ChapterContent.class_level, ChapterContent.subject).distinct()
        ).all():
            content[level].add(subject)
        assigned: dict[int, set[str]] = defaultdict(set)
        if room_ids:
            for cid, subject in db.execute(
                select(ClassTeacher.classroom_id, ClassTeacher.subject).where(
                    ClassTeacher.classroom_id.in_(room_ids)
                )
            ).all():
                assigned[cid].add(subject)

        subjects: set[str] = set()
        cells: list[CoverageCell] = []
        for room in rooms:
            level_content = content.get(room.class_level, set())
            subs = set(level_content)
            subs |= {s for (cid, s) in attempts if cid == room.id}
            subs |= {s for s in assigned.get(room.id, ()) if s}
            for subject in sorted(subs):
                key = (room.id, subject)
                att = attempts.get(key, 0)
                avg = coverage.avg_of(graded.get(key, []))
                taught = coverage.is_taught(
                    subject in level_content, assigned.get(room.id, set()), subject
                )
                status = coverage.derive_status(taught, att > 0, avg)
                subjects.add(subject)
                cells.append(
                    CoverageCell(
                        classroom_id=room.id,
                        class_level=room.class_level,
                        section=room.section,
                        subject=subject,
                        taught=taught,
                        attempts=att,
                        attempts_graded=len(graded.get(key, [])),
                        avg_score_pct=avg,
                        status=status,
                    )
                )
        return CoverageOut(subjects=sorted(subjects), cells=cells)

    @app.post("/teacher/support-plans", response_model=SupportPlanOut, status_code=201)
    def teacher_create_support_plan(
        payload: SupportPlanIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> SupportPlanOut:
        """Rule-based 3-week plan over the student's three weakest concepts."""
        student = db.get(Student, payload.student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="student not found")
        cells = _answer_cells(db, [student.id]).get(student.id, {})
        scored = sorted(
            (
                (ch, acc)
                for ch, (asked, correct) in cells.items()
                if (acc := atrisk.cell_accuracy(asked, correct)) is not None
            ),
            key=lambda t: (t[1], t[0]),
        )
        if not scored:
            raise HTTPException(status_code=422, detail="no graded quiz data for this student")
        weak = [{"name": ch, "accuracy": acc} for ch, acc in scored[:3]]
        plan = atrisk.build_plan(weak)
        row = SupportPlan(
            student_id=student.id,
            teacher_id=teacher.id,
            class_level=student.class_level,
            focus_concepts=plan["focus_concepts"],
            plan=plan,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        json_log(
            logger,
            logging.INFO,
            "support_plan_created",
            student_id=student.id,
            teacher_id=teacher.id,
            focus=len(plan["focus_concepts"]),
        )
        return _support_plan_out(row)

    @app.get("/teacher/support-plans", response_model=list[SupportPlanOut])
    def teacher_list_support_plans(
        db: DbSession, teacher: TeacherOrAdminUser, student_id: int | None = None
    ) -> list[SupportPlanOut]:
        stmt = select(SupportPlan).order_by(SupportPlan.created_at.desc(), SupportPlan.id.desc())
        if teacher.role != "admin":
            stmt = stmt.where(SupportPlan.teacher_id == teacher.id)
        if student_id is not None:
            stmt = stmt.where(SupportPlan.student_id == student_id)
        rows = db.execute(stmt).scalars().all()
        return [_support_plan_out(r) for r in rows]

    # --- S2.8: bulk assignment + tracking (multi-student, one quiz, due date) --

    def _assignment_questions(a: Assignment) -> list[QuizQuestionPublic]:
        return [
            QuizQuestionPublic(
                id=str(q["id"]),
                question_text=str(q["question_text"]),
                options=[str(o) for o in q["options"]],
            )
            for q in a.questions
        ]

    def _assignment_out(a: Assignment) -> AssignmentOut:
        return AssignmentOut(
            id=a.id,
            teacher_id=a.teacher_id,
            subject=a.subject,
            chapter=a.chapter,
            num_questions=a.num_questions,
            due_at=a.due_at,
            questions=_assignment_questions(a),
            attempts=[{k: int(v) for k, v in ref.items()} for ref in a.attempts],
            created_at=a.created_at,
        )

    @app.post("/teacher/assignments", response_model=AssignmentOut, status_code=201)
    def teacher_assignment_create(
        payload: AssignmentIn, db: DbSession, teacher: TeacherOrAdminUser
    ) -> AssignmentOut:
        """Generate ONE rule-based set, open an attempt per selected student.

        All selected students must share one class level so the single shared
        question set stays fair; no LLM call keeps 52-student assigns fast.
        """
        if index is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
            )
        students: list[Student] = []
        for sid in dict.fromkeys(payload.student_ids):  # dedupe, keep order
            student = db.get(Student, sid)
            if student is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "unknown_student", "message": f"Student {sid} not found"},
                )
            students.append(student)
        levels = {st.class_level for st in students}
        if len(levels) > 1:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "mixed_class_levels",
                    "message": "Select students from a single class",
                },
            )
        due_at = payload.due_at
        if due_at.tzinfo is not None:
            due_at = due_at.astimezone(UTC).replace(tzinfo=None)
        started = time.perf_counter()
        generator = ClozeQuizGenerator(index.chunks)
        questions = generator.generate(
            class_level=students[0].class_level,
            subject=canonical_subject(payload.subject),
            chapter=payload.chapter,
            num=payload.num_questions,
            seed=random.randrange(1_000_000_000),
        )
        if not questions:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "no_quiz_for_filter",
                    "message": "No questions for this class/subject/chapter yet",
                },
            )
        dump = dump_quiz(questions)
        attempts: list[dict[str, int]] = []
        for student in students:
            attempt = QuizAttempt(
                student_id=student.id,
                subject=payload.subject,
                class_level=student.class_level,
                quiz_json=dump,
            )
            db.add(attempt)
            db.flush()
            attempts.append({"student_id": student.id, "attempt_id": attempt.id})
        assignment = Assignment(
            teacher_id=teacher.id,
            subject=payload.subject,
            chapter=payload.chapter,
            num_questions=payload.num_questions,
            due_at=due_at,
            questions=dump,
            attempts=attempts,
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        json_log(
            logger,
            logging.INFO,
            "assignment_assigned",
            assignment_id=assignment.id,
            teacher_id=teacher.id,
            students=len(attempts),
            question_count=len(questions),
            elapsed_ms=elapsed_ms,
        )
        return _assignment_out(assignment)

    @app.get("/teacher/assignments", response_model=list[AssignmentOut])
    def teacher_assignment_list(
        db: DbSession,
        teacher: TeacherOrAdminUser,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[AssignmentOut]:
        # S5.5: newest-first page (was every row the teacher ever created).
        q = select(Assignment)
        if teacher.role != "admin":
            q = q.where(Assignment.teacher_id == teacher.id)
        rows = (
            db.execute(
                q.order_by(Assignment.created_at.desc(), Assignment.id.desc())
                .offset(offset)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [_assignment_out(row) for row in rows]

    def _assignment_progress_rows(
        db: Session, assignment: Assignment
    ) -> list[AssignmentProgressRow]:
        now = datetime.now(UTC).replace(tzinfo=None)
        refs = [(int(r["student_id"]), int(r["attempt_id"])) for r in assignment.attempts]
        attempts = (
            {
                a.id: a
                for a in db.execute(
                    select(QuizAttempt).where(QuizAttempt.id.in_([aid for _, aid in refs]))
                ).scalars()
            }
            if refs
            else {}
        )
        names = (
            {
                s.id: s.name
                for s in db.execute(
                    select(Student).where(Student.id.in_([sid for sid, _ in refs]))
                ).scalars()
            }
            if refs
            else {}
        )
        rows: list[AssignmentProgressRow] = []
        for sid, aid in refs:
            attempt = attempts.get(aid)
            done = attempt is not None and attempt.status == "graded"
            score_pct: float | None = None
            if done and attempt is not None and attempt.score_pct is not None:
                score_pct = float(attempt.score_pct)
            rows.append(
                AssignmentProgressRow(
                    student_id=sid,
                    name=names.get(sid, f"#{sid}"),
                    attempt_id=aid,
                    done=done,
                    score_pct=score_pct,
                    overdue=not done and now > assignment.due_at,
                )
            )
        return rows

    @app.get(
        "/teacher/assignments/{assignment_id}/progress",
        response_model=list[AssignmentProgressRow],
    )
    def teacher_assignment_progress(
        assignment_id: int, db: DbSession, teacher: TeacherOrAdminUser
    ) -> list[AssignmentProgressRow]:
        assignment = db.get(Assignment, assignment_id)
        if assignment is None or (teacher.role != "admin" and assignment.teacher_id != teacher.id):
            raise HTTPException(status_code=404, detail="Assignment not found")
        return _assignment_progress_rows(db, assignment)

    @app.get("/assignments/mine", response_model=list[AssignmentMineOut])
    def assignments_mine(
        db: DbSession,
        user: CurrentUser,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[AssignmentMineOut]:
        """Assigned quizzes for the signed-in student. Due date is soft like
        short tests: ``overdue`` is advisory, submitting still grades the work.

        S5.5: membership lives in the attempts JSON, so the candidate window is
        the most recent `limit` assignments (was an unbounded full-table scan),
        and attempt rows are fetched in ONE batched query (was 1 per item).
        A membership link table is the proper long-term fix (documented).
        """
        if user.role != "student":
            return []
        student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
        if student is None:
            return []
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = (
            db.execute(
                select(Assignment)
                .order_by(Assignment.created_at.desc(), Assignment.id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        matched: list[tuple[Assignment, int]] = []
        for a in rows:
            own = {int(r["student_id"]): int(r["attempt_id"]) for r in a.attempts}
            aid = own.get(student.id)
            if aid is not None:
                matched.append((a, aid))
        attempts = (
            {
                a.id: a
                for a in db.execute(
                    select(QuizAttempt).where(QuizAttempt.id.in_([aid for _, aid in matched]))
                ).scalars()
            }
            if matched
            else {}
        )
        out: list[AssignmentMineOut] = []
        for a, aid in matched:
            attempt = attempts.get(aid)
            done = attempt is not None and attempt.status == "graded"
            out.append(
                AssignmentMineOut(
                    id=a.id,
                    attempt_id=aid,
                    subject=a.subject,
                    chapter=a.chapter,
                    questions=_assignment_questions(a),
                    due_at=a.due_at,
                    overdue=now > a.due_at and not done,
                    done=done,
                )
            )
        return out

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
        old_role = target.role
        target.role = payload.role
        # S5.6 audit event 1/5: role_change (ids + before/after only)
        write_audit(
            db,
            action="role_change",
            actor_user_id=admin.id,
            actor_role=admin.role,
            target=f"user:{target.id}",
            detail={"from": old_role, "to": payload.role},
        )
        db.commit()
        db.refresh(target)
        return UserPublic(
            id=target.id, email=target.email, role=target.role, created_at=target.created_at
        )

    # --- S5.6: audited support impersonation (audit event 5/5) ---
    # Short-lived token for the target user, minted only by an admin, with
    # start AND stop rows in the audit trail. Admin-role targets are refused:
    # support never needs admin powers. S5.10 added the missing piece: the
    # token carries a jti and POST /auth/impersonate/exit revokes it through
    # the shared cache, so a session no longer rides out its 15-minute ceiling.

    IMPERSONATION_MINUTES = 15

    @app.post("/admin/users/{user_id}/impersonate", response_model=ImpersonateOut)
    def admin_impersonate(
        user_id: int, payload: ImpersonateRequest, db: DbSession, admin: AdminUser
    ) -> ImpersonateOut:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if target.role in ("admin", "school_admin"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "impersonation_forbidden",
                    "message": "admins cannot be impersonated",
                },
            )
        token = create_access_token(
            target,
            settings=settings,
            minutes=IMPERSONATION_MINUTES,
            # jti makes this specific token revocable (S5.10 exit button /
            # admin revoke), which stateless JWT alone cannot do.
            jti=secrets.token_hex(16),
            extra_claims={"imp": True, "imp_by": admin.id},
        )
        write_audit(
            db,
            action="impersonation",
            actor_user_id=admin.id,
            actor_role=admin.role,
            target=f"user:{target.id}",
            detail={"phase": "start", "reason": payload.reason, "minutes": IMPERSONATION_MINUTES},
        )
        db.commit()
        return ImpersonateOut(
            access_token=token,
            user_id=target.id,
            role=target.role,
            expires_in_min=IMPERSONATION_MINUTES,
        )

    @app.delete("/admin/users/{user_id}/impersonate", status_code=204)
    def admin_impersonate_end(user_id: int, db: DbSession, admin: AdminUser) -> None:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        write_audit(
            db,
            action="impersonation",
            actor_user_id=admin.id,
            actor_role=admin.role,
            target=f"user:{target.id}",
            detail={"phase": "stop"},
        )
        db.commit()

    @app.post("/auth/impersonate/exit", status_code=204)
    def impersonate_exit(request: Request, db: DbSession, user: CurrentUser) -> None:
        """S5.10: the holder of an impersonation token ends the session NOW.

        The jti lands in the revocation cache with a TTL equal to the token's
        remaining life, so the token stops working at once and the cache entry
        itself disappears when the token would have expired anyway. Only works
        with an impersonation token -- a normal session token cannot 'exit'
        itself into 401s (that would be a self-DoS foot-gun).
        """
        claims = getattr(request.state, "jwt_claims", None) or {}
        if not claims.get("imp") or not isinstance(claims.get("jti"), str):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "not_impersonation",
                    "message": "only an impersonation session can exit here",
                },
            )
        exp = claims.get("exp")
        ttl = max(1.0, float(exp) - time.time()) if isinstance(exp, (int, float)) else 900.0
        app.state.cache.set_json(f"imp_revoke:{claims['jti']}", True, ttl)
        write_audit(
            db,
            action="impersonation",
            actor_user_id=user.id,
            actor_role=user.role,
            target=f"user:{user.id}",
            detail={"phase": "exit", "imp_by": claims.get("imp_by")},
        )
        db.commit()

    @app.get("/admin/audit", response_model=AdminAuditPage)
    def admin_audit(
        db: DbSession,
        admin: AdminUser,
        action: str | None = Query(default=None, max_length=40),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> AdminAuditPage:
        """S5.6: the privileged-action trail (newest first), admin-only."""
        stmt = select(AuditLog).order_by(AuditLog.id.desc())
        count_stmt = select(func.count()).select_from(AuditLog)
        if action:
            stmt = stmt.where(AuditLog.action == action)
            count_stmt = count_stmt.where(AuditLog.action == action)
        total = db.execute(count_stmt).scalar_one()
        rows = db.execute(stmt.offset(offset).limit(limit)).scalars().all()
        return AdminAuditPage(
            rows=[
                AuditRowOut(
                    id=r.id,
                    created_at=r.created_at,
                    actor_user_id=r.actor_user_id,
                    actor_role=r.actor_role,
                    action=r.action,
                    target=r.target,
                    detail=dict(r.detail),
                )
                for r in rows
            ],
            total=int(total),
            limit=limit,
            offset=offset,
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

    @app.get("/admin/safety/refusals", response_model=RefusalAuditOut)
    def admin_refusal_audit(db: DbSession, admin: AdminUser, days: int = 30) -> RefusalAuditOut:
        """S4.8 refusal audit: why and where safety refusals happened.

        Aggregates the refused_reason already persisted on ChatMessage --
        counts only, never message content (R11 child-data minimization).
        """
        days = max(1, min(days, 365))
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        rows = db.execute(
            select(ChatMessage.refused_reason, Student.class_level, ChatMessage.created_at)
            .join(Conversation, ChatMessage.conversation_id == Conversation.id)
            .join(Student, Conversation.student_id == Student.id)
            .where(ChatMessage.refused_reason.is_not(None))
            .where(ChatMessage.created_at >= cutoff)
        ).all()
        by_reason: dict[str, int] = defaultdict(int)
        by_class: dict[str, int] = defaultdict(int)
        last_at: datetime | None = None
        for reason, class_level, created_at in rows:
            by_reason[reason or "unknown"] += 1
            by_class[str(class_level)] += 1
            if last_at is None or created_at > last_at:
                last_at = created_at
        return RefusalAuditOut(
            days=days,
            total_refusals=len(rows),
            by_reason=dict(by_reason),
            by_class=dict(by_class),
            last_refusal_at=last_at,
        )

    @app.post("/admin/maintenance/purge", response_model=dict)
    def admin_purge_expired(db: DbSession, admin: AdminUser, dry_run: bool = False) -> dict:
        """Retention sweep (D20, S5.8): expired tokens, stale invites, old chats.

        Child-data minimization: conversations older than
        ``chat_retention_days`` are deleted with their messages. With
        ``dry_run=true`` the SAME count report is returned without deleting
        anything (compliance evidence); real runs also write the audit row.
        """
        report = run_retention_sweep(db, settings=settings, dry_run=dry_run)
        if not dry_run:
            # S5.6 audit event 3/5: purge (counts only -- never deleted content)
            write_audit(
                db,
                action="purge",
                actor_user_id=admin.id,
                actor_role=admin.role,
                target="retention_sweep",
                detail={k: v for k, v in report.items() if k != "dry_run"},
            )
            db.commit()
        return report

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
        weak_chapters = weakness.weak_names(db, student.id)
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

    # S3.4: in-process weekly digest scheduler. Once per ISO week, Sunday
    # ~22:00 Dhaka (digest_due owns the rule). The job reads ONLY aggregates
    # (services.parent_digest); conversation content is never queried.
    # S5.4: the once-per-week guard moved from a per-process dict into the
    # job_runs ledger (jobs.claim_period), so N gunicorn workers can no
    # longer double-send; with JOBS_BACKEND=arq the ARQ worker owns the
    # schedule instead and these loops stay off.
    async def parent_digest_loop() -> None:
        while True:
            try:
                result = await asyncio.to_thread(jobs.run_weekly_digest, session_factory, settings)
                if result["ran"]:
                    json_log(logger, logging.INFO, "parent_digest_run", **result)
            except Exception as exc:  # the loop must survive any job failure
                json_log(logger, logging.WARNING, "parent_digest_error", error=str(exc)[:200])
            await asyncio.sleep(max(1, settings.parent_digest_check_minutes) * 60)

    @app.on_event("startup")
    async def start_parent_digest() -> None:
        if not settings.parent_digest_enabled or settings.jobs_backend == "arq":
            return
        app.state.digest_task = asyncio.create_task(parent_digest_loop())
        json_log(logger, logging.INFO, "parent_digest_scheduler_started")

    @app.on_event("shutdown")
    async def stop_parent_digest() -> None:
        task = getattr(app.state, "digest_task", None)
        if task is not None:
            task.cancel()

    # S4.6: nightly weakness reconciliation -- recomputes chapter-root rows of
    # ConceptMastery from the graded answer log so the persisted per-concept
    # mastery cannot drift from the rollup the three consumers read. Logs
    # counts only (R11). S5.4: once-per-day claim lives in job_runs now.
    async def weakness_refresh_loop() -> None:
        while True:
            try:
                result = await asyncio.to_thread(jobs.run_nightly_rollup, session_factory, settings)
                if result["ran"]:
                    json_log(logger, logging.INFO, "weakness_refresh_run", **result)
            except Exception as exc:  # the loop must survive any job failure
                json_log(logger, logging.WARNING, "weakness_refresh_error", error=str(exc)[:200])
            await asyncio.sleep(max(1, settings.weakness_refresh_check_minutes) * 60)

    @app.on_event("startup")
    async def start_weakness_refresh() -> None:
        if not settings.weakness_refresh_enabled or settings.jobs_backend == "arq":
            return
        app.state.weakness_task = asyncio.create_task(weakness_refresh_loop())
        json_log(logger, logging.INFO, "weakness_refresh_scheduler_started")

    @app.on_event("shutdown")
    async def stop_weakness_refresh() -> None:
        task = getattr(app.state, "weakness_task", None)
        if task is not None:
            task.cancel()

    return app


app = create_app()
