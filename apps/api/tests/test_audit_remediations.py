"""Regression tests for the 2026-10-06 audit remediations.

Covers the confirmed defects fixed in this pass:
- F-01: /metrics bearer bypass (any ``Authorization: Bearer ...`` used to pass)
- F-02: /auth/mfa/challenge had no rate-limit rule (TOTP brute-forceable)
- F-03: POST /students/{id}/consent/reconfirm skipped the school tenancy gate
- F-06: CORS preflight rejected PATCH (and CORS was registered twice)
- F-07: RATE_LIMIT_RULES setting was silently ignored
"""

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JOIN_PASSWORD = "joinsecret9"
JWT = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        env="test",
        database_url=f"sqlite:///{tmp_path}/remediation.db",
        jwt_secret=JWT,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return Settings(**base)


def _prod_settings(tmp_path, **over) -> Settings:
    base = dict(
        env="production",
        database_url=f"sqlite:///{tmp_path}/prod.db",
        jwt_secret=JWT,
        admin_email="a@b.com",
        admin_password="longenoughpass1",
        allowed_origins="https://app.example.com",
        pii_enc_key="k" * 32,
        smtp_enabled=True,
        smtp_host="smtp.example.com",
        smtp_from="noreply@example.com",
        metrics_require_auth=True,
        metrics_token="tok-" + "x" * 28,
    )
    base.update(over)
    return Settings(**base)


def _register(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "নাম", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login_headers(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# --- F-01: /metrics token enforcement --------------------------------------


def test_metrics_rejects_garbage_bearer(tmp_path) -> None:
    c = TestClient(create_app(_prod_settings(tmp_path)))
    assert c.get("/metrics").status_code == 403
    assert c.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert c.get("/metrics", headers={"x-metrics-token": "wrong"}).status_code == 403
    ok_bearer = c.get("/metrics", headers={"Authorization": "Bearer tok-" + "x" * 28})
    assert ok_bearer.status_code == 200
    ok_header = c.get("/metrics", headers={"x-metrics-token": "tok-" + "x" * 28})
    assert ok_header.status_code == 200


# --- F-02: MFA challenge rate limit -----------------------------------------


def test_mfa_challenge_rate_limited(tmp_path) -> None:
    c = TestClient(create_app(_settings(tmp_path)))
    bad = {"mfa_token": "x" * 32, "code": "000000"}
    codes = []
    for _ in range(5):
        res = c.post("/auth/mfa/challenge", json=bad)
        codes.append(res.status_code)
    # every attempt inside the window fails auth (401), the 6th is throttled
    assert codes == [401, 401, 401, 401, 401]
    assert c.post("/auth/mfa/challenge", json=bad).status_code == 429


# --- F-03: consent reconfirm tenancy ----------------------------------------


def _school_with_teacher(client: TestClient, name: str, email: str) -> dict:
    root = _login_headers(client, "root@example.com")
    school = client.post("/admin/schools", json={"name": name}, headers=root).json()
    invite = client.post(
        f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root
    ).json()
    res = client.post(
        "/auth/join-school",
        json={
            "invite_code": invite["code"],
            "email": email,
            "password": JOIN_PASSWORD,
            "name": "শিক্ষক",
        },
    )
    assert res.status_code == 201, res.text
    return school


def test_consent_reconfirm_denied_across_schools(tmp_path) -> None:
    c = TestClient(create_app(_settings(tmp_path)))
    _school_with_teacher(c, "School A", "ta@school.test")
    student = _register(c, "student@example.com")
    teacher = _login_headers(c, "ta@school.test", JOIN_PASSWORD)

    denied = c.post(
        f"/students/{student['profile_id']}/consent/reconfirm",
        json={"accepted": True},
        headers=teacher,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "other_school"


def test_consent_reconfirm_admin_still_allowed(tmp_path) -> None:
    c = TestClient(create_app(_settings(tmp_path)))
    student = _register(c, "student2@example.com")
    admin = _login_headers(c, "root@example.com")
    ok = c.post(
        f"/students/{student['profile_id']}/consent/reconfirm",
        json={"accepted": True},
        headers=admin,
    )
    assert ok.status_code == 200
    assert ok.json()["accepted_version"] == ok.json()["current_version"]


def test_consent_reconfirm_own_student_allowed(tmp_path) -> None:
    c = TestClient(create_app(_settings(tmp_path)))
    student = _register(c, "self@example.com")
    headers = _login_headers(c, "self@example.com")
    ok = c.post(
        f"/students/{student['profile_id']}/consent/reconfirm",
        json={"accepted": True},
        headers=headers,
    )
    assert ok.status_code == 200


# --- F-06: CORS PATCH preflight ----------------------------------------------


def test_cors_preflight_allows_patch(tmp_path) -> None:
    c = TestClient(
        create_app(
            _settings(
                tmp_path,
                database_url=f"sqlite:///{tmp_path}/cors.db",
                allowed_origins="https://app.example.edu.bd",
            )
        )
    )
    res = c.options(
        "/admin/users/1/role",
        headers={
            "Origin": "https://app.example.edu.bd",
            "Access-Control-Request-Method": "PATCH",
        },
    )
    assert res.status_code == 200
    assert "PATCH" in res.headers["access-control-allow-methods"]


# --- F-07: RATE_LIMIT_RULES is effective -------------------------------------


def test_rate_limit_rules_override_takes_effect(tmp_path) -> None:
    c = TestClient(create_app(_settings(tmp_path, rate_limit_rules={"/events": (1, "ip")})))
    headers = _login_headers(c, "root@example.com")
    event = {"name": "audit_remediation_probe", "props": {}}
    assert c.post("/events", json=event, headers=headers).status_code in (200, 201, 202)
    assert c.post("/events", json=event, headers=headers).status_code == 429


def test_default_rule_tables_stay_in_parity() -> None:
    """config.rate_limit_rules defaults must stay in sync with the
    middleware's per-field derived rules — guards against the tables
    drifting apart again (the defect that hid /auth/mfa/challenge from
    rate limiting)."""
    from bangla_gpt_api.config import Settings as S
    from bangla_gpt_api.initialize.middleware_stack import _derive_default_rules

    derived = _derive_default_rules(S(env="test", jwt_secret=JWT))
    defaults = S().rate_limit_rules
    for route, rule in derived.items():
        assert defaults.get(route) == rule, route
