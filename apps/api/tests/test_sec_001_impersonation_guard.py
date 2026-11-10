"""SEC-001: a support session must not be able to create durable guardian
access to a child's record.

Proven before this file existed: an impersonated student token could
``POST /students/me/invite-code`` and hand an attacker-controlled parent a
live code, and redeeming it writes a ``ParentStudentLink`` for which no
unlink endpoint exists anywhere -- a permanent adult-to-child grant made
inside a 15-minute read-shaped support session. The same session could also
rewrite the child's consent evidence (``consent_at`` / ``consent_ip``) and
destroy the only revocation path (``DELETE /students/me/invite-code/{id}``),
so the child could not undo any of it afterwards.

The refusal is the established support-session guard shape (403
``{"detail": {"code": "impersonation_forbidden", ...}}``) raised by
``routers/deps.py::forbid_impersonation``.

Every refusal case below is paired with an ordinary-token positive control
asserting the same endpoint still works for the account owner, so this file
cannot go green by breaking the feature it protects.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import ParentInvite, ParentStudentLink, Student
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
FORBIDDEN_CODE = "impersonation_forbidden"
FORBIDDEN_MESSAGE = (
    "This action is not available while impersonating a user; exit impersonation first"
)


@pytest.fixture
def pair(tmp_path):
    """Client + session factory over the same store (assert rows directly)."""
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "sec001"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory


def _register(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _impersonate(client: TestClient, user_id: int) -> dict:
    """Mint a support-session token for ``user_id`` (admin-side route)."""
    res = client.post(
        f"/admin/users/{user_id}/impersonate",
        json={"reason": "support: reproduce the reported bug"},
        headers=_login(client, "root@example.com"),
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _assert_impersonation_forbidden(res) -> None:  # type: ignore[no-untyped-def]
    assert res.status_code == 403, res.text
    detail = res.json()["detail"]
    assert detail["code"] == FORBIDDEN_CODE, res.text
    assert detail["message"] == FORBIDDEN_MESSAGE, res.text


def _invite_rows(factory, student_id: int) -> list:  # type: ignore[no-untyped-def]
    """(id, used_at) of every invite owned by this student -- read back
    through a second session so an uncommitted row cannot masquerade as
    persisted state."""
    with factory() as session:
        return list(
            session.execute(
                select(ParentInvite.id, ParentInvite.used_at).where(
                    ParentInvite.student_id == student_id
                )
            ).all()
        )


def _link_rows(factory, parent_id: int) -> list:  # type: ignore[no-untyped-def]
    with factory() as session:
        return list(
            session.execute(
                select(ParentStudentLink.id).where(ParentStudentLink.parent_id == parent_id)
            ).all()
        )


def test_impersonated_student_cannot_mint_a_guardian_invite(pair) -> None:
    client, factory = pair
    kid = _register(client, "kid@example.com")
    imp = _impersonate(client, kid["user_id"])
    # the support session really is a working session for READS
    assert client.get("/users/me", headers=imp).status_code == 200

    _assert_impersonation_forbidden(client.post("/students/me/invite-code", headers=imp))
    # no code was issued, so no stranger can be handed access to the child
    assert _invite_rows(factory, kid["profile_id"]) == []

    # positive control: the account owner still mints codes, same shape
    created = client.post("/students/me/invite-code", headers=_login(client, "kid@example.com"))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"].startswith("BGPT-")
    assert body["expires_in_minutes"] > 0
    rows = _invite_rows(factory, kid["profile_id"])
    assert [row.id for row in rows] == [body["id"]]
    assert rows[0].used_at is None


def test_impersonated_student_cannot_destroy_the_revocation_path(pair) -> None:
    client, factory = pair
    kid = _register(client, "kid@example.com")
    _register(client, "mom@example.com", role="parent")
    kid_h = _login(client, "kid@example.com")
    first = client.post("/students/me/invite-code", headers=kid_h).json()

    imp = _impersonate(client, kid["user_id"])
    _assert_impersonation_forbidden(
        client.delete(f"/students/me/invite-code/{first['id']}", headers=imp)
    )
    rows = _invite_rows(factory, kid["profile_id"])
    assert [row.id for row in rows] == [first["id"]]
    assert rows[0].used_at is None, "the refused revoke must not half-apply"
    # ...and the code is still redeemable end to end
    redeemed = client.post(
        "/parents/link/invite",
        json={"code": first["code"]},
        headers=_login(client, "mom@example.com"),
    )
    assert redeemed.status_code == 201, redeemed.text

    # positive control: the owner's own revoke still lands
    second = client.post("/students/me/invite-code", headers=kid_h).json()
    revoked = client.delete(f"/students/me/invite-code/{second['id']}", headers=kid_h)
    assert revoked.status_code == 204, revoked.text
    dead = {row.id: row.used_at for row in _invite_rows(factory, kid["profile_id"])}
    assert dead[second["id"]] is not None


def test_impersonated_parent_cannot_redeem_a_live_code(pair) -> None:
    client, factory = pair
    kid = _register(client, "kid@example.com")
    mom = _register(client, "mom@example.com", role="parent")
    code = client.post(
        "/students/me/invite-code", headers=_login(client, "kid@example.com")
    ).json()["code"]

    imp = _impersonate(client, mom["user_id"])
    _assert_impersonation_forbidden(
        client.post("/parents/link/invite", json={"code": code}, headers=imp)
    )
    # no durable grant onto the child's record
    assert _link_rows(factory, mom["profile_id"]) == []
    # and the refusal did not silently burn the code on its way out
    assert _invite_rows(factory, kid["profile_id"])[0].used_at is None

    # positive control: an ordinary parent redeems the same code
    redeemed = client.post(
        "/parents/link/invite",
        json={"code": code},
        headers=_login(client, "mom@example.com"),
    )
    assert redeemed.status_code == 201, redeemed.text
    assert len(_link_rows(factory, mom["profile_id"])) == 1

    # defence in depth: the legacy direct-ID route refuses BEFORE its own
    # 410/404 answer, i.e. the guard is the handler's first statement
    legacy = client.post("/parents/link", json={"student_id": kid["profile_id"]}, headers=imp)
    _assert_impersonation_forbidden(legacy)


def test_impersonated_session_cannot_rewrite_consent_evidence(pair) -> None:
    client, factory = pair
    kid = _register(client, "kid@example.com")
    stale_at = datetime(2026, 7, 1, 12, 0, 0)
    with factory() as session:
        student = session.get(Student, kid["profile_id"])
        student.consent_version = "2026-07-v1"
        student.consent_at = stale_at
        session.commit()
        student_id = student.id

    imp = _impersonate(client, kid["user_id"])
    _assert_impersonation_forbidden(
        client.post(
            f"/students/{student_id}/consent/reconfirm",
            json={"accepted": True},
            headers=imp,
        )
    )
    with factory() as session:
        row = session.get(Student, student_id)
        assert row.consent_at == stale_at, "consent evidence was rewritten by a support session"
        assert row.consent_version == "2026-07-v1"

    # positive control: the student's own re-confirmation still updates it
    accepted = client.post(
        f"/students/{student_id}/consent/reconfirm",
        json={"accepted": True},
        headers=_login(client, "kid@example.com"),
    )
    assert accepted.status_code == 200, accepted.text
    with factory() as session:
        row = session.get(Student, student_id)
        assert row.consent_version != "2026-07-v1"
        assert row.consent_at != stale_at
