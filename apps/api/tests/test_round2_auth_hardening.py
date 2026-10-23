"""Auth hardening: enumeration oracles, JWT claim ownership, secret policy.

F-057  login disclosed whether an address was registered, two ways
F-066  extra_claims could own a reserved claim; the MFA step-up token was
       a replayable bearer credential
F-067  the JWT secret guard checked length only
F-068  PII_ENC_KEY was checked for presence, not validity
F-070  MFA step-up replay
F-071  the MFA branch skipped the Argon2id rehash-on-login
F-072  no password blocklist
F-076  /auth/register and /auth/mfa/* carried no rate limit
"""

from __future__ import annotations

import statistics
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from bangla_gpt_api.auth import mfa as mfa_mod
from bangla_gpt_api.auth.security import (
    RESERVED_CLAIMS,
    create_access_token,
    decode_token,
    hash_password,
    is_common_password,
)
from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.middleware_stack import _effective_rules
from bangla_gpt_api.main import (
    _validate_jwt,
    _validate_pii,
    create_app,
)

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "Str0ngPassphrase!234"


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "env": "test",
        "database_url": f"sqlite:///{tmp_path}/auth.db",
        "jwt_secret": SECRET,
        "admin_email": "root@example.test",
        "admin_password": PASSWORD,
        "force_admin_password_change": False,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(_settings(tmp_path)))


def _register(client: TestClient, email: str, password: str = PASSWORD, role: str = "student"):
    payload: dict = {"email": email, "password": password, "name": "Tester", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    return client.post("/auth/register", json=payload)


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# F-057 - enumeration oracles
# ---------------------------------------------------------------------------


def test_login_does_not_reveal_that_an_address_is_registered(tmp_path) -> None:
    """The status code must not separate 'no such user' from 'wrong password'.

    SMTP is configured so the registered account stays UNVERIFIED — that is
    the case the old code answered with 403 `email_unverified`. With no SMTP
    the app trusts registrations, both branches answer 401, and this test
    would pass against the vulnerable code for the wrong reason.
    """
    client = TestClient(
        create_app(
            _settings(
                tmp_path,
                smtp_enabled=True,
                smtp_host="smtp.example.test",
                smtp_from="noreply@example.test",
            )
        )
    )
    assert _register(client, "real@example.test").status_code in (200, 201)

    res = _login(client, "real@example.test", "definitely-not-the-password")
    missing = _login(client, "nobody-at-all@example.test", "definitely-not-the-password")

    assert res.status_code == missing.status_code, (
        f"registered-but-unverified answered {res.status_code}, "
        f"unregistered answered {missing.status_code}; that difference is a "
        "working account-enumeration oracle"
    )
    assert res.json()["detail"]["code"] == missing.json()["detail"]["code"]
    assert missing.status_code == 401


def test_login_does_not_reveal_registration_by_response_time(client) -> None:
    """Argon2id must be spent on both paths, or timing answers the question.

    Measured over several rounds and compared as medians: a single sample on
    Windows is noise, a consistent multi-fold gap is a working oracle.
    """
    _register(client, "timed@example.test")

    def sample(email: str) -> float:
        best = []
        for _ in range(5):
            start = time.perf_counter()
            _login(client, email, "wrong-password-entirely")
            best.append(time.perf_counter() - start)
        return statistics.median(best)

    # Warm the decoy hash first so its construction is not counted as a
    # one-off cost on the unknown-address path.
    _login(client, "priming@example.test", "wrong-password-entirely")
    known = sample("timed@example.test")
    unknown = sample("still-nobody@example.test")

    assert unknown > known * 0.6, (
        f"unknown-address login was {known / max(unknown, 1e-9):.2f}x faster "
        f"(known {known * 1000:.1f}ms vs unknown {unknown * 1000:.1f}ms); "
        "the decoy hash is not being spent on the no-such-user path"
    )


def test_unverified_hint_is_only_given_when_the_password_is_right(tmp_path) -> None:
    """403 email_unverified is fine — but only to someone who holds the secret.

    SMTP is configured so registration leaves the account unverified; with no
    SMTP the app trusts registrations and every account is verified, which
    would make this test pass for the wrong reason.
    """
    client = TestClient(
        create_app(
            _settings(
                tmp_path,
                smtp_enabled=True,
                smtp_host="smtp.example.test",
                smtp_from="noreply@example.test",
            )
        )
    )
    assert _register(client, "unverified@example.test").status_code in (200, 201)
    # Wrong password on an unverified account: must NOT get the hint.
    wrong = _login(client, "unverified@example.test", "wrong-password-entirely")
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] != "email_unverified"
    # Right password: the hint is useful and discloses nothing new.
    right = _login(client, "unverified@example.test")
    assert right.status_code == 403
    assert right.json()["detail"]["code"] == "email_unverified"


# ---------------------------------------------------------------------------
# F-066 - reserved claims cannot be overridden
# ---------------------------------------------------------------------------


class _FakeUser:
    id = 4242
    role = "student"


def test_extra_claims_cannot_override_reserved_claims(tmp_path) -> None:
    settings = _settings(tmp_path)
    token = create_access_token(
        _FakeUser(),  # type: ignore[arg-type]
        settings=settings,
        extra_claims={"role": "admin", "sub": "999", "exp": 9999999999, "iss": "evil"},
    )
    claims = decode_token(token, settings=settings)
    assert claims["role"] == "student"
    assert claims["sub"] == "4242"
    assert claims["iss"] == settings.jwt_issuer
    assert claims["exp"] < 9999999999


def test_extra_claims_still_add_unreserved_claims(tmp_path) -> None:
    settings = _settings(tmp_path)
    token = create_access_token(
        _FakeUser(),  # type: ignore[arg-type]
        settings=settings,
        extra_claims={"imp": True, "mfa": True},
    )
    claims = decode_token(token, settings=settings)
    assert claims["imp"] is True
    assert claims["mfa"] is True


def test_reserved_claim_set_is_the_one_the_token_builder_owns() -> None:
    settings_fields = RESERVED_CLAIMS
    assert settings_fields == {"sub", "role", "iss", "aud", "exp", "iat", "jti"}


# ---------------------------------------------------------------------------
# F-070 - the MFA step-up token is single-use
# ---------------------------------------------------------------------------


def _enable_mfa(client: TestClient, email: str) -> str:
    _register(client, email)
    login = _login(client, email)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    secret = client.post("/auth/mfa/enroll", headers=headers).json()["secret"]
    code = mfa_mod._hotp(secret, int(time.time()) // mfa_mod._STEP_SECONDS)
    assert (
        client.post(
            "/auth/mfa/verify", json={"secret": secret, "code": code}, headers=headers
        ).status_code
        == 200
    )
    return secret


def test_mfa_step_up_token_cannot_be_replayed(client) -> None:
    secret = _enable_mfa(client, "mfauser@example.test")

    step_up = _login(client, "mfauser@example.test")
    assert step_up.status_code == 202
    mfa_token = step_up.json()["access_token"]

    code = mfa_mod._hotp(secret, int(time.time()) // mfa_mod._STEP_SECONDS)
    first = client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": code})
    assert first.status_code == 200, first.text

    # Same token, same code, immediately afterwards.
    second = client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": code})
    assert second.status_code == 401, (
        "the MFA step-up token was replayable; a token observed once could be "
        f"re-presented and got a fresh login (second response: {second.text})"
    )
    assert second.json()["detail"]["code"] == "bad_mfa_token"


def test_a_mistyped_code_does_not_burn_the_step_up(client) -> None:
    secret = _enable_mfa(client, "typo@example.test")
    step_up = _login(client, "typo@example.test")
    mfa_token = step_up.json()["access_token"]

    bad = client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": "000000"})
    assert bad.status_code == 401

    good = mfa_mod._hotp(secret, int(time.time()) // mfa_mod._STEP_SECONDS)
    ok = client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": good})
    assert ok.status_code == 200, "a wrong code must not cost the user their login"


# ---------------------------------------------------------------------------
# F-071 - the rehash runs even with MFA enabled
# ---------------------------------------------------------------------------


def test_login_upgrades_a_legacy_hash_for_an_mfa_account(client, tmp_path) -> None:
    """A legacy pbkdf2 hash must be upgraded however the login completes."""
    import hashlib

    _enable_mfa(client, "legacy-mfa@example.test")

    from bangla_gpt_api.db.session import make_engine, make_session_factory

    settings = _settings(tmp_path)
    factory = make_session_factory(make_engine(settings))
    salt = "aa" * 16
    expected = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), bytes.fromhex(salt), 200000).hex()
    legacy_value = f"pbkdf2_sha256$200000${salt}${expected}"

    with factory() as db:
        from bangla_gpt_api.db.models import User

        user = db.query(User).filter(User.email == "legacy-mfa@example.test").one()
        user.password_hash = legacy_value
        db.commit()

    from bangla_gpt_api.auth.security import verify_password

    assert verify_password(PASSWORD, legacy_value), "the fixture hash must actually verify"

    # The MFA branch is taken (totp_secret set) -> the old code returned here
    # and never reached the rehash.
    assert _login(client, "legacy-mfa@example.test").status_code == 202

    with factory() as db:
        from bangla_gpt_api.db.models import User

        user = db.query(User).filter(User.email == "legacy-mfa@example.test").one()
        assert user.password_hash != legacy_value, (
            "the Argon2id upgrade was skipped on the MFA branch; a legacy "
            "pbkdf2 hash survives every login for an MFA-enabled account"
        )
        assert user.password_hash.startswith("$argon2")


# ---------------------------------------------------------------------------
# F-072 - password blocklist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        "password",
        "Password1",
        "p@ssw0rd",
        "P@ssw0rd1",
        "12345678",
        "qwerty123",
        "aaaaaaaa",
        "bangladesh123",
        "letmein",
        "student123",
    ],
)
def test_common_passwords_are_recognised(candidate: str) -> None:
    assert is_common_password(candidate), candidate


@pytest.mark.parametrize(
    "candidate",
    ["Str0ngPassphrase!234", "monsoon-rain-42-mango", "correct horse battery", "t@chor-ঢাকা-9"],
)
def test_reasonable_passwords_are_not_blocked(candidate: str) -> None:
    assert not is_common_password(candidate), candidate


def test_registration_refuses_a_common_password(client) -> None:
    res = _register(client, "weak@example.test", "password")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "password_too_common"


def test_password_reset_refuses_a_common_password(client) -> None:
    """A blocklist on registration alone is bypassed by a reset to 12345678."""
    _register(client, "resetter@example.test")
    from bangla_gpt_api.db.session import make_engine, make_session_factory

    # Mint a reset row directly and then try the weak password through the API.
    res = client.post("/auth/forgot", json={"email": "resetter@example.test"})
    assert res.status_code == 202
    settings = client.app.state.settings
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        from datetime import UTC, datetime, timedelta

        from bangla_gpt_api.db.models import PasswordReset, User

        user = db.query(User).filter(User.email == "resetter@example.test").one()
        token = "a" * 48
        db.add(
            PasswordReset(
                user_id=user.id,
                token_hash=hashlib_sha256(token),
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            )
        )
        db.commit()

    weak = client.post("/auth/reset", json={"token": token, "new_password": "12345678"})
    assert weak.status_code == 400
    assert weak.json()["detail"]["code"] == "password_too_common"


def hashlib_sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# F-067 / F-068 - production secret policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "a" * 32,
        "0" * 48,
        "abcabcabcabcabcabcabcabcabcabcab",
        "123456" * 8,
        "change-me-change-me-change-me",
    ],
)
def test_production_refuses_a_predictable_jwt_secret(secret: str) -> None:
    problems = _validate_jwt(_settings_standalone(jwt_secret=secret))
    assert problems, f"a length-only guard accepted {secret!r}"


def test_production_accepts_a_real_random_secret() -> None:
    import secrets as pysecrets

    assert _validate_jwt(_settings_standalone(jwt_secret=pysecrets.token_urlsafe(48))) == []


def _settings_standalone(**overrides) -> Settings:
    base = {"env": "test", "database_url": "sqlite://", "jwt_secret": SECRET}
    base.update(overrides)
    return Settings(**base)


def test_production_refuses_a_malformed_pii_key() -> None:
    problems = _validate_pii(_settings_standalone(pii_enc_key="not-a-fernet-key"))
    assert problems, "a malformed Fernet key passed the presence-only guard"
    assert "Fernet" in problems[0]


def test_production_accepts_a_real_fernet_key() -> None:
    key = Fernet.generate_key().decode()
    assert _validate_pii(_settings_standalone(pii_enc_key=key)) == []


# ---------------------------------------------------------------------------
# F-076 - rate-limit coverage
# ---------------------------------------------------------------------------


def test_register_and_mfa_are_rate_limited() -> None:
    rules = _effective_rules(_settings_standalone())
    assert "/auth/register" in rules, rules.keys()
    assert "/auth/mfa" in rules, rules.keys()
    assert rules["/auth/register"][0] > 0

    # F-076: ``RATE_LIMIT_RULES`` REPLACES the whole default map, so an operator
    # who overrides a single route must not silently unbind the account-creating
    # and secret-consuming routes. The derived defaults in
    # ``_derive_default_rules`` are the safety net for exactly that case, and
    # this is the path that makes them load-bearing: with the config map reduced
    # to one entry, register/mfa/challenge can only come from the derivation.
    # (/auth/forgot is used rather than /auth/login: login is one of the four
    # per-field routes, where the dedicated knob deliberately wins.)
    partial = _effective_rules(_settings_standalone(rate_limit_rules={"/auth/forgot": (3, "ip")}))
    assert partial["/auth/forgot"] == (3, "ip")
    for route in ("/auth/register", "/auth/mfa", "/auth/mfa/challenge"):
        assert route in partial, (route, partial.keys())
        assert partial[route][0] > 0


def test_register_eventually_returns_429(client) -> None:
    """Not vacuous: the limit must actually bite."""
    seen_429 = False
    for i in range(12):
        res = _register(client, f"flood{i}@example.test")
        if res.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "12 registrations from one IP produced no 429"


# ---------------------------------------------------------------------------
# sanity: password hashing itself is untouched
# ---------------------------------------------------------------------------


def test_hash_password_roundtrip() -> None:
    stored = hash_password(PASSWORD)
    assert stored.startswith("$argon2")

    from bangla_gpt_api.auth.security import verify_password

    assert verify_password(PASSWORD, stored)
    assert not verify_password("wrong", stored)


def test_parallel_mfa_challenges_issue_exactly_one_session(client) -> None:
    """Concurrent replays of one step-up token: exactly one winner.

    The original burn was check-then-act — ``get_json_strict`` to see
    whether the jti was used, then ``set_json_strict`` to mark it. Two
    concurrent challenges with the same intercepted token and the same
    currently-valid 30-second code both read "unused" before either wrote,
    and both were issued full sessions, defeating the replay guarantee for
    exactly the parallel case it was written for. The claim is now one
    SETNX (``Cache.add_if_absent``); this test fires N identical
    challenges and asserts the count of 200s is exactly 1.
    """
    import threading

    secret = _enable_mfa(client, "parallel-mfa@example.test")
    step_up = _login(client, "parallel-mfa@example.test")
    assert step_up.status_code == 202
    mfa_token = step_up.json()["access_token"]

    code = mfa_mod._hotp(secret, int(time.time()) // mfa_mod._STEP_SECONDS)
    attempts = 4
    barrier = threading.Barrier(attempts)
    statuses: list[int] = []
    statuses_lock = threading.Lock()

    def challenge() -> None:
        barrier.wait(5)
        res = client.post("/auth/mfa/challenge", json={"mfa_token": mfa_token, "code": code})
        with statuses_lock:
            statuses.append(res.status_code)

    threads = [threading.Thread(target=challenge) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert len(statuses) == attempts
    assert statuses.count(200) == 1, (
        f"the step-up token was replayed: {statuses.count(200)} of {attempts} "
        f"concurrent challenges minted sessions (statuses: {statuses})"
    )
    assert all(s in (200, 401) for s in statuses), statuses
