"""SEC-002: privileged audit rows written inside a support session must say so.

Proven before this file existed: the ``data_export`` row produced by an
impersonated admin's ``GET /users/me/export`` was byte-identical to a genuine
self-export (``actor_user_id`` = the student, ``actor_role`` = student,
``detail`` = ``{"format": "json"}``). Only the impersonation start/stop rows
named the admin, so an incident review reading the trail could not tell a
child's self-export from an admin downloading that child's data.

The fix carries the fact on the row: the actor stays the impersonated
account (that is whose data was touched) and ``detail`` gains
``impersonated: true`` plus ``imp_by`` (the admin's user id). ``detail``
stays ids-only -- no message content, no PII.

The positive control locks the other direction: an ordinary request's row is
EXACTLY what it was before, so an impersonation marker can never leak into a
genuine user action (``tests/test_delete_cascade_v2.py`` asserts the same
for ``account_erase``).

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AuditLog, User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def pair(tmp_path):
    """Client + session factory over the same store (assert rows directly)."""
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "sec002"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory


def _register(client: TestClient, email: str) -> dict:
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
    return res.json()


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _impersonate(client: TestClient, user_id: int) -> dict:
    res = client.post(
        f"/admin/users/{user_id}/impersonate",
        json={"reason": "support: reproduce the reported bug"},
        headers=_login(client, "root@example.com"),
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _user_id(factory, email: str) -> int:  # type: ignore[no-untyped-def]
    with factory() as session:
        return int(session.execute(select(User.id).where(User.email == email)).scalar_one())


def _data_export_rows(factory) -> list:  # type: ignore[no-untyped-def]
    """(actor_user_id, actor_role, target, detail) for every data_export row,
    oldest first -- read through a second session (committed state only)."""
    with factory() as session:
        return list(
            session.execute(
                select(
                    AuditLog.actor_user_id,
                    AuditLog.actor_role,
                    AuditLog.target,
                    AuditLog.detail,
                )
                .where(AuditLog.action == "data_export")
                .order_by(AuditLog.id)
            ).all()
        )


def test_impersonated_export_row_names_the_account_and_the_admin(pair) -> None:
    client, factory = pair
    kid = _register(client, "kid@example.com")
    admin_id = _user_id(factory, "root@example.com")

    imp = _impersonate(client, kid["user_id"])
    exported = client.get("/users/me/export", headers=imp)
    assert exported.status_code == 200, exported.text

    rows = _data_export_rows(factory)
    assert len(rows) == 1, "exactly one export happened"
    row = rows[0]
    # attribution stays the impersonated account: that is whose data moved
    assert row.actor_user_id == kid["user_id"]
    assert row.actor_role == "student"
    assert row.target == f"user:{kid['user_id']}"
    # ...and the row now names the support session that drove it
    assert row.detail["impersonated"] is True
    assert row.detail["imp_by"] == admin_id
    # ids and outcome metadata only; nothing about the payload itself
    assert set(row.detail) == {"format", "impersonated", "imp_by"}
    assert row.detail["format"] == "json"

    # the operator-visible trail (admin API) says the same thing
    page = client.get("/admin/audit?action=data_export", headers=_login(client, "root@example.com"))
    assert page.status_code == 200, page.text
    assert page.json()["rows"][0]["detail"]["impersonated"] is True


def test_ordinary_export_row_is_byte_identical_to_before(pair) -> None:
    """Positive control + leak check: an impersonated export in the same
    process must not colour the next ordinary request's row."""
    client, factory = pair
    kid_a = _register(client, "a@example.com")
    kid_b = _register(client, "b@example.com")

    assert (
        client.get("/users/me/export", headers=_impersonate(client, kid_a["user_id"])).status_code
        == 200
    )
    assert (
        client.get("/users/me/export", headers=_login(client, "b@example.com")).status_code == 200
    )

    rows = _data_export_rows(factory)
    assert len(rows) == 2
    # the ordinary self-export: exact equality with the pre-change payload
    assert rows[1].actor_user_id == kid_b["user_id"]
    assert rows[1].actor_role == "student"
    assert rows[1].detail == {"format": "json"}
    # the impersonated one carries the marker (no accidental cross-talk)
    assert rows[0].actor_user_id == kid_a["user_id"]
    assert rows[0].detail["impersonated"] is True


def test_a_second_audited_action_inside_the_support_session_is_marked(pair) -> None:
    """The marker rides the request's Session, not the export code path, so
    every ``write_audit`` caller inside a support session carries it. The
    exit row already named the admin (``imp_by``) -- the merge must add the
    fact without changing what the caller wrote."""
    client, factory = pair
    kid = _register(client, "kid@example.com")
    admin_id = _user_id(factory, "root@example.com")
    imp = _impersonate(client, kid["user_id"])

    exited = client.post("/auth/impersonate/exit", headers=imp)
    assert exited.status_code == 204, exited.text

    with factory() as session:
        row = (
            session.execute(
                select(AuditLog)
                .where(AuditLog.action == "impersonation")
                .order_by(AuditLog.id.desc())
            )
            .scalars()
            .first()
        )
    assert row is not None
    assert row.detail["phase"] == "exit"
    assert row.actor_user_id == kid["user_id"], "the row names whose session was touched"
    assert row.detail["impersonated"] is True
    assert row.detail["imp_by"] == admin_id
