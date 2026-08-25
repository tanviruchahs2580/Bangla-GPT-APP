from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bangla GPT API"
    version: str = "0.1.0"
    env: str = "development"
    llm_provider: str = "mock"
    database_url: str = "sqlite://"
    jwt_secret: str = "dev-insecure-change-me"
    jwt_expire_minutes: int = 60
    rate_limit_login_per_minute: int = 10
    rate_limit_tutor_per_minute: int = 30
    max_body_bytes: int = 65536
    admin_email: str | None = None
    admin_password: str | None = None
    nctb_corpus_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
