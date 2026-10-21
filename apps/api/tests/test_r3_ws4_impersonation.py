"""B-09: an impersonation session cannot change credentials or delete data.

The audit's hole: an impersonation token could call ``DELETE /users/me`` and
erase the impersonated user's account. The per-route dependency on that one
route is now backed by a central refusal in ``get_current_user``: every
``DELETE`` and every credential-mutating path (password change, MFA
enroll/verify/disable) is refused for ``imp`` tokens no matter which router
serves it. These tests exercise it through the public API on a real app --
including the two paths the per-route guard never covered.
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
        database_url=f"sqlite:///{tmp_path}/r3_ws4_imp.db",
        jwt_secret=JWT,
        admin_email=ADMIN,
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _register_student(client: TestClient, email: str) -> int:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    return int(res.json()["user_id"])


def _impersonate(client: TestClient, user_id: int) -> dict:
    admin = _login(client, ADMIN)
    res = client.post(
        f"/admin/users/{user_id}/impersonate",
        json={"reason": "support session for the B-09 suite"},
        headers=admin,
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_impersonation_cannot_delete_me(client: TestClient) -> None:
    user_id = _register_student(client, "b09-delete@example.net")
    imp = _impersonate(client, user_id)
    res = client.delete("/users/me", headers=imp)
    assert res.status_code == 403, res.text
    assert res.json()["detail"]["code"] == "impersonation_readonly"
    # The account is intact: the real owner can still log in and read it.
    owner = _login(client, "b09-delete@example.net")
    assert client.get("/users/me", headers=owner).status_code == 200


def test_impersonation_cannot_delete_a_conversation(client: TestClient) -> None:
    """The per-route guard never covered this DELETE; the central one does."""
    user_id = _register_student(client, "b09-convo@example.net")
    owner = _login(client, "b09-convo@example.net")
    created = client.post("/tutor/conversations", json={}, headers=owner)
    assert created.status_code in (200, 201), created.text
    convo_id = created.json()["id"]

    imp = _impersonate(client, user_id)
    res = client.delete(f"/tutor/conversations/{convo_id}", headers=imp)
    assert res.status_code == 403, res.text
    assert res.json()["detail"]["code"] == "impersonation_readonly"
    # The owner still sees the conversation.
    listing = client.get("/tutor/conversations", headers=owner)
    assert listing.status_code == 200
    ids = {row["id"] for row in listing.json()}
    assert convo_id in ids


def test_impersonation_cannot_change_the_password(client: TestClient) -> None:
    user_id = _register_student(client, "b09-password@example.net")
    imp = _impersonate(client, user_id)
    res = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "brand-new-secret-9"},
        headers=imp,
    )
    assert res.status_code == 403, res.text
    assert res.json()["detail"]["code"] == "impersonation_readonly"
    # The original password still logs in; the attempted one does not.
    assert (
        client.post(
            "/auth/login", json={"email": "b09-password@example.net", "password": PASSWORD}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": "b09-password@example.net", "password": "brand-new-secret-9"},
        ).status_code
        == 401
    )


def test_impersonation_cannot_enroll_an_mfa_factor(client: TestClient) -> None:
    """Enrolling a factor would hand the impersonator standing access."""
    user_id = _register_student(client, "b09-mfa@example.net")
    imp = _impersonate(client, user_id)
    res = client.post("/auth/mfa/enroll", headers=imp)
    assert res.status_code == 403, res.text
    assert res.json()["detail"]["code"] == "impersonation_readonly"
    assert (
        client.post("/auth/mfa/disable", json={"password": PASSWORD}, headers=imp).status_code
        == 403
    )


def test_impersonation_can_still_help_read_and_write_non_destructive(client: TestClient) -> None:
    """The session stays useful: reads and ordinary support actions work."""
    user_id = _register_student(client, "b09-readonly@example.net")
    imp = _impersonate(client, user_id)
    assert client.get("/users/me", headers=imp).status_code == 200
    # A normal write (starting a conversation) is allowed -- only destructive
    # and credential-mutating operations are refused.
    created = client.post("/tutor/conversations", json={}, headers=imp)
    assert created.status_code in (200, 201), created.text


def test_the_real_owner_keeps_full_rights(client: TestClient) -> None:
    """The refusal is scoped to imp tokens, not to the account."""
    _register_student(client, "b09-owner@example.net")
    owner = _login(client, "b09-owner@example.net")
    created = client.post("/tutor/conversations", json={}, headers=owner)
    assert created.status_code in (200, 201), created.text
    gone = client.delete(f"/tutor/conversations/{created.json()['id']}", headers=owner)
    assert gone.status_code == 204, gone.text
    enroll = client.post("/auth/mfa/enroll", headers=owner)
    assert enroll.status_code == 200, enroll.text
