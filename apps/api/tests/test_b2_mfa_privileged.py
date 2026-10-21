"""AUD-B-06 (MFA half): privileged-role posture, compensating controls, doc drift.

The B register recorded "MFA optional for privileged roles with no
compensating-control document". The decision here is documented, not a silent
enforcement change: `docs/security/mfa-privileged-roles.md` records the
current posture, the compensating controls that bound it, and the owner
action. These tests keep that document honest:

* an **admin** can complete the full MFA lifecycle and a challenged login
  yields a working bearer token (the recovery path an operator depends on);
* the **posture pin**: a privileged account without MFA still receives a
  bearer token — flipping this to enforced MFA must be a deliberate change
  that also updates the decision record;
* the document names both privileged roles and lists the compensating
  controls the register asked for.
"""

from __future__ import annotations

import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.auth.mfa import _hotp
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

SECRET = "test-secret-0123456789abcdef0123456789"
ADMIN_PASSWORD = "Adm1n-Str0ng-Passphrase!"
DOC = pathlib.Path(__file__).resolve().parents[3] / "docs" / "security" / "mfa-privileged-roles.md"


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/mfa_priv.db",
        jwt_secret=SECRET,
        admin_email="root@example.test",
        admin_password=ADMIN_PASSWORD,
        force_admin_password_change=False,
    )


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(_settings(tmp_path)))


def _current_code(secret: str) -> str:
    return _hotp(secret, int(time.time()) // 30)


def _admin_login(client: TestClient) -> str:
    res = client.post(
        "/auth/login", json={"email": "root@example.test", "password": ADMIN_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_admin_can_complete_the_mfa_lifecycle(client: TestClient) -> None:
    token = _admin_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    enroll = client.post("/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200, enroll.text
    secret = enroll.json()["secret"]

    verify = client.post(
        "/auth/mfa/verify",
        json={"secret": secret, "code": _current_code(secret)},
        headers=headers,
    )
    assert verify.status_code == 200, verify.text
    assert verify.json() == {"enabled": True}

    # Login now answers 202 with a purpose-bound step-up token...
    step_up = client.post(
        "/auth/login", json={"email": "root@example.test", "password": ADMIN_PASSWORD}
    )
    assert step_up.status_code == 202, step_up.text
    assert step_up.json()["token_type"] == "mfa"

    # ...which is NOT a working API credential...
    mfa_token = step_up.json()["access_token"]
    refused = client.get("/admin/audit", headers={"Authorization": f"Bearer {mfa_token}"})
    assert refused.status_code == 401, refused.text

    # ...until the second factor converts it into a real bearer token that
    # reaches the admin surface.
    challenge = client.post(
        "/auth/mfa/challenge",
        json={"mfa_token": mfa_token, "code": _current_code(secret)},
    )
    assert challenge.status_code == 200, challenge.text
    real = challenge.json()["access_token"]
    allowed = client.get("/admin/audit", headers={"Authorization": f"Bearer {real}"})
    assert allowed.status_code == 200, allowed.text


def test_posture_pin_mfa_is_not_enforced_for_admins(client: TestClient) -> None:
    """The documented decision is "optional for privileged roles".

    When enforcement lands, this test must fail so the change is deliberate:
    update `docs/security/mfa-privileged-roles.md` (decision + recovery
    procedure) in the same commit that flips the behaviour.
    """
    res = client.post(
        "/auth/login", json={"email": "root@example.test", "password": ADMIN_PASSWORD}
    )
    assert res.status_code == 200, res.text
    assert res.json()["token_type"] == "bearer"


def test_decision_record_names_roles_and_controls() -> None:
    text = DOC.read_text(encoding="utf-8")
    # Both privileged roles are named in the document.
    assert "admin" in text and "school_admin" in text
    # NIST/inline references to the code that implements each control.
    for control_anchor in (
        "_LOGIN_LOCKOUT_",
        "forbid_impersonation",
        "single_use",
        "AuditLog",
    ):
        assert control_anchor in text, control_anchor
    # The register asked for compensating controls; a one-line doc would not
    # be a record. The table carries at least six.
    assert text.count("\n| ") >= 6
    # The decision is dated and carries the owner action.
    assert "2026-10-19" in text
    assert "Owner action" in text
