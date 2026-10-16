"""S-005: a password change invalidates pending password-reset tokens.

``change_password()`` set the new hash, cleared ``must_change_password`` and
rotated the token epoch, but left every pending ``password_resets`` row with
``used_at IS NULL``. Whoever held a reset link kept a working password-reset
path for up to the full TTL AFTER the victim rotated the password to contain
the incident. These tests pin the invalidation and that it is scoped:
tokens requested after the change still work.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import PasswordReset
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/reset-invalidation.db",
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _register_student(client: TestClient, email: str = "kid@example.test") -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


def _login_headers(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _capture_reset_token(client: TestClient, email: str, caplog) -> str:
    with caplog.at_level(logging.INFO):
        response = client.post("/auth/forgot", json={"email": email})
    assert response.status_code == 202
    for record in reversed(caplog.records):
        try:
            payload = json.loads(record.getMessage())
        except ValueError:
            continue
        if payload.get("event") == "password_reset_token_console":
            token = payload["token"]
            caplog.clear()
            return token
    raise AssertionError("console reset token was not logged in non-production")


def test_change_password_kills_a_pending_reset_token(client, tmp_path, caplog) -> None:
    _register_student(client)
    headers = _login_headers(client, "kid@example.test")
    token = _capture_reset_token(client, "kid@example.test", caplog)

    changed = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "rotated-pass-11"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text

    stale = client.post("/auth/reset", json={"token": token, "new_password": "attacker-pass-99"})
    assert stale.status_code == 400, stale.text

    # The token row really was marked used in the same transaction ...
    with make_session_factory(
        make_engine(Settings(database_url=f"sqlite:///{tmp_path}/reset-invalidation.db"))
    )() as db:
        rows = db.execute(select(PasswordReset)).scalars().all()
    assert rows, "the /auth/forgot call must have persisted a reset row"
    assert all(row.used_at is not None for row in rows)

    # ... and the attacker's password never took effect.
    assert (
        client.post(
            "/auth/login", json={"email": "kid@example.test", "password": "attacker-pass-99"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": "kid@example.test", "password": "rotated-pass-11"}
        ).status_code
        == 200
    )


def test_resets_requested_after_the_change_still_work(client, caplog) -> None:
    _register_student(client)
    headers = _login_headers(client, "kid@example.test")
    _capture_reset_token(client, "kid@example.test", caplog)
    assert (
        client.post(
            "/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "rotated-pass-11"},
            headers=headers,
        ).status_code
        == 200
    )

    fresh = _capture_reset_token(client, "kid@example.test", caplog)
    res = client.post("/auth/reset", json={"token": fresh, "new_password": "final-pass-42"})
    assert res.status_code == 200, res.text
    assert (
        client.post(
            "/auth/login", json={"email": "kid@example.test", "password": "final-pass-42"}
        ).status_code
        == 200
    )
