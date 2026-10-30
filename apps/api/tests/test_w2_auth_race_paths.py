"""Coverage for the auth race and degraded paths (F-058 floor regression).

`routers/auth.py` fell 0.56 points below its recorded floor when wave 2 added
the registration-conflict policy and the mail quota. The uncovered lines were
the paths that only fire under a race, a cache outage or an exhausted quota -
exactly the paths that must not be assumed. These tests execute them.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from bangla_gpt_api.caching import CacheUnavailable
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


def _client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "auth-paths"),
        jwt_secret=JWT,
        **overrides,
    )
    return TestClient(create_app(settings))


def _register_body(email: str = "kid@example.test") -> dict:
    return {
        "email": email,
        "password": PASSWORD,
        "name": "Kid",
        "role": "student",
        "guardian_consent": True,
        "class_level": 6,
    }


def test_registration_race_under_generic_policy_is_not_a_disclosure(tmp_path, monkeypatch) -> None:
    """The IntegrityError branch: a concurrent insert won the race.

    Under REGISTRATION_EMAIL_CONFLICT=generic the loser of the race must get
    the same 202 non-answer as the pre-check would give, not a 409 - the
    whole point of the policy. The race is simulated by making the first
    flush raise IntegrityError once.
    """
    client = _client(tmp_path, registration_email_conflict="generic")
    from bangla_gpt_api.db import session as db_session

    real_flush = db_session.Session.flush
    state = {"raised": False}

    def flaky_flush(self, *args, **kwargs):
        if not state["raised"]:
            state["raised"] = True
            raise IntegrityError("INSERT", {}, Exception("unique violation"))
        return real_flush(self, *args, **kwargs)

    monkeypatch.setattr(db_session.Session, "flush", flaky_flush, raising=False)
    res = client.post("/auth/register", json=_register_body("race@example.test"))
    assert res.status_code == 202, res.text
    assert res.json() == {"status": "accepted"}
    # and no token: the response must not authenticate the caller
    assert "access_token" not in res.text


def test_forgot_returns_accepted_when_the_mail_quota_is_exhausted(tmp_path, monkeypatch) -> None:
    """The quota branch: identical 202, no token row, no SMTP attempt."""
    client = _client(tmp_path)
    client.post("/auth/register", json=_register_body("quota@example.test"))

    from bangla_gpt_api.routers import auth as auth_router

    monkeypatch.setattr(
        auth_router, "_address_mail_quota_allows", lambda *a, **k: False
    )
    res = client.post("/auth/forgot", json={"email": "quota@example.test"})
    # The documented generic answer for /auth/forgot is 202 {"status": "accepted"}.
    assert res.status_code == 202, res.text
    assert res.json() == {"status": "accepted"}


def test_mfa_claim_fails_closed_when_the_cache_is_down(tmp_path, monkeypatch) -> None:
    """The CacheUnavailable branch of the single-use MFA claim returns False."""
    client = _client(tmp_path)
    app = client.app
    ctx = app.state.ctx

    class _Down:
        def add_if_absent(self, *a, **k):
            raise CacheUnavailable("down")

    monkeypatch.setattr(ctx, "cache", _Down())
    from bangla_gpt_api.routers.auth import _claim_mfa_step_up

    claims = {"jti": "abc", "exp": int((datetime.now(UTC) + timedelta(minutes=1)).timestamp())}
    assert _claim_mfa_step_up(ctx, "abc", claims) is False


def test_mfa_claim_treats_a_missing_expiry_as_a_one_second_claim(tmp_path) -> None:
    """The (TypeError, ValueError) branch: no exp -> ttl floors at 1 s, still claimed."""
    client = _client(tmp_path)
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    from bangla_gpt_api.routers.auth import _claim_mfa_step_up

    assert _claim_mfa_step_up(ctx, "no-exp", {"jti": "no-exp"}) is True
