"""AUD-0046: school invite codes are time-limited (expires_at) and fail closed.

Covers: creation stamps a lifetime; valid codes redeem inside the TTL; expired
codes are refused with 410 (and stay unredeemable); pre-column rows with NULL
''expires_at'' fail closed; used codes still report 409.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JOIN_PASSWORD = "joinsecret9"
TTL_MINUTES = 1440


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/inv.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/inv.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _root(client: TestClient) -> dict:
    return _login(client, "root@example.com")


def _create_invite(client: TestClient, role: str = "teacher") -> dict:
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Expiry School"}, headers=root).json()
    res = client.post(
        f"/schools/{school['id']}/invites", json={"role": role}, headers=root
    )
    assert res.status_code == 201, res.text
    return {**res.json(), "school_id": school["id"]}


def _join(client: TestClient, code: str, email: str):
    return client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )


def test_invite_creation_stamps_a_lifetime(env):
    client, conn = env
    invite = _create_invite(client)
    expires_at = datetime.fromisoformat(invite["expires_at"])
    created_at = datetime.fromisoformat(invite["created_at"])
    ttl = (expires_at - created_at) - timedelta(minutes=TTL_MINUTES)
    assert abs(ttl.total_seconds()) < 1.0
    admin = client.get(
        f"/admin/schools/{invite['school_id']}/invites", headers=_root(client)
    ).json()
    assert admin[0]["expires_at"] is not None
    assert admin[0]["id"] == invite["id"]


def test_valid_invite_redeems_inside_ttl(env):
    client, _ = env
    invite = _create_invite(client)
    res = _join(client, invite["code"], "ok@expiry.test")
    assert res.status_code == 201, res.text


def test_expired_invite_refused_and_stays_unredeemable(env):
    client, conn = env
    invite = _create_invite(client)
    conn.execute(
        "UPDATE school_invites SET expires_at = '2020-01-01 00:00:00' WHERE id = ?",
        (invite["id"],),
    )
    conn.commit()
    res = _join(client, invite["code"], "late@expiry.test")
    assert res.status_code == 410, res.text
    assert res.json()["detail"]["code"] == "invite_expired"
    used = conn.execute(
        "SELECT used_at FROM school_invites WHERE id = ?", (invite["id"],)
    ).fetchone()[0]
    assert used is None


def test_legacy_null_expiry_fails_closed(env):
    client, conn = env
    invite = _create_invite(client)
    conn.execute("UPDATE school_invites SET expires_at = NULL WHERE id = ?", (invite["id"],))
    conn.commit()
    res = _join(client, invite["code"], "legacy@expiry.test")
    assert res.status_code == 410, res.text
    assert res.json()["detail"]["code"] == "invite_expired"


def test_used_invite_still_reports_409(env):
    client, _ = env
    invite = _create_invite(client)
    assert _join(client, invite["code"], "first@expiry.test").status_code == 201
    res = _join(client, invite["code"], "reuse@expiry.test")
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == "code_used"


def test_invalid_code_still_404(env):
    client, _ = env
    res = _join(client, "AAAAAAAAAA", "who@expiry.test")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "invalid_code"


def test_expiry_is_strictly_after_bound(env):
    client, conn = env
    invite = _create_invite(client)
    conn.execute(
        "UPDATE school_invites SET expires_at = ? WHERE id = ?",
        (
            (datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1))
            .strftime("%Y-%m-%d %H:%M:%S.%f"),
            invite["id"],
        ),
    )
    conn.commit()
    assert _join(client, invite["code"], "strict@expiry.test").status_code == 410