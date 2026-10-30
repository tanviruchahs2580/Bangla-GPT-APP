"""ANON-06 wave-2 integration test: the email-verification gate end to end.

The gate only exists when SMTP delivery is configured, so the audit could
not drive it: `playwright.config.ts` sets SMTP_HOST='' and no unit test can
assert "the mail really carries a redeemable code" against a mock. This
test runs against a real SMTP server (mailpit) and reads the delivered
message back through its HTTP API:

  docker run -d --name bgpt-w2-mail -p 18025:1025 -p 18080:8025 \
    axllent/mailpit

The test SKIPS (not fails) when mailpit is not reachable, so a developer
without the container still runs the rest of the suite; the skip reason
names the command above. What it proves, in order:

* registration with SMTP configured creates an UNVERIFIED account and the
  sign-in is refused with the coded 403 `email_unverified`;
* the verification mail is actually delivered, addressed to the account,
  and its body carries a code that the API accepts;
* a resend invalidates the previous code and delivers a new one (the
  single-use contract), and the resend surface is rate-limited;
* after verification the account signs in and receives a normal session.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

MAILPIT_API = "http://127.0.0.1:18080"
MAILPIT_SMTP_HOST = "127.0.0.1"
MAILPIT_SMTP_PORT = 18025

#: The scheme is pinned here rather than at each call site: the URL is
#: assembled from this constant plus fixed mailpit paths, never from input.
_ALLOWED_PREFIX = f"{MAILPIT_API}/"

pytestmark = pytest.mark.integration


def _mailpit_get(path: str, *, timeout: float = 5.0) -> dict:
    url = f"{MAILPIT_API}{path}"
    assert url.startswith(_ALLOWED_PREFIX), url
    with urllib.request.urlopen(url, timeout=timeout) as res:  # noqa: S310 - fixed http:// prefix
        body = res.read().decode("utf-8")
    return json.loads(body) if body else {}


def _mailpit_probe() -> str | None:
    """None when mailpit answers, else the reason it did not."""
    try:
        _mailpit_get("/api/v1/info", timeout=2)
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


@pytest.fixture(scope="module")
def mailpit() -> dict:
    reason = _mailpit_probe()
    if reason is not None:
        pytest.skip(
            f"mailpit is not reachable on 127.0.0.1:18080 ({reason}); start it with: "
            "docker run -d --name bgpt-w2-mail -p 18025:1025 -p 18080:8025 axllent/mailpit"
        )
    return {"api": MAILPIT_API}


def _message_ids_for(address: str) -> list[str]:
    query = urllib.parse.quote(f"to:{address}")
    listing = _mailpit_get(f"/api/v1/search?query={query}")
    return [str(item["ID"]) for item in listing.get("messages", [])]


def _wait_for_new_message(address: str, seen: set[str], *, timeout: float = 15.0) -> dict:
    """Wait for a delivery to ``address`` that is not in ``seen``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        fresh = [mid for mid in _message_ids_for(address) if mid not in seen]
        if fresh:
            return _mailpit_get(f"/api/v1/message/{fresh[-1]}")
        time.sleep(0.2)
    pytest.fail(f"no new mail was delivered to {address} within {timeout}s")


def _token_from_message(message: dict) -> str:
    body = message.get("Text") or message.get("HTML") or ""
    match = re.search(r"([A-Za-z0-9_\-]{40,})\s*$", body.strip())
    assert match is not None, f"no verification code found in the mail body: {body!r}"
    return match.group(1)


@pytest.fixture
def client(tmp_path, mailpit) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2email"),
        jwt_secret=SECRET,
        smtp_enabled=True,
        smtp_host=MAILPIT_SMTP_HOST,
        smtp_port=MAILPIT_SMTP_PORT,
        smtp_from="no-reply@bangla-gpt.test",
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Tester",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


def test_unverified_account_is_gated_reads_the_mail_and_verifies(client: TestClient) -> None:
    email = "verify-me@example.test"
    _register(client, email)

    # the gate: with SMTP configured the account starts unverified, and the
    # refusal is the CODED 403 the client branches on (not a generic 401)
    denied = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "email_unverified"

    # the mail really arrived, addressed to this account, and carries a code
    message = _wait_for_new_message(email, set())
    token = _token_from_message(message)
    assert token

    verified = client.post("/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text
    assert verified.json()["access_token"]

    # the gate is open now, and the session works
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    me = client.get(
        "/users/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.status_code == 200 and me.json()["email"] == email


def test_resend_invalidates_the_previous_code_and_is_rate_limited(client: TestClient) -> None:
    email = "resend-me@example.test"
    _register(client, email)
    first = _wait_for_new_message(email, set())
    first_token = _token_from_message(first)

    accepted = client.post("/auth/resend-verification", json={"email": email})
    assert accepted.status_code == 202, accepted.text
    assert accepted.json() == {"status": "accepted"}

    second_token = _token_from_message(_wait_for_new_message(email, {str(first["ID"])}))
    assert second_token != first_token, "a resend must issue a NEW code"

    # verification.py contract: the resend burns the previous code
    stale = client.post("/auth/verify-email", json={"token": first_token})
    assert stale.status_code == 400 and stale.json()["detail"]["code"] == "invalid_token"

    # ... and the freshly mailed one works
    fresh = client.post("/auth/verify-email", json={"token": second_token})
    assert fresh.status_code == 200, fresh.text

    # resend is rate-limited (10/minute per IP by default): a burst of 12
    # must hit the limiter rather than silently dropping every mail
    statuses = [
        client.post("/auth/resend-verification", json={"email": email}).status_code
        for _ in range(12)
    ]
    assert 429 in statuses, f"resend never rate-limited: {statuses}"
    assert statuses[-1] == 429, statuses
