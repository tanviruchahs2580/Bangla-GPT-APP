"""PRIV-06: the free-tier data-use acknowledgement gates the production boot.

The audit's remaining PRIV-06 element is owner-side (record the vendor's
data-use terms, F-042); the code side is that the deployment cannot silently
run on a free-tier key whose content may be used to improve the vendor's
products, and that the tier declaration fails closed when misspelled. The
pre-provider PII minimisation the check also verifies is pinned by
tests/test_pii.py (question and history redacted before the prompt is built);
these tests keep the acknowledgement side honest.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import _validate_llm_data_use, enforce_production_safety


def prod(**overrides) -> Settings:
    """Production settings that pass the boot battery unless overridden."""
    base = {
        "env": "production",
        "pii_allow_plaintext": False,
        "jwt_secret": "Zk7Qp2XvN8mR4tYcW1bH6jL3sD9fG5aE0uI2oP7xV4qM8nC6rT1wY3zB5",
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
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
        "rate_limit_backend": "memory",
    }
    base.update(overrides)
    return Settings(**base)


def test_free_tier_production_boot_is_refused_until_acknowledged(monkeypatch) -> None:
    # WEB_CONCURRENCY is read from the OS environment (main._worker_count), not
    # a Settings field: one worker keeps the memory limiter's caveat a warning.
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    with pytest.raises(RuntimeError) as excinfo:
        enforce_production_safety(prod(llm_data_use_tier="free"))
    assert "LLM_DATA_USE_ACKNOWLEDGED" in str(excinfo.value)
    assert "LLM_DATA_USE_TIER=free" in str(excinfo.value)

    # The acknowledgement is the escape hatch, and it only exists together
    # with the tier declaration.
    enforce_production_safety(prod(llm_data_use_tier="free", llm_data_use_acknowledged=True))


def test_the_fallback_provider_counts_too() -> None:
    """A named fallback can serve children's questions, so it is billable too."""
    settings = prod(
        llm_provider="mock",
        gemini_api_key=None,
        llm_fallback_provider="gemini",
        llm_data_use_tier="free",
    )
    assert settings.has_billable_llm_provider
    assert _validate_llm_data_use(settings)


def test_paid_and_unset_tiers_do_not_add_the_problem() -> None:
    assert _validate_llm_data_use(prod(llm_data_use_tier="paid")) == []
    assert _validate_llm_data_use(prod()) == []


def test_the_mock_provider_needs_no_tier_declaration() -> None:
    """The mock bills nothing and is itself refused in production (SEC-02)."""
    assert _validate_llm_data_use(prod(llm_provider="mock", gemini_api_key=None)) == []


def test_a_typo_in_the_tier_is_refused_at_parse_time() -> None:
    """Fail closed: 'Free' must not skip the guard by not matching 'free'."""
    with pytest.raises(ValidationError):
        Settings(llm_data_use_tier="Free")
