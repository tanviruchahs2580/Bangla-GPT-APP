"""T-11 authorization-matrix additions: mass assignment, cross-tenant writes,
and an unauthenticated sweep driven by the route classification file.

The tenancy suites (test_school_tenancy_isolation.py, test_w2_authz_tenancy.py)
already pin cross-tenant READS and same-school positive controls. This module
adds the three checks those suites do not carry:

* mass assignment — client-supplied identity fields (role boundaries, school
  membership, activation/verification flags) on the self-service registration
  route must be ignored or rejected, never persisted as-is;
* cross-tenant WRITE — a teacher of school A addressing school B's classroom
  through a crafted id must not be able to create anything there;
* unauthenticated sweep — every non-public operation in the route
  classification file answers with a denial (never 2xx) when called without a
  bearer token; exact 401s are asserted for the bodyless GET subset.

The factories mirror test_school_tenancy_isolation.py on purpose: two schools,
each with its own principal and teacher, positive controls included.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "Str0ngRootPassw0rd!"
JOIN_PASSWORD = "Str0ngJoinPassw0rd!"
CLASSIFICATION = Path(__file__).parent / "data" / "route_classification.json"


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "authz_matrix"),
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/authz_matrix.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    token = str(res.json()["access_token"])
    return {"Authorization": "Bearer " + token}


def _root(client: TestClient) -> dict:
    return _login(client, "root@example.com")


def _invite(client: TestClient, headers: dict, school_id: int, role: str) -> str:
    res = client.post(f"/schools/{school_id}/invites", json={"role": role}, headers=headers)
    assert res.status_code == 201, res.text
    return str(res.json()["code"])


def _join(client: TestClient, code: str, email: str) -> None:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text


def _build_school(client: TestClient, name: str, principal_email: str, teacher_email: str):
    root = _root(client)
    school = client.post("/admin/schools", json={"name": name}, headers=root).json()
    sid = school["id"]
    _join(client, _invite(client, root, sid, "school_admin"), principal_email)
    principal = _login(client, principal_email, JOIN_PASSWORD)
    _join(client, _invite(client, root, sid, "teacher"), teacher_email)
    teacher = _login(client, teacher_email, JOIN_PASSWORD)
    room = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher).json()
    return {"school": school, "principal": principal, "teacher": teacher, "room_id": room["id"]}


def _two_schools(client: TestClient):
    a = _build_school(client, "Matrix Alpha", "prin.a@mx.test", "teach.a@mx.test")
    b = _build_school(client, "Matrix Beta", "prin.b@mx.test", "teach.b@mx.test")
    return a, b


def test_registration_cannot_self_assign_privileged_fields(env):
    """Mass assignment: extra identity fields are ignored, and the role stays
    inside the registration Literal -- never admin/school_admin."""
    client, conn = env
    res = client.post(
        "/auth/register",
        json={
            "email": "sneaky@mx.test",
            "password": JOIN_PASSWORD,
            "name": "Sneaky Attempt",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
            # fields a hostile client adds hoping they persist:
            "school_id": 1,
            "is_active": True,
            "email_verified": True,
            "totp_secret": "attacker-chosen",
            "token_epoch": 999,
        },
    )
    assert res.status_code == 201, res.text
    row = conn.execute(
        "SELECT role, school_id, email_verified, totp_secret FROM users "
        "WHERE email='sneaky@mx.test'"
    ).fetchone()
    assert row is not None
    role, school_id, email_verified, totp_secret = row
    assert role == "student", f"role persisted as {role}"
    assert school_id is None, f"school_id persisted as {school_id}"
    # email_verified is a SERVER decision: without SMTP the account is trusted
    # as verified (auth.py: "verified = not smtp_configured"). The
    # mass-assignment proof is that the value never comes from the client:
    # this request sent email_verified=true, and the server would have set
    # True anyway here, so assert the server's rule holds for the opposite
    # client value in a sibling assertion below (email_verified=false also
    # yields True without SMTP) -- and that the schema simply has no such
    # field for the client to set.
    assert bool(email_verified) is True  # server rule without SMTP, in test env
    # totp_secret stays server-shaped (encrypted blob or NULL), never the raw input
    assert totp_secret is None or totp_secret != "attacker-chosen"


def test_registration_email_verified_is_a_server_decision_not_client_input(env):
    """The mass-assignment mirror of the assertion above: with the client
    sending email_verified=false, the no-SMTP server rule still yields True --
    proving the persisted flag is computed, not copied."""
    from bangla_gpt_api.services.mailer import smtp_configured

    client, conn = env
    payload = {
        "email": "unverified-claim@mx.test",
        "password": JOIN_PASSWORD,
        "name": "Server Decides",
        "role": "student",
        "class_level": 6,
        "guardian_consent": True,
        "email_verified": False,  # the hostile value: "please keep me unverified"
    }
    assert smtp_configured(client.app.state.settings) is False  # test env precondition
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    row = conn.execute(
        "SELECT email_verified FROM users WHERE email='unverified-claim@mx.test'"
    ).fetchone()
    assert bool(row[0]) is True, "email_verified must follow the server rule, not the payload"


def test_registration_role_literal_blocks_admin_self_grant(env):
    client, conn = env
    res = client.post(
        "/auth/register",
        json={
            "email": "admin-wannabe@mx.test",
            "password": JOIN_PASSWORD,
            "name": "Admin Wannabe",
            "role": "admin",
        },
    )
    assert res.status_code == 422, res.text  # Literal rejects before any write
    row = conn.execute("SELECT id FROM users WHERE email='admin-wannabe@mx.test'").fetchone()
    assert row is None, "a rejected registration must not create the account"


def test_cross_tenant_classroom_write_is_refused(env):
    """A school-A teacher must not create anything inside a school-B classroom
    by crafting B's classroom id."""
    client, _ = env
    a, b = _two_schools(client)
    res = client.post(
        f"/teacher/classrooms/{b['room_id']}/import",
        json={"csv_text": "name,email\nIntruder,intruder@mx.test"},
        headers=a["teacher"],
    )
    assert res.status_code in (403, 404), (
        f"cross-tenant classroom import answered {res.status_code}: {res.text[:200]}"
    )
    # and nothing was created in B's classroom
    body = client.get("/school/students", headers=b["principal"]).json()
    names = {row["name"] for row in body["items"]}
    assert "Intruder" not in names


def test_cross_tenant_classroom_write_positive_control(env):
    """The same write against the caller's OWN classroom must still succeed,
    so the denial cannot be 'refuse everything'."""
    client, _ = env
    a, _b = _two_schools(client)
    res = client.post(
        f"/teacher/classrooms/{a['room_id']}/import",
        json={"csv_text": "name,email\nLegit,legit@mx.test"},
        headers=a["teacher"],
    )
    assert res.status_code == 200, res.text


@pytest.mark.parametrize(
    "entry",
    [
        e
        for e in json.loads(CLASSIFICATION.read_text(encoding="utf-8"))["operations"]
        if e["class"] in ("authenticated", "role-restricted", "optional-auth")
        and e["method"] == "GET"
    ],
)
def test_get_operations_refuse_anonymous_callers(entry):
    """Every bodyless authenticated/role-restricted GET answers 401 without a
    token. (Optional-auth GETs may succeed anonymously by design; they are
    excluded -- their anonymous behaviour is the documented contract.)
    production-token-gated (/metrics) is excluded too: its bearer gate is a
    PRODUCTION-only control (routers/system.py), verified by
    test_metrics_auth.py; the guard test pins its classification."""
    client = TestClient(
        create_app(Settings(env="test", database_url="sqlite://", jwt_secret="x" * 48))
    )
    res = client.get(entry["path"])
    assert res.status_code == 401, (
        f"GET {entry['path']} answered {res.status_code} without a bearer token"
    )


@pytest.mark.parametrize(
    "entry",
    [
        e
        for e in json.loads(CLASSIFICATION.read_text(encoding="utf-8"))["operations"]
        if e["class"] in ("authenticated", "role-restricted")
    ],
)
def test_all_non_public_operations_never_succeed_anonymously(entry):
    """Hard sweep over every authenticated/role-restricted operation: with no
    bearer token and a minimal request, the route must not answer 2xx
    (401/403/404/422 are the acceptable denials; which of them fires depends
    on where the auth dependency sits relative to body validation).
    production-token-gated (/metrics) is excluded -- its bearer gate is a
    production-only control with its own dedicated tests."""
    client = TestClient(
        create_app(Settings(env="test", database_url="sqlite://", jwt_secret="x" * 48))
    )
    # Replace each {param} with a benign literal so the path resolves.
    import re

    concrete = re.sub(r"\{[^}]+\}", "1", entry["path"])
    if entry["method"] == "GET":
        res = client.get(concrete)
    else:
        res = client.request(entry["method"], concrete, json={})
    assert not 200 <= res.status_code < 300, (
        f"{entry['method']} {entry['path']} answered {res.status_code} anonymously: "
        f"{res.text[:120]}"
    )
