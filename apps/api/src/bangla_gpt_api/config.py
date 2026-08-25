from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bangla GPT API"
    version: str = "0.1.0"
    env: str = "development"
    llm_provider: str = "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
