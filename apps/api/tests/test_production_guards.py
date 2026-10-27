"""Production must refuse unsafe defaults, not merely warn about them.

Three defects found on 2026-10-09, all reachable by running the documented
stack, because docker-compose.yml defaults ENV to production while also
defaulting the other two variables to values production should refuse:

  AUD-0025  LLM_PROVIDER=mock  -> production served fabricated tutor answers
  AUD-0026  file SQLite        -> two gunicorn workers contending on one file
  AUD-0027  RATE_LIMIT_BACKEND=memory -> effective limits multiplied by workers

Every test here asserts the boot guard refuses, except the last two, which
assert the documented escape hatches still work so the guard cannot be
"passed" by simply deleting it.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import (
    _validate_database,
    _validate_llm_provider,
    _validate_rate_limit_redis,
)

PG = "postgresql+psycopg://u:p@localhost:5432/db"


def prod(**overrides) -> Settings:
    base = {
        "env": "production",
        "pii_allow_plaintext": False,
        "jwt_secret": "Zk7Qp2XvN8mR4tYcW1bH6jL3sD9fG5aE0uI2oP7xV4qM8nC6rT1wY3zB5",
        "database_url": PG,
        "allowed_origins": "https://app.example.test",
        "admin_email": "admin@example.test",
        "admin_password": "Str0ngAdminPassw0rd!",
        "metrics_require_auth": True,
        "metrics_token": "m" + "0" * 32,
        "pii_enc_key": "LjDorcxuiR0OrEApp_g6hwfAbKKwimZQOPIvEz1pRhk=",
        "smtp_enabled": True,
        "smtp_host": "smtp.example.test",
        "smtp_from": "noreply@example.test",
    }
    base.update(overrides)
    return Settings(**base)


# --- AUD-0025: mock provider -------------------------------------------------


def test_mock_provider_is_refused_in_production():
    assert prod(llm_provider="mock").is_production
    problems = _validate_llm_provider(prod(llm_provider="mock"))
    assert problems, "production must refuse the mock provider"
    assert "mock" in problems[0]


def test_gemini_provider_still_requires_its_key():
    assert _validate_llm_provider(prod(llm_provider="gemini"))
    assert not _validate_llm_provider(prod(llm_provider="gemini", gemini_api_key="k"))


def test_mock_provider_is_still_fine_outside_production():
    """The guard must not break development, CI or the mock-based test suite."""
    assert Settings(env="development", llm_provider="mock").is_production is False


def test_mock_in_production_requires_an_explicit_opt_in(monkeypatch):
    """The escape hatch is opt-in, not a default."""
    monkeypatch.delenv("ALLOW_MOCK_LLM_IN_PRODUCTION", raising=False)
    assert _validate_llm_provider(prod(llm_provider="mock"))
    monkeypatch.setenv("ALLOW_MOCK_LLM_IN_PRODUCTION", "true")
    assert not _validate_llm_provider(prod(llm_provider="mock"))


# --- AUD-0026: SQLite with workers -------------------------------------------


def test_file_sqlite_is_refused_when_multiple_workers_run(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    problems = _validate_database(prod(database_url="sqlite:////data/app.db"))
    assert problems, "file SQLite behind 2 workers must be refused"
    assert "SQLite" in problems[0]


def test_file_sqlite_is_allowed_with_a_single_worker(monkeypatch):
    """Not a blanket ban: one worker on SQLite is a legitimate small setup."""
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    assert not _validate_database(prod(database_url="sqlite:////data/app.db"))


def test_postgres_is_always_accepted(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    assert not _validate_database(prod(database_url=PG))


def test_in_memory_sqlite_was_already_refused(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    assert _validate_database(prod(database_url="sqlite://"))


# --- AUD-0027: rate-limit backend --------------------------------------------


def test_memory_rate_limiter_is_refused_with_multiple_workers(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    problems = _validate_rate_limit_redis(prod(rate_limit_backend="memory"))
    assert problems, "a per-process limiter must be refused behind 2 workers"
    assert "worker" in problems[0]


def test_memory_rate_limiter_is_allowed_with_one_worker(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    assert not _validate_rate_limit_redis(prod(rate_limit_backend="memory"))


def test_redis_backend_still_requires_a_url(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    assert _validate_rate_limit_redis(prod(rate_limit_backend="redis", redis_url=""))
    assert not _validate_rate_limit_redis(
        prod(rate_limit_backend="redis", redis_url="redis://localhost:6379/0")
    )


@pytest.mark.parametrize("bad", ["not-a-number", "", "0", "-3"])
def test_unparseable_worker_count_does_not_bypass_the_guard(monkeypatch, bad):
    """A malformed WEB_CONCURRENCY must fail safe, not skip validation."""
    monkeypatch.setenv("WEB_CONCURRENCY", bad)
    assert _validate_database(prod(database_url="sqlite:////data/app.db"))
    assert _validate_rate_limit_redis(prod(rate_limit_backend="memory"))
