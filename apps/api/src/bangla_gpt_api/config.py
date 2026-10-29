from __future__ import annotations

import logging
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PRODUCTION_ENVS = frozenset({"production", "prod", "staging"})
# BE/ENV-gate audit: PRODUCTION_ENVS is kept for reference, but it is no
# longer what is_production checks. The old allowlist ("these names ARE
# production") made safety a free-text spelling contest: boot a pilot with
# ENV=uat, ENV=live, or a typo like ENV=prodction and every guard silently
# switched off -- open /metrics, default JWT secret accepted, the mock
# provider serving fabricated answers to children, SMTP verification
# bypassed. The gate is now a DENYLIST of explicitly unguarded names:
# anything unknown boots guarded. staging keeps production parity by
# construction instead of by enumeration.
#
# These are the ONLY names that skip the guard, and each is a genuine
# development/CI lane: the test suite and dev loops, the developer's own
# machine, the CI container smoke, and Vercel preview builds. Anything
# else -- a deployment name, a typo -- runs the strict production boot
# battery and the denylist goes into the boot error so the operator can
# see which names WOULD have been unguarded. Pinned by tests/test_env_gate.py.
NON_PRODUCTION_ENVS = frozenset({"development", "dev", "local", "test", "ci", "preview"})
# staging/prod parity: staging runs the SAME strict boot guard and secret
# suppression as production (no default JWT_SECRET, no raw reset-token logs);
# only the data is non-authoritative. Enforced by tests/test_env_parity.py.
DEFAULT_JWT_SECRET = "dev-insecure-change-me"  # noqa: S105 - an obvious placeholder or a fixture name, not a credential


def _project_version() -> str:
    """Read the release version from ``apps/api/pyproject.toml``.

    The manifest is the repository's single source of truth (README: "Nothing
    else may carry a version number"); the installed distribution metadata is
    generated from it at install time.
    """
    manifest = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with manifest.open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _get_version() -> str:
    """Read version from the installed package metadata.

    Source-tree runs (bare execution, a harness with no installed
    distribution) fall back to the same pyproject.toml the metadata is built
    from, so the fallback tracks the release manifest instead of a literal
    that drifts on every version bump (F-053).
    """
    try:
        from importlib.metadata import version as _version

        return _version("bangla-gpt-api")
    except Exception:
        return _project_version()


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
    # F-031: operator kill switch for AI generation. false = the tutor/chat
    # generation surfaces answer with a localized refusal envelope
    # (refused_reason=ai_generation_disabled) instead of calling a provider;
    # retrieval, /search, the reader and quizzes keep working, and provider/
    # index construction is untouched (unlike unsetting LLM_PROVIDER, which
    # also removes the index). Default true keeps generation on.
    ai_generation_enabled: bool = True
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
    # Production boot refuses to start without a valid key (enforce_production_safety).
    pii_enc_key: str | None = None
    # B-04: the old behaviour passed guardian phones through unencrypted
    # whenever no key was configured -- silently, everywhere. Dev/test keep
    # that convenience, but only because this flag names the choice;
    # production refuses to boot with it on, and with it off a missing key
    # makes the write fail with a coded 503 instead of storing PII in the
    # clear (security.py::encrypt_pii_strict).
    pii_allow_plaintext: bool = True

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
    # DB-04: the answer log is the child's graded-answer record — it gets a
    # LONG window (two school years) but it GETS one now; the table shipped
    # without a timestamp at all, so nothing could ever age it out.
    answer_log_retention_days: int = 730
    # The AI spend ledger. The budget math only reads the current month, so
    # a year of history is generous for dashboards and audits while keeping
    # the table bounded for accounts that live for years.
    ai_usage_retention_days: int = 365

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
    # F-016: with NCTB_CORPUS_DIR empty (the compose default) the tutor falls
    # back to the bundled 78-chunk synthetic sample corpus and cites it as
    # evidence. That fallback is a legitimate start-small mode, so it gets an
    # explicit opt-in instead of being deleted; a production boot with a
    # billable provider and no corpus is refused without it
    # (see _validate_corpus in main.py and the load-time guard in
    # initialize/dependencies.py).
    allow_bundled_sample_corpus_in_production: bool = False

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
        # B-02: session renewal. User-scoped: a school NAT shares one IP
        # across a class, and the proactive renewal loop fires on every api()
        # call near the token's last five minutes -- a per-IP bound would
        # throttle a whole classroom's honest sessions at once.
        "/auth/renew": (60, "user"),
        "/auth/forgot": (10, "ip"),
        "/auth/reset": (10, "ip"),
        # The password-verifying counterpart of /auth/login had NO rule: a
        # stolen-token holder (or shared school device) could guess the
        # CURRENT password unbounded, and each attempt costs two Argon2id
        # operations (verify + hash-on-save) -- the worst cost profile on any
        # credential endpoint, with no throttle. Scoped per user for the same
        # school-NAT reason as /auth/mfa above; the unauthenticated fallback
        # is the caller's IP.
        "/auth/change-password": (10, "user"),
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
        # Denylist, not allowlist: see NON_PRODUCTION_ENVS at the top of
        # this file. The frozenset is inlined here on purpose -- this is the
        # one decision every guard reads, and it must not depend on a
        # module-global lookup resolving at call time. Keep the two in sync
        # (tests/test_env_gate.py pins the behaviour on both ends).
        return self.env.strip().lower() not in frozenset(
            {"development", "dev", "local", "test", "ci", "preview"}
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def has_billable_llm_provider(self) -> bool:
        """True when a configured provider bills per token (not the mock).

        Used by the production boot guards (F-016 corpus, F-034 AI budget):
        the mock provider is itself refused in production unless the offline
        demo opt-in is set, and its ledger cost is exactly 0, so there is no
        spend ceiling to enforce and no real answer served from a sample
        corpus. A named fallback provider counts too -- it can serve traffic.
        """
        return any(
            name.strip().lower() not in ("", "mock")
            for name in (self.llm_provider, self.llm_fallback_provider)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
