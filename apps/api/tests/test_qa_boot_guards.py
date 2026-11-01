"""F-016 / F-034: production boot guards for the corpus and the AI budget.

Both findings are "the safe behaviour is switched off by configuration": the
compose stack ships NCTB_CORPUS_DIR empty (the tutor then answers from the
bundled 78-chunk synthetic sample and cites it as evidence) and the per-user
AI spend cap defaults to 0 = unlimited. The validators are exercised directly,
in the style of tests/test_production_guards.py, plus end-to-end
``enforce_production_safety`` runs and one load-time run of the corpus guard's
second door (a configured directory that yields no usable chunks).

The mock provider is a documented exemption in both guards: it is itself
refused in production unless ALLOW_MOCK_LLM_IN_PRODUCTION is set, it bills
exactly 0 (services.costs.MODEL_COSTS_USD_PER_1K) and it serves no real
answer, so mock-based production demo boot tests keep passing unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bangla_gpt_api import caching
from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.dependencies import build_dependencies
from bangla_gpt_api.main import (
    _validate_ai_budget,
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


# --- F-034: the per-user AI spend cap -----------------------------------------


def test_billable_production_requires_a_budget() -> None:
    problems = _validate_ai_budget(prod(ai_monthly_budget_usd_per_user=0.0))
    assert problems, "a billable production deployment must not run unbounded"
    assert "AI_MONTHLY_BUDGET_USD_PER_USER" in problems[0]
    assert not _validate_ai_budget(prod(ai_monthly_budget_usd_per_user=5.0))


def test_a_named_fallback_provider_also_requires_a_budget() -> None:
    settings = prod(
        llm_provider="mock",
        llm_fallback_provider="gemini",
        ai_monthly_budget_usd_per_user=0.0,
    )
    assert _validate_ai_budget(settings), "the fallback can serve traffic and spend"


def test_enforce_production_safety_names_the_budget_problem(monkeypatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    with pytest.raises(RuntimeError, match="AI_MONTHLY_BUDGET_USD_PER_USER"):
        enforce_production_safety(
            prod(
                database_url="sqlite:////data/app.db",
                ai_monthly_budget_usd_per_user=0.0,
            )
        )


def test_mock_production_demo_needs_no_budget(monkeypatch) -> None:
    """The mock ledger costs exactly 0, so there is no spend to cap."""
    monkeypatch.setenv("ALLOW_MOCK_LLM_IN_PRODUCTION", "true")
    assert not _validate_ai_budget(
        prod(llm_provider="mock", nctb_corpus_dir=None, ai_monthly_budget_usd_per_user=0.0)
    )


def test_the_production_template_ships_a_non_zero_budget() -> None:
    """Documentation half of F-034: the template must not teach 0 = unlimited."""
    text = (Path(__file__).resolve().parents[3] / ".env.production.example").read_text(
        encoding="utf-8"
    )
    match = re.search(r"(?m)^AI_MONTHLY_BUDGET_USD_PER_USER=([0-9.]+)\s*$", text)
    assert match, ".env.production.example must document the budget actively"
    assert float(match.group(1)) > 0
