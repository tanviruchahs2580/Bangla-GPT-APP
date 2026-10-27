"""Environment-gate regression tests.

`is_production` decides whether the whole boot guard runs (JWT secret, SMTP,
CORS allowlist, PII key, metrics auth, Redis rate limiting). It used to be an
allow-list of three strings, so any unrecognized value -- a typo, or a real
environment name nobody had thought about -- silently skipped every check and
booted with the insecure default JWT secret.

These tests pin the fail-closed contract: unknown means production.
"""

import pytest

from bangla_gpt_api.config import DEFAULT_JWT_SECRET, NON_PRODUCTION_ENVS, Settings
from bangla_gpt_api.main import enforce_production_safety


def _settings(env: str, tmp_path) -> Settings:
    return Settings(
        env=env,
        database_url=f"sqlite:///{tmp_path}/env-gate.db",
        jwt_secret="x" * 48,
        smtp_enabled=True,
        smtp_host="mail.example.org",
        smtp_from="no-reply@example.org",
        admin_email="admin@example.org",
        admin_password="a-sufficiently-long-password",
        allowed_origins="https://app.example.org",
        pii_enc_key="a-valid-fernet-key",
        metrics_require_auth=True,
        metrics_token="m" * 32,
        rate_limit_backend="redis",
        llm_provider="gemini",
        gemini_api_key="k" * 32,
    )


# Recognized local/CI environments must keep skipping the guard, otherwise the
# test suite and the CI container smoke cannot boot at all.
@pytest.mark.parametrize("env", ["development", "dev", "local", "test", "ci", "preview"])
def test_recognized_non_production_envs_skip_the_guard(env: str, tmp_path) -> None:
    settings = _settings(env, tmp_path)
    assert settings.is_production is False
    enforce_production_safety(settings)  # must not raise


@pytest.mark.parametrize(
    "env",
    [
        "production",
        "prod",
        "staging",
        # Typos and unrecognized names: previously treated as development.
        "prodction",
        "Productionn",
        "live",
        "prod ",
        "PRODUCTION",
    ],
)
def test_unknown_or_misspelled_env_is_treated_as_production(env: str, tmp_path) -> None:
    assert _settings(env, tmp_path).is_production is True


def test_case_and_whitespace_are_normalized() -> None:
    assert Settings(env="  TEST  ").is_production is False
    assert Settings(env=" Production ").is_production is True


def test_typo_in_env_still_refuses_the_insecure_default_secret(tmp_path) -> None:
    """The concrete exploit: a typo booting production with the default secret."""
    settings = _settings("prodction", tmp_path)
    settings.jwt_secret = DEFAULT_JWT_SECRET

    with pytest.raises(RuntimeError) as excinfo:
        enforce_production_safety(settings)

    assert "prodction" in str(excinfo.value), "the error must name the offending ENV"
    # ...and tell the operator which values would legitimately skip the guard.
    assert "development" in str(excinfo.value)


def test_non_production_set_is_not_empty() -> None:
    """Guards against an empty deny-list making every env production."""
    assert NON_PRODUCTION_ENVS
    assert "production" not in NON_PRODUCTION_ENVS
    assert "staging" not in NON_PRODUCTION_ENVS
