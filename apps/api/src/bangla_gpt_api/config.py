from __future__ import annotations

import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PRODUCTION_ENVS = frozenset({"production", "prod", "staging"})
# staging/prod parity: staging runs the SAME strict boot guard and secret
# suppression as production (no default JWT_SECRET, no raw reset-token logs);
# only the data is non-authoritative. Enforced by tests/test_env_parity.py.
DEFAULT_JWT_SECRET = "dev-insecure-change-me"  # noqa: S105 - an obvious placeholder or a fixture name, not a credential


def _get_version() -> str:
    """Read version from the installed package metadata.

    Falls back to a hardcoded constant when the package is not installed
    (editable install, test harness, or bare-source execution).
    """
    try:
        from importlib.metadata import version as _version

        return _version("bangla-gpt-api")
    except Exception:
        # Fallback for bare-source execution (must track pyproject version).
        return "0.9.2"


class Settings(BaseSettings):
    """Single source of truth for every runtime parameter.

    ``.env.example`` must document every field here (enforced by
    ``tests/test_env_example.py``).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bangla GPT API"
    version: str = _get_version()
    env: str = "development"

    # --- AI providers ---
    # Primary provider: "mock", "gemini", or "openai"
    llm_provider: str = "mock"
    gemini_api_key: str | None = None
    # Verified live 2026-08-26 with new-format ("AQ.") API keys, which cannot
    # access legacy models like gemini-2.5-flash ("no longer available to new
    # users"). Override via GEMINI_MODEL if your account has broader access.
    gemini_model: str = "gemini-3.1-flash-lite"
    # model router: model serving SIMPLE routes. Empty -> the main
    # model serves every route (routes are still decided + logged).
    gemini_fast_model: str = ""
    # OpenAI-compatible provider settings
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None  # None -> official OpenAI endpoint
    # Fallback provider (secondary). E.g., "gemini" when primary is "openai".
    # Empty -> no fallback. When set and primary fails with ProviderError,
    # the fallback is used automatically (circuit breaker enabled).
    llm_fallback_provider: str = ""  # "gemini" | "openai" | ""
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    # A9: hard ceiling on generated completion size, wired into every real
    # provider payload (OpenAI max_tokens / Gemini maxOutputTokens). Bounds
    # the cost of a looping model; 0 disables the cap (key omitted).
    llm_max_output_tokens: int = 2048
    # AI-002: monthly per-user AI budget (USD, estimated — see services/costs.py).
    # 0 (default) = unlimited. When set, generation entry points refuse with
    # 429 ai_budget_exceeded once the user's current-month ledger hits the cap.
    ai_monthly_budget_usd_per_user: float = 0.0
    # I-11: global (whole-deployment) monthly AI budget in USD. 0 (default) =
    # not configured, and the series bgpt_ai_monthly_budget_usd is NOT
    # exported, so the burn-rate alert cannot fire on an unset budget. Set it
    # with the provider figure you have actually budgeted; the alert compares
    # the projected month-end spend against it.
    ai_monthly_budget_usd: float = 0.0
    # I-01: emit one structured JSON access line per request (method, route,
    # status, latency_ms, pseudonymous user ref) next to the Prometheus
    # counters, so metric-to-log correlation does not need the database.
    access_log_enabled: bool = True
    # I-03: emit per-stage trace records (retrieval, prompt, generation) as
    # structured JSON events carrying the trace id, index/prompt versions,
    # token counts and retrieved chunk ids. The no-collector equivalent of
    # OpenTelemetry spans; see docs/operations/TRACING.md.
    tracing_enabled: bool = False
    # H-07: PostgreSQL per-session guards applied on every connection. A
    # statement that runs past the timeout is cancelled by the server instead
    # of holding one of the pool's connections until the client gives up;
    # lock_timeout bounds how long a transaction waits on a contested lock.
    # 0 disables the guard (not recommended in production).
    db_statement_timeout_ms: int = 30_000
    db_lock_timeout_ms: int = 5_000
    # Circuit breaker thresholds
    circuit_breaker_failure_threshold: int = 3  # failures before opening
    circuit_breaker_reset_timeout_seconds: float = 60.0  # seconds before half-open

    # --- RAG v2 retrieval ---
    # "hybrid" = lexical BM25 lane + vector lane fused by reciprocal rank
    # fusion, then lexically reranked (retrieval/hybrid_index.py).
    # "bm25" = lexical lane only (v1 baseline).
    retrieval_mode: str = "hybrid"
    # Real multilingual embedding models are a staging human decision.
    # Empty -> the deterministic local hash-ngram embedder serves the vector
    # lane; naming a model without the staging backend is a config error.
    embedding_model: str = ""

    # --- persistence ---
    # File-based SQLite by default so local dev data survives restarts.
    # In-memory ("sqlite://" / "sqlite:///:memory:") is for tests only;
    # production boot refuses in-memory stores (see enforce_production_safety).
    database_url: str = "sqlite:///./bangla_gpt.db"

    # --- auth ---
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 60
    # SEC-03: tokens are stamped with and verified against these so a token
    # minted for a different audience/issuer (e.g. a future service sharing the
    # signing key) cannot be replayed here.
    jwt_issuer: str = "bangla-gpt-api"
    jwt_audience: str = "bangla-gpt-clients"
    password_reset_token_minutes: int = 30

    # --- admin bootstrap / lifecycle ---
    admin_email: str | None = None
    admin_password: str | None = None
    force_admin_password_change: bool = True

    # --- HTTP hardening ---
    allowed_origins: str = ""
    # Ceiling must fit the wave-2 vision contract (up to 1_500_000 decoded
    # bytes of base64 in one chat turn); a smaller limit makes the middleware
    # reject a valid image turn before the route can answer image_invalid.
    max_body_bytes: int = 4_000_000

    # --- rate limiting ---
    rate_limit_login_per_minute: int = 10
    rate_limit_tutor_per_minute: int = 30
    # Generic IP ceiling for remaining /tutor/* routes (conversation listing).
    rate_limit_tutor_ip_per_minute: int = 60
    rate_limit_backend: str = "memory"  # memory | redis
    rate_limit_fail_open: bool = False
    redis_url: str | None = None
    # inline = scheduler loops inside the web process (default);
    # arq = an external ARQ worker owns the schedule (job bodies live in jobs.py).
    jobs_backend: str = "inline"  # inline | arq
    # Enable ONLY behind a trusted reverse proxy (Caddy/nginx) that APPENDS
    # the real peer to X-Forwarded-For ($proxy_add_x_forwarded_for) and is the
    # only trusted hop; the limiter reads the LAST valid entry (S-001). With
    # any other proxy setup the header is spoofable and clients could rotate
    # fake rate-limit identities.
    trust_proxy_headers: bool = False
    # Fernet key (PII_ENC_KEY) for encrypting guardian phone at rest.
    # Without it values pass through unchanged (dev/test); production boot
    # refuses to start without a key (enforce_production_safety).
    pii_enc_key: str | None = None

    # --- chat ---
    chat_history_messages: int = 8
    # A24: per-message cap applied when conversation history is replayed
    # into a prompt, so one giant pasted turn cannot blow the context.
    chat_history_message_char_limit: int = 2000
    chat_retention_days: int = 180

    # Product analytics trail (analytics_events). The model docstring claims
    # "cleaned by the retention sweep" and no sweep touched the table at all,
    # so the trail grew without bound and survived account erasure still
    # carrying user_id (F-058). Same window as chat by default; the trail is
    # coarser data than the conversation itself.
    analytics_retention_days: int = 180

    # --- parent invites ---
    invite_ttl_minutes: int = 1440
    # Legacy bare-ID parent linking is DISABLED by default: any parent could
    # link any student_id and read progress. The invite-code flow replaces it;
    # enable only for controlled migrations/tests.
    allow_direct_parent_link: bool = False

    # --- email delivery (password reset) ---
    smtp_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    # --- parent weekly digest ---
    # Sunday ~22:00 Dhaka, once per ISO week; summary aggregates only, never
    # conversation content. Check cadence for the in-process scheduler loop.
    parent_digest_enabled: bool = True
    parent_digest_check_minutes: int = 60

    # --- nightly weakness reconciliation ---
    # Daily 03:00 Dhaka: recompute chapter-root ConceptMastery from the graded
    # answer log (aggregate counts only, ). Keeps the persisted per-concept
    # mastery in sync with the rollup that Home/Teacher/Parent read.
    weakness_refresh_enabled: bool = True
    weakness_refresh_check_minutes: int = 60

    # --- data ---
    nctb_corpus_dir: str | None = None

    # --- default rate limit rules (merged over per-field settings in middleware_stack) ---
    # NOTE: the chat LLM routes are /tutor/conversations/{id}/messages[/stream];
    # a "/tutor/chat" key would match no real path.
    rate_limit_rules: dict[str, tuple[int, str]] = {
        "/auth/login": (10, "ip"),
        "/auth/mfa/challenge": (5, "ip"),
        # F-076: registration was unlimited -- each call runs Argon2id and
        # sends a verification mail, so an unbounded caller was an unbounded
        # CPU and mail pump from one address.
        "/auth/register": (10, "ip"),
        # The authenticated MFA legs (enroll/verify/disable). Scoped per user,
        # not per IP, because a school NAT puts a whole class behind one
        # address; the genuine brute-force surface is /auth/mfa/challenge
        # above, which stays the tighter 5/minute bound.
        "/auth/mfa": (20, "user"),
        "/tutor/ask": (30, "user"),
        "/tutor/conversations": (30, "user"),
        "/tutor": (60, "ip"),
        "/auth/forgot": (10, "ip"),
        "/auth/reset": (10, "ip"),
        # Unauthenticated resend (login stuck at email_unverified) must be
        # throttled like forgot/reset to avoid email-spam abuse.
        "/auth/resend-verification": (10, "ip"),
        "/auth/verify-email": (10, "ip"),
        # The invite code is 64 bits, but an unthrottled redeem is still a free
        # oracle for guessing one.
        "/parents/link/invite": (10, "ip"),
        # The costly teacher AI paths: each spends provider tokens on a
        # teacher's behalf, so without a per-user bound one token can loop at
        # full network speed and the bill lands on the account (SEC-002).
        "/teacher/content": (20, "user"),
        "/teacher/qpapers": (20, "user"),
        "/teacher/lesson-plans": (20, "user"),
        "/teacher/generate": (20, "user"),
        "/teacher/jobs": (20, "user"),
        # Roster import runs one Argon2id hash per created student.
        "/teacher/classrooms": (30, "user"),
        # S-003: each of these opens one QuizAttempt (plus an in-app
        # notification) per roster student in a single call, so an unbounded
        # caller is an unbounded row/notification pump aimed at minors.
        "/teacher/shorttests": (20, "user"),
        "/teacher/assignments": (20, "user"),
        # S-012: quiz generation walks the whole corpus and inserts a
        # QuizAttempt per call; unbounded it is both CPU and storage abuse.
        # Per user, not per IP: a school NAT must not lock out a classroom.
        "/quizzes": (20, "user"),
        "/events": (60, "ip"),
    }

    # --- observability ---
    log_level: str = "INFO"
    sentry_dsn: str | None = None
    sentry_env: str = "development"

    # --- hardening (Phase 4) ---
    # protect /metrics in production — internal ingress or bearer token
    metrics_require_auth: bool = False
    metrics_token: str | None = None

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in PRODUCTION_ENVS

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


class SettingsRegistry:
    """Thread-safe settings cache with optional hot-reload capability.

    By default it uses:func:`get_settings` (cached singleton) for simplicity.
    When ``force_reload=True`` is passed, a fresh ``Settings`` instance is
    constructed (useful for tests or config-reload scenarios).
    """

    _settings: Settings | None = None

    @classmethod
    def get(cls, force_reload: bool = False) -> Settings:
        if cls._settings is None or force_reload:
            cls._settings = Settings()
        return cls._settings

    @classmethod
    def clear(cls) -> None:
        cls._settings = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
