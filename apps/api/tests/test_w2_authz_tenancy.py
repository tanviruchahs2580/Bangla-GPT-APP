"""SEC-05/06/07 wave-2 guards: uniform tenancy answers, revocable invites,
session-bound impersonation.

Three findings share this file because they share one root cause: a
security control whose OBSERVABLE effect did not match its documented
effect.

* F-144 -- the tenancy wall answered 403 ``other_school`` for an object
  that exists in another school but 404 for one that does not, i.e. the
  wall also worked as an existence oracle over sequential ids.
* F-145 -- guardian invite codes were neither audited nor revocable: an
  incident review could not reconstruct who attached a guardian to a
  child, and a leaked code stayed redeemable for its whole TTL.
* F-146 -- ``POST /auth/logout`` answered 204 for an impersonation token
  while revoking a DIFFERENT cache namespace, so a "signed out" support
  session kept authenticating; and the impersonated window could change
  the target's credentials.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AuditLog
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def pair(tmp_path):
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2authz"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory


def _register(client: TestClient, email: str, role: str = "student", **extra) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role, **extra}
    if role == "student":
        payload.setdefault("guardian_consent", True)
        payload.setdefault("class_level", 6)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _headers(client: TestClient, email: str) -> dict:
    return {"Authorization": f"Bearer {_login(client, email)}"}


def _admin(client: TestClient) -> dict:
    token = _login(client, "root@example.com")
    return {"Authorization": f"Bearer {token}"}


def _audit_rows(factory, action: str) -> list[AuditLog]:
    with factory() as session:
        return list(session.execute(select(AuditLog).where(AuditLog.action == action)).scalars())


def _two_schools(client: TestClient, factory) -> tuple[dict, dict]:
    """Return each school's teacher headers plus a student id inside A."""
    admin = _admin(client)
    schools = {}
    for label in ("A", "B"):
        created = client.post("/admin/schools", json={"name": f"School {label}"}, headers=admin)
        assert created.status_code in (200, 201), created.text
        schools[label] = created.json()
    teacher_headers = {}
    for label in ("A", "B"):
        invite = client.post(
            f"/schools/{schools[label]['id']}/invites", json={"role": "teacher"}, headers=admin
        )
        assert invite.status_code in (200, 201), invite.text
        join = client.post(
            "/auth/join-school",
            json={
                "invite_code": invite.json()["code"],
                "email": f"t{label.lower()}@school.test",
                "password": PASSWORD,
                "name": f"Teacher {label}",
            },
        )
        assert join.status_code == 201, join.text
        teacher_headers[label] = _headers(client, f"t{label.lower()}@school.test")
    # a student enrolled in school A through the roster import (each import
    # row becomes a student row inside the teacher's school)
    room = client.post(
        "/teacher/classrooms",
        json={"class_level": 6, "section": "GEN"},
        headers=teacher_headers["A"],
    )
    assert room.status_code == 201, room.text
    imported = client.post(
        f"/teacher/classrooms/{room.json()['id']}/import",
        json={"csv_text": "name,email\nPupil A,pupil.a@school.test\n"},
        headers=teacher_headers["A"],
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 1, imported.text
    with factory() as session:
        from bangla_gpt_api.db.models import Student

        student_id = session.execute(
            select(Student.id).where(Student.name == "Pupil A")
        ).scalar_one()
    return {"teacher": teacher_headers, "student_id": int(student_id), "schools": schools}, schools


# --- F-144: the tenancy wall must not be an existence oracle ----------------


def test_cross_tenant_student_read_is_indistinguishable_from_missing(pair) -> None:
    client, factory = pair
    env, _ = _two_schools(client, factory)
    other = env["teacher"]["B"]

    # the student exists, in school A; a school-B teacher asks for it
    cross = client.get(f"/students/{env['student_id']}", headers=other)
    # and asks for an id that was never issued
    missing = client.get("/students/999999", headers=other)

    assert cross.status_code == missing.status_code == 404
    assert cross.json() == missing.json(), (
        "a cross-tenant read must be byte-identical to a missing id (F-144)"
    )
    assert cross.json()["detail"]["code"] == "student_not_found"

    # ... and the attempt is recorded server-side, so support can still see
    # that somebody probed across tenants
    rows = _audit_rows(factory, "cross_tenant_denied")
    assert rows, "the cross-tenant attempt must leave an audit row"
    assert rows[0].target == f"student:{env['student_id']}"
    assert rows[0].detail["actor_school_id"] == env["schools"]["B"]["id"]


def test_own_school_student_read_still_works(pair) -> None:
    """The wall must not be satisfied by refusing everything (F-144)."""
    client, factory = pair
    env, _ = _two_schools(client, factory)
    own = client.get(f"/students/{env['student_id']}", headers=env["teacher"]["A"])
    assert own.status_code == 200, own.text
    assert own.json()["id"] == env["student_id"]


def test_cross_tenant_classroom_read_is_indistinguishable_from_missing(pair) -> None:
    client, factory = pair
    env, _ = _two_schools(client, factory)
    other = env["teacher"]["B"]
    with factory() as session:
        from bangla_gpt_api.db.models import ClassRoom

        room_id = int(session.execute(select(ClassRoom.id)).scalar_one())

    cross = client.get(f"/teacher/classrooms/{room_id}/roster", headers=other)
    missing = client.get("/teacher/classrooms/999999/roster", headers=other)
    assert cross.status_code == missing.status_code == 404
    assert cross.json() == missing.json()
    assert cross.json()["detail"]["code"] == "classroom_not_found"


# --- F-145: guardian invites are audited and revocable ---------------------


def test_invite_code_is_64_bit_and_audited_and_revocable(pair) -> None:
    client, factory = pair
    student = _register(client, "kid@example.com")
    kid = _headers(client, "kid@example.com")
    parent = _register(client, "mom@example.com", role="parent")
    parent_headers = _headers(client, "mom@example.com")

    created = client.post("/students/me/invite-code", headers=kid)
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    # entropy: 8 random bytes (64 bits) rendered as 16 hex chars
    prefix, _, body = code.partition("-")
    assert prefix == "BGPT" and len(body) == 16
    assert all(c in "0123456789ABCDEF" for c in body)

    # the CREATE is audited (hash only, never the code)
    rows = [
        r for r in _audit_rows(factory, "parent_link") if r.detail.get("phase") == "invite_created"
    ]
    assert len(rows) == 1
    assert rows[0].target == f"student:{student['profile_id']}"
    assert code not in str(rows[0].detail), "an audit row must never carry the code"

    # revocation kills it immediately: redemption now fails
    invite_id = _invite_id(factory, student["profile_id"])
    revoked = client.delete(f"/students/me/invite-code/{invite_id}", headers=kid)
    assert revoked.status_code == 204, revoked.text
    refused = client.post("/parents/link/invite", json={"code": code}, headers=parent_headers)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"]["code"] == "invalid_invite"
    assert [
        r for r in _audit_rows(factory, "parent_link") if r.detail.get("phase") == "invite_revoked"
    ]

    # and a successful redemption is audited as `linked` (create + redeem
    # both reconstructable in an incident review)
    second = client.post("/students/me/invite-code", headers=kid).json()["code"]
    linked = client.post("/parents/link/invite", json={"code": second}, headers=parent_headers)
    assert linked.status_code == 201, linked.text
    linked_rows = [
        r for r in _audit_rows(factory, "parent_link") if r.detail.get("phase") == "linked"
    ]
    assert len(linked_rows) == 1
    assert linked_rows[0].actor_user_id == parent["user_id"]


def test_another_student_cannot_revoke_your_invite(pair) -> None:
    client, factory = pair
    owner = _register(client, "owner@example.com")
    _register(client, "other@example.com")
    other = _headers(client, "other@example.com")
    client.post("/students/me/invite-code", headers=_headers(client, "owner@example.com"))
    invite_id = _invite_id(factory, owner["profile_id"])

    # same 404 whether it is someone else's invite or a nonexistent id
    foreign = client.delete(f"/students/me/invite-code/{invite_id}", headers=other)
    missing = client.delete("/students/me/invite-code/999999", headers=other)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()

    # the owner's code is still live
    again = client.post("/students/me/invite-code", headers=_headers(client, "owner@example.com"))
    assert again.status_code == 201


def _invite_id(factory, student_id: int) -> int:
    from bangla_gpt_api.db.models import ParentInvite

    with factory() as session:
        return int(
            session.execute(select(ParentInvite.id).where(ParentInvite.student_id == student_id))
            .scalars()
            .first()
        )


# --- F-146: impersonation cannot outlive or exceed its session -------------


def _start_impersonation(client: TestClient, admin_token: str, user_id: int) -> str:
    res = client.post(
        f"/admin/users/{user_id}/impersonate",
        json={"reason": "support: reproduce the reported bug"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_logout_revokes_an_impersonation_token(pair) -> None:
    client, _ = pair
    admin_token = _login(client, "root@example.com")
    student = _register(client, "imp@example.com")
    imp_token = _start_impersonation(client, admin_token, student["user_id"])
    imp_headers = {"Authorization": f"Bearer {imp_token}"}
    assert client.get("/users/me", headers=imp_headers).status_code == 200

    # the impersonated user's own sign-out must really end the session
    assert client.post("/auth/logout", headers=imp_headers).status_code == 204
    refused = client.get("/users/me", headers=imp_headers)
    assert refused.status_code == 401, "F-146: 'signed out' must mean signed out"


def test_impersonation_dies_with_the_admin_session(pair) -> None:
    """The support window is a subset of the admin session that opened it."""
    client, factory = pair
    admin_token = _login(client, "root@example.com")
    student = _register(client, "imp2@example.com", role="teacher")
    imp_token = _start_impersonation(client, admin_token, student["user_id"])
    imp_headers = {"Authorization": f"Bearer {imp_token}"}
    assert client.get("/users/me", headers=imp_headers).status_code == 200

    # the admin signs out (their own session ends)
    assert (
        client.post("/auth/logout", headers={"Authorization": f"Bearer {admin_token}"}).status_code
        == 204
    )
    assert client.get("/users/me", headers=imp_headers).status_code == 401, (
        "an impersonation token must not outlive the admin session that minted it"
    )
    # the implicit end is audited with the count of ended windows
    ends = [
        r for r in _audit_rows(factory, "impersonation") if r.detail.get("phase") == "session_end"
    ]
    assert ends and ends[0].detail["revoked_sessions"] == 1


def test_impersonation_scope_excludes_credential_change_and_destruction(pair) -> None:
    client, _ = pair
    admin_token = _login(client, "root@example.com")
    student = _register(client, "imp3@example.com")
    imp_token = _start_impersonation(client, admin_token, student["user_id"])
    imp_headers = {"Authorization": f"Bearer {imp_token}"}

    refused = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "DifferentPass123"},
        headers=imp_headers,
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "impersonation_forbidden"

    revoked = client.post("/users/me/sessions/revoke", headers=imp_headers)
    assert revoked.status_code == 403
    assert revoked.json()["detail"]["code"] == "impersonation_forbidden"

    deleted = client.request(
        "DELETE", "/users/me", json={"password": PASSWORD}, headers=imp_headers
    )
    assert deleted.status_code == 403
    assert deleted.json()["detail"]["code"] == "impersonation_forbidden"

    # the admin's own credential is untouched by the refusals
    assert (
        client.post(
            "/auth/login", json={"email": "imp3@example.com", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_admin_session_revoke_also_ends_impersonation(pair) -> None:
    client, _ = pair
    admin_token = _login(client, "root@example.com")
    student = _register(client, "imp4@example.com")
    imp_token = _start_impersonation(client, admin_token, student["user_id"])
    imp_headers = {"Authorization": f"Bearer {imp_token}"}

    assert (
        client.post(
            "/users/me/sessions/revoke", headers={"Authorization": f"Bearer {admin_token}"}
        ).status_code
        == 204
    )
    assert client.get("/users/me", headers=imp_headers).status_code == 401


def test_start_and_stop_are_audited_with_context(pair) -> None:
    client, factory = pair
    admin_token = _login(client, "root@example.com")
    student = _register(client, "imp5@example.com")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    _start_impersonation(client, admin_token, student["user_id"])
    assert (
        client.delete(
            f"/admin/users/{student['user_id']}/impersonate", headers=admin_headers
        ).status_code
        == 204
    )

    rows = _audit_rows(factory, "impersonation")
    phases = sorted(r.detail["phase"] for r in rows)
    assert phases == ["start", "stop"]
    start = next(r for r in rows if r.detail["phase"] == "start")
    assert start.target == f"user:{student['user_id']}"
    assert start.detail["reason"].startswith("support:")
    # the start row records WHICH admin session authorised the window, so
    # the two rows can be joined in a review without a schema change
    assert isinstance(start.detail["admin_jti"], str) and start.detail["admin_jti"]
    assert not any("password" in str(r.detail).lower() for r in rows)


def test_impersonation_claims_bind_the_session(pair) -> None:
    """The minted token names the admin session it came from (claim-level)."""
    client, _ = pair
    admin_token = _login(client, "root@example.com")
    admin_claims = pyjwt.decode(
        admin_token,
        SECRET,
        algorithms=["HS256"],
        audience="bangla-gpt-clients",
        issuer="bangla-gpt-api",
    )
    student = _register(client, "imp6@example.com")
    imp_token = _start_impersonation(client, admin_token, student["user_id"])
    claims = pyjwt.decode(
        imp_token,
        SECRET,
        algorithms=["HS256"],
        audience="bangla-gpt-clients",
        issuer="bangla-gpt-api",
    )
    assert claims["imp_session"] == admin_claims["jti"]
