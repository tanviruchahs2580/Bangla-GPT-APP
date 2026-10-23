"""A resent verification code must invalidate the one it replaces.

`send_verification_email` used to insert a new 24-hour code and stop there.
Every code ever mailed for an account stayed redeemable for its full TTL, so
"resend" invalidated nothing: a code seen earlier kept working after the user
asked for a fresh one. `forgot_password` already burned the pending reset tokens
before issuing a new one; this covers the same rule for verification codes.

The fix lives in the shared service, so it holds for every entry point at once
(register, join-school, resend) rather than only for the resend route.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CODE = re.compile(r"\n([A-Za-z0-9_-]{20,})\n")


@pytest.fixture
def mails() -> list[dict]:
    return []


@pytest.fixture
def client(tmp_path, monkeypatch, mails) -> TestClient:
    def fake_send_mail(_settings, *, to, subject, body):  # noqa: ANN001
        mails.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("bangla_gpt_api.services.verification.send_mail", fake_send_mail)
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "resend"),
        jwt_secret=SECRET,
        smtp_enabled=True,
        smtp_host="smtp.example.edu.bd",
        smtp_from="no-reply@example.edu.bd",
    )
    return TestClient(create_app(settings))


def _code(mails: list[dict], index: int) -> str:
    match = CODE.search(mails[index]["body"])
    assert match, f"no code in mail {index}: {mails[index]['body']!r}"
    return match.group(1)


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "যাচাইকারী",
            "role": "teacher",
        },
    )
    assert res.status_code == 201, res.text


def test_resending_invalidates_the_previous_code(client: TestClient, mails: list[dict]) -> None:
    _register(client, "resend@example.com")
    first = _code(mails, 0)

    res = client.post("/auth/resend-verification", json={"email": "resend@example.com"})
    assert res.status_code == 202, res.text
    assert len(mails) == 2
    second = _code(mails, 1)
    assert second != first

    # The superseded code is dead. Before the fix this returned 200 and the
    # account was verified with a code the user had already been told to
    # replace.
    # The body carries the token only (VerifyEmailRequest has no email field).
    stale = client.post("/auth/verify-email", json={"token": first})
    assert stale.status_code == 400, stale.text
    assert stale.json()["detail"]["code"] == "invalid_token"

    fresh = client.post("/auth/verify-email", json={"token": second})
    assert fresh.status_code == 200, fresh.text
    assert (
        client.post(
            "/auth/login",
            json={"email": "resend@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )


def test_redeeming_a_code_twice_still_fails(client: TestClient, mails: list[dict]) -> None:
    """Single-use is unchanged by the invalidation."""
    _register(client, "once@example.com")
    code = _code(mails, 0)
    assert client.post("/auth/verify-email", json={"token": code}).status_code == 200
    assert client.post("/auth/verify-email", json={"token": code}).status_code == 400


def test_a_first_issue_is_not_disturbed_by_the_invalidation(
    client: TestClient, mails: list[dict]
) -> None:
    """Registration issues one code with nothing pending: no-op branch."""
    _register(client, "first@example.com")
    assert len(mails) == 1
    assert client.post("/auth/verify-email", json={"token": _code(mails, 0)}).status_code == 200
