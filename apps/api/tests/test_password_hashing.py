"""Password hashing policy and upgrade path (AUD-0023).

Before this change passwords were hashed with PBKDF2-HMAC-SHA256 at 200,000
iterations, which is below OWASP's 600,000-iteration floor for that algorithm
and far below the recommendation to use Argon2id (19 MiB, t=2, p=1). New
hashes are now Argon2id, legacy pbkdf2_sha256 hashes still verify, and a
successful login upgrades a legacy (or weak-parameter) hash in place.

These tests pin the parameters, not just the behaviour, so a future "tidy-up"
that quietly lowers the cost is caught.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.auth.security import (
    hash_password,
    needs_rehash,
    verify_password,
)
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "Str0ngRootPassw0rd!"


def _legacy_hash(password: str, iterations: int = 200_000) -> str:
    """Reproduce the pre-AUD-0023 pbkdf2_sha256 format."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def test_new_hashes_are_argon2id_at_owasp_parameters() -> None:
    stored = hash_password("correct-horse-battery")
    assert stored.startswith("$argon2id$")
    # The encoded hash carries its parameters; assert the exact policy so a
    # regression to weaker costs fails here, not in production.
    assert "m=19456,t=2,p=1" in stored
    assert verify_password("correct-horse-battery", stored)
    assert not verify_password("wrong-password", stored)


def test_argon2_hash_is_salted() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_legacy_pbkdf2_hashes_still_verify() -> None:
    legacy = _legacy_hash("legacy-secret")
    assert verify_password("legacy-secret", legacy)
    assert not verify_password("not-the-secret", legacy)


def test_corrupt_and_foreign_hashes_are_rejected() -> None:
    for bad in ("not-a-valid-hash", "md5$1$aa$bb", "$argon2id$broken"):
        assert not verify_password("x", bad)


def test_needs_rehash_flags_legacy_and_weak_argon2() -> None:
    assert needs_rehash(_legacy_hash("x")) is True
    assert needs_rehash(hash_password("x")) is False
    # An Argon2id hash produced with weaker parameters than current policy.
    weak = hash_password("x").replace("m=19456,t=2,p=1", "m=1024,t=1,p=1")
    assert needs_rehash(weak) is True


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/hash.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/hash.db")
    yield client, conn
    conn.close()


def test_login_upgrades_a_legacy_hash_in_place(env) -> None:
    """A pbkdf2 user signs in, and the stored hash becomes Argon2id."""
    client, conn = env
    email = "legacy@hash.test"
    legacy = _legacy_hash("LegacyPassw0rd!")
    conn.execute(
        "INSERT INTO users (email, password_hash, role, must_change_password, "
        "email_verified, created_at) "
        "VALUES (?, ?, 'student', 0, 1, '2026-01-01 00:00:00')",
        (email, legacy),
    )
    conn.commit()

    res = client.post("/auth/login", json={"email": email, "password": "LegacyPassw0rd!"})
    assert res.status_code == 200, res.text

    stored = conn.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()[0]
    assert stored.startswith("$argon2id$"), "login must upgrade the hash to Argon2id"
    assert verify_password("LegacyPassw0rd!", stored)


def test_login_leaves_a_current_hash_unchanged(env) -> None:
    client, conn = env
    email = "modern@hash.test"
    current = hash_password("ModernPassw0rd!")
    conn.execute(
        "INSERT INTO users (email, password_hash, role, must_change_password, "
        "email_verified, created_at) "
        "VALUES (?, ?, 'student', 0, 1, '2026-01-01 00:00:00')",
        (email, current),
    )
    conn.commit()

    assert (
        client.post("/auth/login", json={"email": email, "password": "ModernPassw0rd!"}).status_code
        == 200
    )
    stored = conn.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()[0]
    assert stored == current
