"""F-143: the registration email-conflict posture is explicit and configurable.

`POST /auth/register` answering 409 `email_taken` is an unauthenticated
enumeration oracle the sibling credential flows deliberately do not have.
It is also useful signup UX, so the wording was made a deployment setting
rather than silently changed: "disclose" (the default) keeps the documented
409, "generic" answers the same 202 `{"status": "accepted"}` envelope for a
new and a taken address alike. These tests pin both postures, the safe
default first, so a future change to either is deliberate.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _client(tmp_path, policy: str) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, f"enum_{policy}"),
        jwt_secret=SECRET,
        registration_email_conflict=policy,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "শিক্ষক", "role": "teacher"},
    )


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_default_policy_keeps_the_documented_409(tmp_path) -> None:
    """The shipped default must not change signup behaviour: 201 for a new
    address, 409 email_taken for a registered one."""
    client = _client(tmp_path, "disclose")
    first = _register(client, "enum-default@example.com")
    assert first.status_code == 201, first.text
    assert set(first.json()) >= {"user_id", "role", "profile_id"}

    second = _register(client, "enum-default@example.com")
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "email_taken"


def test_generic_policy_answers_identically_for_new_and_taken(tmp_path) -> None:
    """The anti-enumeration posture: the same status and body either way, and
    the taken address silently creates nothing."""
    client = _client(tmp_path, "generic")
    first = _register(client, "enum-generic@example.com")
    assert first.status_code == 202, first.text
    assert first.json() == {"status": "accepted"}
    # The new account was created and is usable.
    assert _login(client, "enum-generic@example.com").status_code == 200

    second = _register(client, "enum-generic@example.com", password="anothersecret9")
    assert second.status_code == 202, second.text
    assert second.json() == first.json()

    # Nothing was overwritten: the first password still signs in and the
    # second password belongs to no account.
    assert _login(client, "enum-generic@example.com").status_code == 200
    assert _login(client, "enum-generic@example.com", "anothersecret9").status_code == 401


def test_generic_policy_still_reports_request_shape_errors(tmp_path) -> None:
    """The generic policy hides address existence, not the request contract:
    a student registration without consent is still the coded 409."""
    client = _client(tmp_path, "generic")
    res = client.post(
        "/auth/register",
        json={
            "email": "enum-student@example.com",
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "class_level": 6,
        },
    )
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == "guardian_consent_required"
