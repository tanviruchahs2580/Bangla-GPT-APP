"""AUD-B-04 / AUD-B-06: two security decisions that must leave a trace.

* the government aggregate export writes one audit row per successful export
  (B-11 "export access audited"), carrying ids and counts only;
* ``POST /auth/logout`` retires the caller's token in the shared deny-list,
  so the same bearer token is refused afterwards while a fresh login still
  works.

Both are asserted against the real app on a real database, through the public
API only -- no mock of the system under test.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"
ADMIN = "root@example.com"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/b_audit.db",
        jwt_secret=JWT,
        admin_email=ADMIN,
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _register_student(client: TestClient, email: str, name: str = "শিক্ষার্থী") -> int:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": name,
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    return int(res.json()["profile_id"])


# --- AUD-B-06: the government export is audited -----------------------------


def test_aggregate_export_writes_one_audit_row(client: TestClient) -> None:
    admin = _login(client, ADMIN)
    before = client.get("/admin/audit?action=govt_export", headers=admin).json()["total"]

    export = client.get("/admin/reports/aggregate?district=Dhaka&format=csv", headers=admin)
    assert export.status_code == 200, export.text

    page = client.get("/admin/audit?action=govt_export", headers=admin)
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == before + 1, "export access must be audited (AUD-B-06)"
    row = body["rows"][0]
    assert row["actor_role"] == "admin"
    assert row["target"] == "district:Dhaka"
    detail = row["detail"]
    assert detail["format"] == "csv"
    assert detail["district"] == "Dhaka"
    assert isinstance(detail["rows"], int)
    assert isinstance(detail["students_included"], int)
    # No payload, no PII in the audit row.
    assert set(detail) == {
        "format",
        "district",
        "since_days",
        "min_cell",
        "rows",
        "students_included",
        "suppressed_cells",
    }


def test_export_audit_is_admin_scoped(client: TestClient) -> None:
    _register_student(client, "student-a@example.net")
    student = _login(client, "student-a@example.net")
    assert client.get("/admin/reports/aggregate", headers=student).status_code == 403
    assert client.get("/admin/audit?action=govt_export", headers=student).status_code == 403


# --- AUD-B-04: logout revokes the token server-side -------------------------


def test_logout_revokes_the_presented_token(client: TestClient) -> None:
    _register_student(client, "logout-user@example.net")
    headers = _login(client, "logout-user@example.net")
    assert client.get("/users/me", headers=headers).status_code == 200

    out = client.post("/auth/logout", headers=headers)
    assert out.status_code == 204

    revoked = client.get("/users/me", headers=headers)
    assert revoked.status_code == 401, "a revoked token must not authenticate"

    # A fresh login is unaffected: only the retired jti is denied.
    fresh = _login(client, "logout-user@example.net")
    assert client.get("/users/me", headers=fresh).status_code == 200
    # ...and the old token stays dead after the new one is issued.
    assert client.get("/users/me", headers=headers).status_code == 401


def test_logout_requires_authentication(client: TestClient) -> None:
    assert client.post("/auth/logout").status_code == 401
