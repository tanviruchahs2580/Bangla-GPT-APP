"""T-13 / BC-2 characterization: a role change must end existing sessions.

Password change and password reset already rotate the token epoch
(``sessions_invalidated_at``, auth.py) so every pre-rotation access token dies
immediately. A role change did NOT (N-01): a user whose role was demoted kept
a fully-valid 60-minute token. The database-backed role check still denies the
OLD role's routes (``TeacherOrAdminUser`` reads the row, not the claim), but
the stale token itself stayed usable for every other route until natural
expiry -- exactly the window BC-2 closes.

These tests assert the BC-2 target: after ``POST /admin/users/{id}/role``, a
token minted before the change answers 401 ``session_ended`` on the next
request, while the user's fresh login works and the positive control (an
unrelated user's token) is untouched. The role-change handler then rotates the
epoch in the same commit as the audit write.

Red-first: this file failed on the unmodified tree (the pre-change token kept
working) before the fix landed.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "Str0ngRootPassw0rd!"
JOIN_PASSWORD = "Str0ngJoinPassw0rd!"


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "role_revocation"),
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/role_revocation.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


def _root(client: TestClient) -> dict:
    return {"Authorization": "Bearer " + _login(client, "root@example.com")}


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


def test_token_issued_before_a_role_change_is_rejected_afterwards(
    env, monkeypatch: pytest.MonkeyPatch
):
    """The stale token is minted with an iat an hour in the past so it
    deterministically sits before the rotation stamp (integer-second epoch
    comparison; a same-second mint legitimately survives, deps.py)."""
    import time as _time

    from bangla_gpt_api.auth import security as _security

    client, conn = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Rev School"}, headers=root).json()

    _join(client, _invite(client, root, school["id"], "teacher"), "teach@rev.test")

    class _PastClock:
        @staticmethod
        def time() -> float:
            return _time.time() - 3600

    monkeypatch.setattr(_security, "time", _PastClock)
    stale_token = _login(client, "teach@rev.test", JOIN_PASSWORD)
    monkeypatch.setattr(_security, "time", _time)
    stale_headers = {"Authorization": "Bearer " + stale_token}

    # the pre-change token works now (positive control on /users/me)
    assert client.get("/users/me", headers=stale_headers).status_code == 200

    user_id = conn.execute("SELECT id FROM users WHERE email='teach@rev.test'").fetchone()[0]

    # admin demotes the teacher
    res = client.patch(
        f"/admin/users/{user_id}/role",
        json={"role": "student"},
        headers=root,
    )
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "student"

    # BC-2: the pre-change token is dead on the next request
    after = client.get("/users/me", headers=stale_headers)
    assert after.status_code == 401, (
        f"a token minted before the role change still worked ({after.status_code})"
    )
    detail = after.json()["detail"]
    code = detail["code"] if isinstance(detail, dict) else detail
    # the epoch path raises the established code (same as password change/reset)
    assert code == "session_expired", f"expected session_expired, got {code}"

    # and the demoted user can log in fresh (role change is not a lockout)
    fresh_token = _login(client, "teach@rev.test", JOIN_PASSWORD)
    assert (
        client.get("/users/me", headers={"Authorization": "Bearer " + fresh_token}).status_code
        == 200
    )

    # the DB-backed role check also denies the OLD role's routes on a fresh token
    assert (
        client.get(
            "/teacher/classrooms", headers={"Authorization": "Bearer " + fresh_token}
        ).status_code
        == 403
    )


def test_unrelated_users_tokens_survive_someone_elses_role_change(
    env, monkeypatch: pytest.MonkeyPatch
):
    """Epoch rotation is per-account: another user's session is untouched.

    t1's token is minted with an iat an hour in the past (the same technique
    test_session_revocation_v2.py uses) so it deterministically sits before
    the rotation stamp -- the epoch comparison is integer-second and a
    same-second mint legitimately survives (deps.py).
    """
    import time as _time

    from bangla_gpt_api.auth import security as _security

    client, conn = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Rev Two"}, headers=root).json()
    _join(client, _invite(client, root, school["id"], "teacher"), "t1@rev2.test")
    _join(client, _invite(client, root, school["id"], "teacher"), "t2@rev2.test")

    class _PastClock:
        @staticmethod
        def time() -> float:
            return _time.time() - 3600

    monkeypatch.setattr(_security, "time", _PastClock)
    t1 = _login(client, "t1@rev2.test", JOIN_PASSWORD)
    monkeypatch.setattr(_security, "time", _time)
    t2 = _login(client, "t2@rev2.test", JOIN_PASSWORD)

    user_id = conn.execute("SELECT id FROM users WHERE email='t1@rev2.test'").fetchone()[0]
    res = client.patch(f"/admin/users/{user_id}/role", json={"role": "student"}, headers=root)
    assert res.status_code == 200, res.text

    # t1's pre-change token is dead...
    assert client.get("/users/me", headers={"Authorization": "Bearer " + t1}).status_code == 401
    # ...but t2's is not
    assert client.get("/users/me", headers={"Authorization": "Bearer " + t2}).status_code == 200
