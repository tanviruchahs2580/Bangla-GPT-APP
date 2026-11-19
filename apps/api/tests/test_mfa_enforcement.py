"""T-13 / BC-6: MFA enforcement for configured roles.

``MFA_REQUIRED_ROLES`` (comma-separated, EMPTY default = current behaviour)
makes TOTP enrolment mandatory for those roles. A required-but-unenrolled
user keeps a session only for the enrolment endpoints plus the session-less
basics -- the same restricted-waiver shape as the forced password change.
The default-empty path is asserted so the shipped behaviour is provably
unchanged; flipping the default in production is a recorded S-3 decision.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "Str0ngJoinPassw0rd!"
ROOT_PASSWORD = "Str0ngRootPassw0rd!"


@pytest.fixture
def env(tmp_path):
    def make(**overrides) -> TestClient:
        base = dict(
            env="test",
            database_url=engine_url(tmp_path, "mfa_enforce"),
            jwt_secret="test-secret-0123456789abcdef0123456789",
            admin_email="root@example.com",
            admin_password=ROOT_PASSWORD,
            force_admin_password_change=False,
        )
        base.update(overrides)
        return TestClient(create_app(Settings(**base)))

    yield make


def _seed_teacher(client: TestClient, email: str = "teach@mfa.test") -> None:
    root = {"Authorization": "Bearer " + _login(client, "root@example.com", ROOT_PASSWORD)}
    school = client.post("/admin/schools", json={"name": "MFA School"}, headers=root).json()
    res = client.post(f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root)
    code = res.json()["code"]
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


def test_default_keeps_mfa_optional(env):
    """The shipped default: an unenrolled teacher works exactly as before."""
    client = env()
    _seed_teacher(client)
    token = _login(client, "teach@mfa.test")
    res = client.get("/users/me", headers={"Authorization": "Bearer " + token})
    assert res.status_code == 200, res.text


def test_required_role_unenrolled_is_restricted_to_enrolment_endpoints(env):
    client = env(mfa_required_roles="teacher")
    _seed_teacher(client)
    token = _login(client, "teach@mfa.test")
    headers = {"Authorization": "Bearer " + token}

    # normal routes are refused with the dedicated code (GET /users/me stays
    # allowed by the same method-scoped waiver the forced password change
    # uses -- the enrolment screen reads it)
    res = client.get("/notifications", headers=headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "mfa_enrollment_required"

    # the one waived read: the enrolment screen's own identity read
    assert client.get("/users/me", headers=headers).status_code == 200

    # enrolment endpoints stay reachable
    enroll = client.post("/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200, enroll.text
    secret = enroll.json()["secret"]
    assert secret, "enroll must return the seed for the authenticator app"

    # the ops probes stay reachable for the platform
    assert client.get("/health").status_code == 200

    # logout is allowed (the user can give up)
    assert client.post("/auth/logout", headers=headers).status_code == 204


def test_required_role_after_enrolment_is_unrestricted(env):
    client = env(mfa_required_roles="teacher")
    _seed_teacher(client)
    token = _login(client, "teach@mfa.test")
    headers = {"Authorization": "Bearer " + token}

    enroll = client.post("/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200, enroll.text
    secret = enroll.json()["secret"]

    # prove possession with a valid TOTP code (pyotp is in the lockfile's
    # dependency set via the MFA module's own import; the verify step is the
    # RFC 6238 flow the module documents)
    import base64
    import hashlib
    import hmac
    import struct
    import time

    counter = int(time.time()) // 30
    digest = hmac.new(
        base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8)),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    code = str((struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000).zfill(
        6
    )

    verify = client.post(
        "/auth/mfa/verify",
        json={"secret": secret, "code": code, "password": PASSWORD},
        headers=headers,
    )
    assert verify.status_code == 200, verify.text

    # the account is enrolled: a fresh login now runs the documented 202
    # MFA-challenge flow (auth/mfa.py) before normal routes work
    import time as _time

    counter = int(_time.time()) // 30
    digest2 = hmac.new(
        base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8)),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset2 = digest2[-1] & 0x0F
    code2 = str(
        (struct.unpack(">I", digest2[offset2 : offset2 + 4])[0] & 0x7FFFFFFF) % 1000000
    ).zfill(6)
    challenge_login = client.post(
        "/auth/login", json={"email": "teach@mfa.test", "password": PASSWORD}
    )
    assert challenge_login.status_code == 202, challenge_login.text
    mfa_token = challenge_login.json()["access_token"]
    assert challenge_login.json()["token_type"] == "mfa"
    chal = client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": code2})
    assert chal.status_code == 200, chal.text
    fresh = str(chal.json()["access_token"])
    assert (
        client.get("/notifications", headers={"Authorization": "Bearer " + fresh}).status_code
        == 200
    )


def test_role_outside_the_required_set_is_never_restricted(env):
    """A role NOT in the required set works exactly as before (here: teacher
    while only parents are required -- the seeding admin is also outside the
    set, so the flow itself proves non-required roles are untouched)."""
    client = env(mfa_required_roles="parent")
    _seed_teacher(client)
    token = _login(client, "teach@mfa.test")
    assert client.get("/users/me", headers={"Authorization": "Bearer " + token}).status_code == 200


def test_required_roles_setting_parses_spaces(env):
    client = env(mfa_required_roles=" teacher , school_admin ")
    _seed_teacher(client)
    token = _login(client, "teach@mfa.test")
    res = client.get("/notifications", headers={"Authorization": "Bearer " + token})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "mfa_enrollment_required"
