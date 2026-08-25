from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENVS = frozenset({"production", "prod"})
DEFAULT_JWT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    """Single source of truth for every runtime parameter.

    ``.env.example`` must document every field here (enforced by
    ``tests/test_env_example.py``).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bangla GPT API"
    version: str = "0.2.1"
    env: str = "development"

    # --- LLM provider ---
    llm_provider: str = "mock"
    gemini_api_key: str | None = None
    # Verified live 2026-08-26 with new-format ("AQ.") API keys, which cannot
    # access legacy models like gemini-2.5-flash ("no longer available to new
    # users"). Override via GEMINI_MODEL if your account has broader access.
    gemini_model: str = "gemini-3.1-flash-lite"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

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
    max_body_bytes: int = 65536

    # --- rate limiting ---
    rate_limit_login_per_minute: int = 10
    rate_limit_tutor_per_minute: int = 30
    rate_limit_backend: str = "memory"  # memory | redis
    rate_limit_fail_open: bool = False
    redis_url: str | None = None

    # --- email delivery (password reset) ---
    smtp_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    # --- data ---
    nctb_corpus_dir: str | None = None

    # --- observability ---
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in PRODUCTION_ENVS

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
