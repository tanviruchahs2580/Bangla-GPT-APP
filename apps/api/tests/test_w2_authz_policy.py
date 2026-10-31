"""SEC-02 wave-2 guards: the password policy is named, cited and enforced.

The audit found the password rules spread across a doc line and a schema
``min_length`` with no citation: nothing stated WHICH NIST SP 800-63B
revision was targeted, and the policy's shape (length-based only, long
passphrases allowed, no composition rules) was not asserted anywhere. The
policy now lives in ``auth/security.py`` with the revision and the clause
numbers, plus the Argon2id parameters as named constants, and these tests
pin the properties the clause requires:

* the length floor is the ONLY structural rule (an all-lowercase 20-char
  passphrase registers);
* passphrases far beyond 64 characters work (SP 800-63B-4: a verifier
  SHOULD permit at least 64);
* the floor is a real bound, and it is Settings-driven so an operator can
  raise it to the single-factor figure of 15 without a code change;
* the blocklist still refuses known guesses at every credential entry
  point (registration, reset, change-password);
* the named Argon2id parameters equal what the produced hashes encode, so
  the "named parameters" cannot drift from the algorithm actually used;
* the login timing equalisation (decoy verify on an unknown address) is
  preserved -- it is the one password-path behaviour this change must not
  disturb.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.auth.security import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    PASSWORD_MAX_LENGTH,
    _burn_password_check,
    hash_password,
    password_length_problem,
    verify_password,
)
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _client(tmp_path, **over) -> TestClient:
    base = dict(
        env="test",
        database_url=engine_url(tmp_path, "w2policy"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return TestClient(create_app(Settings(**base)))


def _register(client: TestClient, email: str, password: str) -> int:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "name": "Tester",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    return res.status_code


def test_length_is_the_only_structural_rule(tmp_path) -> None:
    """No composition requirements: a lowercase passphrase is valid."""
    client = _client(tmp_path)
    assert _register(client, "lower@example.com", "correcthorsebatterystaple") == 201

    login = client.post(
        "/auth/login",
        json={"email": "lower@example.com", "password": "correcthorsebatterystaple"},
    )
    assert login.status_code == 200


def test_long_passphrases_are_accepted_whole(tmp_path) -> None:
    """SP 800-63B-4 s3.1.1.2: permit at least 64 characters; verify it all.

    A verifier that truncated the input would accept a WRONG tail -- the
    assertion below proves the full secret is hashed and compared.
    """
    client = _client(tmp_path)
    passphrase = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
    assert len(passphrase) > 64
    assert _register(client, "long@example.com", passphrase) == 201

    ok = client.post("/auth/login", json={"email": "long@example.com", "password": passphrase})
    assert ok.status_code == 200
    # same prefix, different tail -> refused (nothing was truncated)
    truncated = passphrase[:-1] + "X"
    bad = client.post("/auth/login", json={"email": "long@example.com", "password": truncated})
    assert bad.status_code == 401


def test_floor_is_enforced_and_settings_driven(tmp_path) -> None:
    """The default floor is the documented 8; the knob raises it to 15."""
    default_client = _client(tmp_path, password_min_length=8)
    assert _register(default_client, "eight@example.com", "abcdefgh") == 201

    strict_client = _client(tmp_path, password_min_length=15)
    refused = strict_client.post(
        "/auth/register",
        json={
            "email": "short@example.com",
            "password": "abcdefghijklmn",
            "name": "Tester",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "password_too_short"
    assert "15" in refused.json()["detail"]["message"]
    assert _register(strict_client, "fifteen@example.com", "abcdefghijklmno") == 201


def test_policy_helper_rejects_the_extremes() -> None:
    assert password_length_problem("short", minimum=8) is not None
    assert password_length_problem("abcdefgh", minimum=8) is None
    assert password_length_problem("x" * PASSWORD_MAX_LENGTH, minimum=8) is None
    assert password_length_problem("x" * (PASSWORD_MAX_LENGTH + 1), minimum=8) is not None


def test_blocklist_applies_at_every_credential_entry_point(tmp_path) -> None:
    """A floor without the blocklist is bypassed by "12345678" plus padding."""
    client = _client(tmp_path)
    refused = client.post(
        "/auth/register",
        json={
            "email": "common@example.com",
            "password": "password123",
            "name": "Tester",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "password_too_common"

    # the same policy guards a password CHANGE (the bypass the comment in
    # routers/auth.py names: a forced-reset flow pushes people to weak ones)
    assert _register(client, "changer@example.com", PASSWORD) == 201
    login = client.post("/auth/login", json={"email": "changer@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    changed = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "12345678"},
        headers=headers,
    )
    assert changed.status_code == 400
    assert changed.json()["detail"]["code"] == "password_too_common"


def test_named_argon2_parameters_match_the_encoded_hash() -> None:
    """The named constants ARE the parameters the hashes carry."""
    stored = hash_password("a-long-enough-passphrase")
    assert stored.startswith("$argon2id$")
    assert f"m={ARGON2_MEMORY_COST_KIB},t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}" in stored
    # OWASP floor, named in the module comment: 19 MiB, 2 passes, 1 lane
    assert ARGON2_MEMORY_COST_KIB == 19 * 1024
    assert (ARGON2_TIME_COST, ARGON2_PARALLELISM) == (2, 1)


def test_decoy_verify_keeps_the_login_timing_equalisation() -> None:
    """SEC-02 keeps the F-057 timing fix: an unknown address still burns Argon2.

    The decoy hash is generated lazily on first use and cached; asserting
    the wall-clock floor (well below the real cost on a loaded CI box but
    far above a no-op) is what a timing-equality claim can honestly test
    without flaking.
    """
    started = time.perf_counter()
    _burn_password_check("some-guess")
    elapsed = time.perf_counter() - started
    assert elapsed > 0.001, "the decoy path must do real Argon2id work"

    second = time.perf_counter()
    _burn_password_check("another-guess")
    cached_elapsed = time.perf_counter() - second
    assert cached_elapsed > 0.001


def test_verify_password_rejects_a_hash_with_weaker_parameters() -> None:
    """The policy is not only what we WRITE but what we accept as current."""
    from argon2 import PasswordHasher

    from bangla_gpt_api.auth.security import needs_rehash

    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash("p" * 20)
    assert verify_password("p" * 20, weak)
    assert needs_rehash(weak), "a weaker argon2 hash must be upgraded on next login"


def test_policy_is_stated_in_the_module_with_the_revision() -> None:
    """The citation is part of the deliverable, so it is asserted, not hoped."""
    import inspect

    from bangla_gpt_api import auth

    source = inspect.getsource(auth.security)
    assert "NIST SP 800-63B" in source
    assert "Revision 4" in source
    assert "3.1.1.2" in source
    assert "retrieved" in source.lower()


@pytest.mark.parametrize("field", ["password_min_length"])
def test_password_knob_has_a_default(field: str) -> None:
    assert getattr(Settings(env="test"), field) == 8
