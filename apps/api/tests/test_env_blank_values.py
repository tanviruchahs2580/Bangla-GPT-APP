"""A blank forwarded env var means "unset", not "crash at boot".

docker-compose forwards documented knobs as ``VAR: ${VAR:-}`` — an operator
leaving the key out of ``.env`` hands the container the EMPTY STRING, and
pydantic v2 rejects ``""`` for bool/int/float fields with a raw
ValidationError before any of the readable production guards run: the
container crash-loops with no hint which knob was blank (measured against
pydantic 2.13 with ``PII_ALLOW_PLAINTEXT=``). Deleting the blank key lets
the declared default apply, exactly what "not set" means.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bangla_gpt_api.config import Settings

SECRET = "test-secret-0123456789abcdef0123456789"


def _base() -> dict:
    return {
        "jwt_secret": SECRET,
        "admin_email": "root@example.test",
        "admin_password": "Str0ngAdminPassw0rd!",
    }


def test_blank_bool_value_falls_back_to_the_default():
    settings = Settings(**_base(), pii_allow_plaintext="")
    assert settings.pii_allow_plaintext is True


def test_blank_int_value_falls_back_to_the_default():
    settings = Settings(**_base(), answer_log_retention_days="")
    assert settings.answer_log_retention_days == 730


def test_blank_float_value_falls_back_to_the_default():
    settings = Settings(**_base(), ai_monthly_budget_usd_per_user="")
    assert settings.ai_monthly_budget_usd_per_user == 0


def test_a_real_value_still_parses():
    settings = Settings(**_base(), pii_allow_plaintext="false", password_min_length="15")
    assert settings.pii_allow_plaintext is False
    assert settings.password_min_length == 15


def test_whitespace_only_counts_as_blank():
    settings = Settings(**_base(), metrics_require_auth="  ")
    assert settings.metrics_require_auth is False  # the declared default


def test_an_unparseable_value_still_fails_loudly():
    """The fix must not swallow REAL typos: 'maybe' is a configuration error,
    not an unset knob."""
    with pytest.raises(ValidationError):
        Settings(**_base(), pii_allow_plaintext="maybe")
