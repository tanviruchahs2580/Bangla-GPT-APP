"""AUD-B-05: registration's account-existence disclosure is a dated decision.

``POST /auth/register`` answers 409 ``email_taken`` for an address that
already has an account, unlike login and password-reset, which are
enumeration-safe. The resolution recorded in ``SECURITY.md`` is an accepted
deviation for this round (a neutral response needs an email-verified
registration flow plus SPA changes), bounded by the register rate limit.

Because the decision is "keep the behaviour", the test that protects it is a
contract pin: it proves the two paths and the rate limit exist, so changing
either without revisiting the decision fails CI.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.middleware_stack import _effective_rules
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                env="test",
                database_url=f"sqlite:///{tmp_path}/b_register.db",
                jwt_secret=JWT,
                admin_email="root@example.com",
                admin_password=PASSWORD,
                force_admin_password_change=False,
            )
        )
    )


def _payload(email: str = "enum-check@example.net") -> dict:
    return {
        "email": email,
        "password": PASSWORD,
        "name": "নাম",
        "role": "student",
        "guardian_consent": True,
        "class_level": 6,
    }


def test_duplicate_registration_is_a_documented_409(client: TestClient) -> None:
    assert client.post("/auth/register", json=_payload()).status_code == 201
    again = client.post("/auth/register", json=_payload())
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "email_taken"


def test_password_reset_stays_enumeration_neutral(client: TestClient) -> None:
    """The inconsistency is bounded: the reset path answers 202 for both.

    This is the comparison the SECURITY.md decision relies on, so it is
    asserted rather than assumed.
    """
    assert client.post("/auth/register", json=_payload("known@example.net")).status_code == 201
    known = client.post("/auth/forgot", json={"email": "known@example.net"}).status_code
    unknown = client.post("/auth/forgot", json={"email": "nobody@example.net"}).status_code
    assert known == unknown == 202


def test_register_rate_limit_rule_ships_by_default() -> None:
    """The control that bounds the oracle, asserted on the shipped defaults."""
    rules = _effective_rules(Settings(env="test"))
    assert rules.get("/auth/register") == (10, "ip")
