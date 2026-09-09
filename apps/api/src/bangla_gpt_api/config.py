from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENVS = frozenset({"production", "prod", "staging"})
# S5.1 staging/prod parity: staging runs the SAME strict boot guard and secret
# suppression as production (no default JWT_SECRET, no raw reset-token logs);
# only the data is non-authoritative. Enforced by tests/test_env_parity.py.
DEFAULT_JWT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    """Single source of truth for every runtime parameter.

    ``.env.example`` must document every field here (enforced by
    ``tests/test_env_example.py``).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bangla GPT API"
    version: str = "0.6.2"
    env: str = "development"

    # --- LLM provider ---
    llm_provider: str = "mock"
    gemini_api_key: str | None = None
    # Verified live 2026-08-26 with new-format ("AQ.") API keys, which cannot
    # access legacy models like gemini-2.5-flash ("no longer available to new
    # users"). Override via GEMINI_MODEL if your account has broader access.
    gemini_model: str = "gemini-3.1-flash-lite"
    # S4.2 model router: model serving SIMPLE routes. Empty -> the main
    # model serves every route (routes are still decided + logged).
    gemini_fast_model: str = ""
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # --- S4.3 RAG v2 retrieval ---
    # "hybrid" = lexical BM25 lane + vector lane fused by reciprocal rank
    # fusion, then lexically reranked (retrieval/hybrid_index.py).
    # "bm25" = lexical lane only (v1 baseline).
    retrieval_mode: str = "hybrid"
    # Real multilingual embedding models are a staging human decision (R8).
    # Empty -> the deterministic local hash-ngram embedder serves the vector
    # lane; naming a model without the staging backend is a config error.
    embedding_model: str = ""

    # --- persistence ---
    database_url: str = "sqlite://"

    # --- auth ---
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 60
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
    # S5.4: inline = scheduler loops inside the web process (default);
    # arq = an external ARQ worker owns the schedule (job bodies live in jobs.py).
    jobs_backend: str = "inline"  # inline | arq
    # Enable ONLY behind a trusted reverse proxy (Caddy/nginx) that overwrites
    # X-Forwarded-For; otherwise clients can spoof their rate-limit identity.
    trust_proxy_headers: bool = False
    # S5.6: Fernet key (PII_ENC_KEY) for encrypting guardian phone at rest.
    # Without it values pass through unchanged (dev/test); production boot
    # refuses to start without a key (enforce_production_safety).
    pii_enc_key: str | None = None

    # --- chat ---
    chat_history_messages: int = 8
    chat_retention_days: int = 180

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

    # --- parent weekly digest (S3.4) ---
    # Sunday ~22:00 Dhaka, once per ISO week; summary aggregates only, never
    # conversation content. Check cadence for the in-process scheduler loop.
    parent_digest_enabled: bool = True
    parent_digest_check_minutes: int = 60

    # --- S4.6 nightly weakness reconciliation ---
    # Daily 03:00 Dhaka: recompute chapter-root ConceptMastery from the graded
    # answer log (aggregate counts only, R11). Keeps the persisted per-concept
    # mastery in sync with the rollup that Home/Teacher/Parent read.
    weakness_refresh_enabled: bool = True
    weakness_refresh_check_minutes: int = 60

    # --- data ---
    nctb_corpus_dir: str | None = None

    # --- observability ---
    log_level: str = "INFO"
    sentry_dsn: str | None = None
    sentry_env: str = "development"

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in PRODUCTION_ENVS

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
