"""F-056 / SEC-15: failed logins and armed lockouts leave a structured trace.

The audit probe saw ``/admin/audit?action=login_failed`` return zero rows after
11 failures and no log call existed on the path: the DB counter is reset to 0
by the next successful sign-in, so a brute force against one account was
effectively invisible. WARNING lines now carry ids/counts and, for an unknown
address, a truncated SHA-256 -- never the raw email.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers.auth import _LOGIN_LOCKOUT_BASE_SECONDS, _LOGIN_LOCKOUT_THRESHOLD
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"
EMAIL = "kid@example.test"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "auth-logging"),
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


def _events(caplog, event: str) -> list[dict]:
    out = []
    for record in caplog.records:
        if record.levelno < logging.WARNING:
            continue
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, ValueError):
            continue
        if payload.get("event") == event:
            out.append(payload)
    return out


def test_failed_logins_and_armed_lockout_are_logged(client: TestClient, caplog) -> None:
    caplog.set_level(logging.WARNING)
    _register(client)

    with caplog.at_level(logging.WARNING):
        for expected_count in range(1, _LOGIN_LOCKOUT_THRESHOLD + 1):
            res = client.post("/auth/login", json={"email": EMAIL, "password": "wrong-password"})
            assert res.status_code == 401, res.text
            failures = _events(caplog, "login_failed")
            assert failures[-1]["failed_count"] == expected_count
            assert failures[-1]["reason"] == "bad_credentials"
            assert isinstance(failures[-1]["user_id"], int)

    failures = _events(caplog, "login_failed")
    assert len(failures) == _LOGIN_LOCKOUT_THRESHOLD

    locked = _events(caplog, "account_locked")
    assert len(locked) == 1, "crossing the threshold must emit exactly one lock line"
    assert locked[0]["failed_count"] == _LOGIN_LOCKOUT_THRESHOLD
    assert locked[0]["lock_seconds"] >= _LOGIN_LOCKOUT_BASE_SECONDS

    # Even the correct password is refused while the lock holds, with a trace.
    res = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert res.status_code == 429, res.text
    refused = _events(caplog, "login_refused_locked")
    assert refused and refused[-1]["retry_after_seconds"] >= 1

    dumped = json.dumps([r.getMessage() for r in caplog.records])
    assert EMAIL not in dumped
    assert PASSWORD not in dumped
    assert "wrong-password" not in dumped


def test_unknown_email_failure_is_logged_as_a_hash(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        res = client.post(
            "/auth/login", json={"email": "ghost@example.test", "password": "whatever"}
        )
    assert res.status_code == 401, res.text

    failures = _events(caplog, "login_failed")
    assert len(failures) == 1
    assert failures[0]["reason"] == "unknown_email"
    assert "user_id" not in failures[0]
    assert len(failures[0]["email_sha256"]) == 16
    dumped = json.dumps([r.getMessage() for r in caplog.records])
    assert "ghost@example.test" not in dumped
