"""S5.6: security hardening -- audit trail, PII encryption, CSP nonce, impersonation.

PASS-WHEN from the roadmap: "audit rows written for all five event types"
(role_change, data_export, purge, qp_finalize, impersonation), plus the
supporting guarantees each mechanism needs to be real: ciphertext at rest
(not just an in-API transform), per-response nonce rotation, admin-only
audit view, and the impersonation guards.
"""

import sqlite3
import time

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app, enforce_production_safety

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
PHONE = "01712345678"

CHAPTER = "\u0995\u09cb\u09b7"  # kosh (cell): sample NCTB class-6 science chapter
DRAFT_BODY = {
    "class_level": 6,
    "subject": "science",
    "chapters": [CHAPTER],
    "exam_type": "Exam 2026",
    "marks": 10,
    "duration_min": 10,
}


def make_client(tmp_path, db_name="sec.db", **overrides) -> tuple[TestClient, Settings]:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/{db_name}",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        **overrides,
    )
    return create_app_client(settings)


def create_app_client(settings: Settings) -> tuple[TestClient, Settings]:
    return TestClient(create_app(settings)), settings


@pytest.fixture
def client(tmp_path) -> TestClient:
    app_client, _ = make_client(tmp_path)
    return app_client


@pytest.fixture
def enc_client(tmp_path) -> TestClient:
    """Client with PII_ENC_KEY configured (production-like encryption)."""
    key = Fernet.generate_key().decode()
    app_client, _ = make_client(tmp_path, db_name="enc.db", pii_enc_key=key)
    return app_client


def _register(client: TestClient, email: str, role: str = "student", **extra) -> dict:
    payload: dict = {
        "email": email,
        "password": PASSWORD,
        "name": "Test User",
        "role": role,
        **extra,
    }
    if role == "student":
        payload.setdefault("guardian_consent", True)
        payload.setdefault("class_level", 6)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _admin(client: TestClient) -> dict:
    return _headers(client, "root@example.com")


def _audit_actions(client: TestClient, action: str | None = None) -> list[dict]:
    params = {"action": action} if action else {}
    res = client.get("/admin/audit", params=params, headers=_admin(client))
    assert res.status_code == 200, res.text
    return res.json()["rows"]


# --- PASS-WHEN: all five sensitive event types produce audit rows ----------


def test_all_five_event_types_write_audit_rows(client: TestClient) -> None:
    admin = _admin(client)
    admin_id = client.get("/users/me", headers=admin).json()["user_id"]

    # 1. role_change
    teacher = _register(client, "t@example.com", role="teacher")
    assert (
        client.patch(
            f"/admin/users/{teacher['user_id']}/role", json={"role": "school_admin"}, headers=admin
        ).status_code
        == 200
    )
    # second change so the trail holds more than one role_change row: the
    # newest-first contract must be observable, not just "a row exists".
    assert (
        client.patch(
            f"/admin/users/{teacher['user_id']}/role", json={"role": "teacher"}, headers=admin
        ).status_code
        == 200
    )

    # 2. data_export
    student = _register(client, "s@example.com")
    export = client.get("/users/me/export", headers=_headers(client, "s@example.com"))
    assert export.status_code == 200

    # 3. purge (retention sweep)
    assert client.post("/admin/maintenance/purge", headers=admin).status_code == 200

    # 4. qp_finalize (draft -> all-accepted review -> FINAL); the paper's author
    # must hold a teacher profile, which admin-only users do not have.
    t_headers = _headers(client, "t@example.com")
    qp = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=t_headers).json()
    decisions = [{"ref": q["ref"], "action": "accept"} for q in qp["questions"]]
    client.post(
        f"/teacher/qpapers/{qp['id']}/review",
        json={"decisions": decisions},
        headers=t_headers,
    )
    fin = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=t_headers)
    assert fin.status_code == 200

    # 5. impersonation (start + stop)
    imp = client.post(
        f"/admin/users/{student['user_id']}/impersonate",
        json={"reason": "support: stuck on login"},
        headers=admin,
    )
    assert imp.status_code == 200, imp.text
    stopped = client.delete(f"/admin/users/{student['user_id']}/impersonate", headers=admin)
    assert stopped.status_code == 204

    page = client.get("/admin/audit", params={"limit": 200}, headers=admin).json()
    actions = {row["action"] for row in page["rows"]}
    assert {"role_change", "data_export", "purge", "qp_finalize", "impersonation"} <= actions

    # newest first, and metadata is precise but never content: role_change
    # carries the from/to pair, actor is the admin who made the call.
    role_rows = _audit_actions(client, action="role_change")
    assert [r["detail"] for r in role_rows] == [
        {"from": "school_admin", "to": "teacher"},
        {"from": "teacher", "to": "school_admin"},
    ]
    assert all(
        r["actor_role"] == "admin"
        and r["actor_user_id"] == admin_id
        and r["target"] == f"user:{teacher['user_id']}"
        for r in role_rows
    )
    # impersonation start + stop are two rows with the same target
    imp_rows = _audit_actions(client, action="impersonation")
    assert [r["detail"]["phase"] for r in imp_rows] == ["stop", "start"]  # newest first
    assert imp_rows[1]["detail"]["reason"] == "support: stuck on login"  # the start row
    assert "reason" not in imp_rows[0]["detail"]  # stop row: no free-text echo
    # qp_finalize points at the paper (ids only, R11)
    fin_row = _audit_actions(client, action="qp_finalize")[0]
    assert fin_row["target"] == f"qp:{qp['id']}"
    assert fin_row["detail"] == {"class_level": 6, "subject": "science"}


# --- admin-only audit view with filtering/pagination -----------------------


def test_audit_view_is_admin_only(client: TestClient) -> None:
    assert client.get("/admin/audit").status_code == 401
    _register(client, "t@example.com", role="teacher")
    assert client.get("/admin/audit", headers=_headers(client, "t@example.com")).status_code == 403


def test_audit_view_filters_and_pages(client: TestClient) -> None:
    admin = _admin(client)
    for i in range(3):
        prof = _register(client, f"u{i}@example.com", role="teacher")
        client.patch(f"/admin/users/{prof['user_id']}/role", json={"role": "admin"}, headers=admin)
    # one more event of a different type so filtering is proven, not assumed
    assert client.post("/admin/maintenance/purge", headers=admin).status_code == 200

    role_rows = _audit_actions(client, action="role_change")
    assert len(role_rows) == 3 and all(r["action"] == "role_change" for r in role_rows)
    purge_rows = _audit_actions(client, action="purge")
    assert len(purge_rows) == 1 and purge_rows[0]["action"] == "purge"

    unfiltered = client.get("/admin/audit", headers=admin).json()
    assert unfiltered["total"] == 4
    all_rows = unfiltered["rows"]
    ids = [r["id"] for r in all_rows]
    assert ids == sorted(ids, reverse=True), "audit view must be newest-first"

    # windowing over the filtered set: offset+limit slices the same ordering
    window = client.get(
        "/admin/audit", params={"action": "role_change", "limit": 2, "offset": 1}, headers=admin
    ).json()
    assert [r["id"] for r in window["rows"]] == [role_rows[1]["id"], role_rows[2]["id"]]
    assert window["total"] == 3 and window["limit"] == 2 and window["offset"] == 1

    # argument bounds are validated, not silently widened
    assert client.get("/admin/audit", params={"limit": 0}, headers=admin).status_code == 422
    assert client.get("/admin/audit", params={"limit": 500}, headers=admin).status_code == 422
    assert client.get("/admin/audit", params={"offset": -1}, headers=admin).status_code == 422


# --- impersonation guards ---------------------------------------------------


def test_impersonation_refuses_admin_and_school_admin_targets(client: TestClient) -> None:
    admin = _admin(client)
    root_id = client.get("/users/me", headers=admin).json()["user_id"]
    res = client.post(
        f"/admin/users/{root_id}/impersonate", json={"reason": "nope nope"}, headers=admin
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "impersonation_forbidden"
    sa = _register(client, "sa@example.com", role="teacher")
    client.patch(f"/admin/users/{sa['user_id']}/role", json={"role": "school_admin"}, headers=admin)
    res2 = client.post(
        f"/admin/users/{sa['user_id']}/impersonate", json={"reason": "nope nope"}, headers=admin
    )
    assert res2.status_code == 403
    # unknown user -> 404; non-admin actor -> 403
    notfound = client.post("/admin/users/9999/impersonate", json={"reason": "x y z"}, headers=admin)
    assert notfound.status_code == 404
    t = _register(client, "t@example.com", role="teacher")
    assert (
        client.post(
            f"/admin/users/{t['user_id']}/impersonate",
            json={"reason": "x y z"},
            headers=_headers(client, "t@example.com"),
        ).status_code
        == 403
    )


def test_impersonated_token_is_short_lived_and_attributable(client: TestClient) -> None:
    admin = _admin(client)
    admin_id = client.get("/users/me", headers=admin).json()["user_id"]
    student = _register(client, "s@example.com")
    res = client.post(
        f"/admin/users/{student['user_id']}/impersonate",
        json={"reason": "password reset call"},
        headers=admin,
    )
    body = res.json()
    assert body["expires_in_min"] == 15 and body["user_id"] == student["user_id"]
    claims = pyjwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(student["user_id"]) and claims["role"] == "student"
    assert claims["imp"] is True and claims["imp_by"] == admin_id
    ttl_min = (claims["exp"] - time.time()) / 60  # exp ~15 min from now (no iat claim)
    assert 14.0 <= ttl_min <= 15.1
    # the token actually works as the student
    me = client.get("/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["role"] == "student"
    # but still not an admin
    imp_headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/admin/audit", headers=imp_headers).status_code == 403
    # audit trail recorded the actor, not just the target
    start = _audit_actions(client, action="impersonation")[0]
    assert start["detail"]["phase"] == "start"
    assert start["actor_user_id"] == admin_id and start["target"] == f"user:{student['user_id']}"


# --- PII encryption for guardian phone --------------------------------------


def test_guardian_phone_encrypted_at_rest_and_roundtrips(enc_client: TestClient, tmp_path) -> None:
    _register(enc_client, "p@example.com", role="parent", phone=PHONE)
    me = enc_client.get("/users/me", headers=_headers(enc_client, "p@example.com"))
    assert me.status_code == 200
    assert me.json()["phone"] == PHONE  # owner sees their own value back
    # raw storage holds fernet: ciphertext -- the digits must not appear
    con = sqlite3.connect(tmp_path / "enc.db")
    stored = con.execute("select phone_enc from parents").fetchone()[0]
    con.close()
    assert stored is not None and stored.startswith("fernet:")
    assert PHONE not in stored and PHONE not in str(_dump_db(tmp_path / "enc.db"))


def test_export_never_leaks_phone_and_logs_data_export(enc_client: TestClient) -> None:
    _register(enc_client, "p@example.com", role="parent", phone=PHONE)
    res = enc_client.get("/users/me/export", headers=_headers(enc_client, "p@example.com"))
    assert res.status_code == 200
    assert PHONE not in res.text  # export is PII-minimal by design (R11)
    rows = _audit_actions(enc_client, action="data_export")
    assert rows and rows[0]["detail"] == {"format": "json"}


def test_phone_passthrough_without_key(client: TestClient) -> None:
    # dev convenience: no PII_ENC_KEY -> plaintext round-trip (no encryption pretend)
    _register(client, "p@example.com", role="parent", phone=PHONE)
    me = client.get("/users/me", headers=_headers(client, "p@example.com"))
    assert me.json()["phone"] == PHONE


def _dump_db(path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("latin-1")


# --- production boot refuses without PII_ENC_KEY ----------------------------


def _prod_settings(**overrides) -> Settings:
    base = {
        "env": "production",
        "database_url": "sqlite:////data/app.db",
        "jwt_secret": "a" * 32,
        "admin_email": "a@b.com",
        "admin_password": "longenough123",
        "allowed_origins": "https://tutor.example.com",
        "llm_provider": "mock",
        "smtp_enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_from": "noreply@example.com",
        # SEC-001: /metrics is never public in production.
        "metrics_require_auth": True,
        "metrics_token": "m" * 32,
    }
    base.update(overrides)
    return Settings(**base)


def test_production_boot_requires_pii_enc_key() -> None:
    with pytest.raises(RuntimeError, match="PII_ENC_KEY"):
        enforce_production_safety(_prod_settings(pii_enc_key=None))
    # and passes once a key is configured
    enforce_production_safety(_prod_settings(pii_enc_key=Fernet.generate_key().decode()))


# --- CSP per-response nonce --------------------------------------------------


def test_csp_nonce_rotates_per_response(client: TestClient) -> None:
    h1 = client.get("/health").headers["content-security-policy"]
    h2 = client.get("/health").headers["content-security-policy"]
    assert "default-src 'self'" in h1 and "frame-ancestors 'none'" in h1
    n1 = h1.split("script-src 'self' 'nonce-")[1].split("'")[0]
    n2 = h2.split("script-src 'self' 'nonce-")[1].split("'")[0]
    assert n1 and n1 != n2
    # documented carve-out: API dev-docs surfaces are exempt
    assert "content-security-policy" not in client.get("/docs").headers


def test_purge_audit_detail_is_counts_only(client: TestClient) -> None:
    admin = _admin(client)
    assert client.post("/admin/maintenance/purge", headers=admin).status_code == 200
    row = _audit_actions(client, action="purge")[0]
    assert row["target"] == "retention_sweep"
    # detail is an aggregate dict of integers/strings -- no message content
    assert isinstance(row["detail"], dict) and all(
        isinstance(v, int | str) for v in row["detail"].values()
    )


def test_qp_finalize_audit_targets_the_paper(client: TestClient) -> None:
    _register(client, "t@example.com", role="teacher")
    t_headers = _headers(client, "t@example.com")
    qp = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=t_headers).json()
    decisions = [{"ref": q["ref"], "action": "accept"} for q in qp["questions"]]
    client.post(
        f"/teacher/qpapers/{qp['id']}/review",
        json={"decisions": decisions},
        headers=t_headers,
    )
    fin = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=t_headers)
    assert fin.status_code == 200
    row = _audit_actions(client, action="qp_finalize")[0]
    assert row["target"] == f"qp:{qp['id']}"
    assert row["detail"] == {"class_level": 6, "subject": "science"}
