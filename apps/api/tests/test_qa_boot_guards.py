"""F-016: production boot guard for the bundled synthetic sample corpus.

The compose stack ships NCTB_CORPUS_DIR empty; the loader then falls back to
the 78-chunk synthetic sample and the tutor cites it as evidence to children,
reported only by a log line and a metric. The validator is exercised directly,
in the style of tests/test_production_guards.py, plus one end-to-end
``enforce_production_safety`` run and one load-time run of the second door (a
configured directory that yields no usable chunks).

The mock provider is a documented exemption: it is itself refused in
production unless ALLOW_MOCK_LLM_IN_PRODUCTION is set, serves no real answer,
and the sample is coherent with a deliberate offline demo -- so mock-based
production boot tests keep passing unchanged.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api import caching
from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.dependencies import build_dependencies
from bangla_gpt_api.main import (
    _validate_corpus,
    enforce_production_safety,
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
        "llm_provider": "gemini",
        "gemini_api_key": "k" * 32,
        "nctb_corpus_dir": "/data/nctb",
        "ai_monthly_budget_usd_per_user": 5.0,
    }
    base.update(overrides)
    return Settings(**base)


# --- F-016: the bundled synthetic sample corpus -------------------------------


def test_production_refuses_the_bundled_sample_with_a_billable_provider() -> None:
    problems = _validate_corpus(prod(nctb_corpus_dir=None))
    assert problems, "a billable production tutor must not default to the sample corpus"
    assert "NCTB_CORPUS_DIR" in problems[0]
    assert "ALLOW_BUNDLED_SAMPLE_CORPUS_IN_PRODUCTION" in problems[0]
    # An empty string is the documented compose default and must behave the
    # same as unset.
    assert _validate_corpus(prod(nctb_corpus_dir="  "))


def test_the_opt_in_allows_a_deliberate_offline_demo() -> None:
    assert not _validate_corpus(
        prod(nctb_corpus_dir=None, allow_bundled_sample_corpus_in_production=True)
    )


def test_mock_production_demo_keeps_the_bundled_sample(monkeypatch) -> None:
    """The mock provider serves no real answer and bills nothing (see module doc)."""
    monkeypatch.setenv("ALLOW_MOCK_LLM_IN_PRODUCTION", "true")
    assert not _validate_corpus(prod(llm_provider="mock", nctb_corpus_dir=None))


def test_configured_corpus_dir_satisfies_the_validator() -> None:
    assert not _validate_corpus(prod())


def test_enforce_production_safety_names_the_corpus_problem(monkeypatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    with pytest.raises(RuntimeError, match="NCTB_CORPUS_DIR"):
        enforce_production_safety(prod(nctb_corpus_dir=None, database_url="sqlite:////data/app.db"))
    # The full production fixture passes the battery unchanged.
    enforce_production_safety(
        prod(database_url="sqlite:////data/app.db", rate_limit_backend="memory")
    )


def test_configured_but_empty_corpus_dir_is_refused_at_boot(tmp_path) -> None:
    """The second door: a configured directory that yields no usable chunks."""
    empty_dir = tmp_path / "empty-corpus"
    empty_dir.mkdir()
    settings = prod(
        nctb_corpus_dir=str(empty_dir),
        database_url=f"sqlite:///{(tmp_path / 'dep.db').as_posix()}",
    )
    with pytest.raises(RuntimeError, match="bundled"):
        # The guard fires before the index is built or any DB is touched; the
        # provider is a stand-in object because only its presence matters here.
        build_dependencies(
            settings,
            caching.build_cache(settings),
            provider=object(),  # type: ignore[arg-type]
            fast_provider=None,
            circuit_breaker=None,
            fallback_provider=None,
        )
