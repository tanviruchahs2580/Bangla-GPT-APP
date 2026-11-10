"""REL-005: production must not boot with a weakened grounding gate.

AGENTS.md Sec.7 pins the invariant -- IDF-weighted coverage >= 0.5 and
context-assembly top_k = 3 -- but RAG_MIN_COVERAGE and RAG_TOP_K are plain
environment-tunable settings with no validator: RAG_MIN_COVERAGE=0 makes the
coverage comparison in services/tutor.py always true, so the refusal path
(a CORRECT outcome) is switched off, and a larger RAG_TOP_K widens the
evidence pool past the shape the golden eval gated.

The guard refuses both in production, mirrors the ALLOW_MOCK_LLM_IN_PRODUCTION
escape-hatch pattern for a deliberate offline sweep, and leaves every
development lane alone. New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import (
    RAG_MIN_COVERAGE_FLOOR,
    RAG_TOP_K_CEILING,
    _validate_rag_grounding,
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


def test_the_documented_defaults_and_constants_agree() -> None:
    """The guard's numbers are the values config.py ships and the eval gated."""
    defaults = Settings(env="test")
    assert defaults.rag_min_coverage == RAG_MIN_COVERAGE_FLOOR
    assert defaults.rag_top_k == RAG_TOP_K_CEILING
    assert _validate_rag_grounding(prod()) == []


def test_zero_coverage_is_refused_in_production() -> None:
    """RAG_MIN_COVERAGE=0 makes the coverage comparison always true."""
    problems = _validate_rag_grounding(prod(rag_min_coverage=0.0))
    assert problems, "a disabled grounding gate must not boot in production"
    assert "RAG_MIN_COVERAGE" in problems[0]
    assert "ALLOW_WEAK_GROUNDING_IN_PRODUCTION" in problems[0]


def test_coverage_just_below_the_floor_is_refused() -> None:
    assert _validate_rag_grounding(prod(rag_min_coverage=0.49))


def test_widened_top_k_is_refused_in_production() -> None:
    problems = _validate_rag_grounding(prod(rag_top_k=8))
    assert problems, "a wider evidence pool than the eval gated must not boot"
    assert "RAG_TOP_K" in problems[0]
    assert "ALLOW_WEAK_GROUNDING_IN_PRODUCTION" in problems[0]


def test_both_weakening_dials_are_named_at_once() -> None:
    problems = _validate_rag_grounding(prod(rag_min_coverage=0.2, rag_top_k=10))
    assert len(problems) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"rag_min_coverage": 0.5},
        {"rag_min_coverage": 0.9},
        {"rag_top_k": 1},
        {"rag_top_k": 3},
        {"rag_min_coverage": 1.0, "rag_top_k": 1},
    ],
)
def test_an_equal_or_stricter_config_still_boots(overrides) -> None:
    assert _validate_rag_grounding(prod(**overrides)) == []


def test_the_escape_hatch_is_explicit_and_opt_in(monkeypatch) -> None:
    """Mirrors ALLOW_MOCK_LLM_IN_PRODUCTION: never a silent default."""
    monkeypatch.delenv("ALLOW_WEAK_GROUNDING_IN_PRODUCTION", raising=False)
    assert _validate_rag_grounding(prod(rag_min_coverage=0.0, rag_top_k=10))
    monkeypatch.setenv("ALLOW_WEAK_GROUNDING_IN_PRODUCTION", "true")
    assert _validate_rag_grounding(prod(rag_min_coverage=0.0, rag_top_k=10)) == []


def test_enforce_production_safety_names_the_grounding_problem(monkeypatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    with pytest.raises(RuntimeError, match="RAG_MIN_COVERAGE"):
        enforce_production_safety(prod(rag_min_coverage=0.0, database_url="sqlite:////data/app.db"))
    with pytest.raises(RuntimeError, match="RAG_TOP_K"):
        enforce_production_safety(prod(rag_top_k=7, database_url="sqlite:////data/app.db"))
    # the untouched fixture passes the battery unchanged
    enforce_production_safety(
        prod(database_url="sqlite:////data/app.db", rate_limit_backend="memory")
    )


@pytest.mark.parametrize("env", ["development", "dev", "local", "test", "ci", "preview"])
def test_no_development_lane_is_affected(env: str) -> None:
    """Offline sweeps need the knobs; only production refuses them."""
    settings = Settings(env=env, rag_min_coverage=0.0, rag_top_k=99)
    assert settings.is_production is False
    enforce_production_safety(settings)  # must not raise
