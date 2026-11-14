"""BGPT-SEC-001 — TOTP seeds are encrypted at rest.

The MFA verification path used to assign the submitted seed straight to
``users.totp_secret`` (Enterprise V2 audit, E1). These tests pin the new
contract:

* with a key configured, the stored value is versioned ciphertext and never
  the seed itself;
* the challenge path decrypts and verifies against the real seed;
* legacy plaintext rows keep working (passthrough) and are lazily upgraded
  to ciphertext on the next successful challenge;
* a bounded startup sweep encrypts every remaining plaintext row;
* decryption failure is fail-closed and never logs the stored value;
* a keyless (dev) deployment stores plaintext with a loud warning — the
  production boot guard already refuses to run keyless, so production
  always encrypts.
"""

import base64

from fastapi.testclient import TestClient

from bangla_gpt_api.auth.mfa import new_secret, otpauth_uri
from bangla_gpt_api.security import decrypt_totp_secret
from conftest import engine_url

SECRET = "x" * 48
PASSWORD = "Str0ngPassphrase!42"

#: 32-byte random key, base64 — same shape as PII_ENC_KEY in production.
PII_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


def make_client(tmp_path, **overrides) -> TestClient:
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.main import create_app

    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "totpenc"),
        jwt_secret=SECRET,
        pii_enc_key=PII_KEY,
        **overrides,
    )
    return TestClient(create_app(settings))


def make_client_keyless(tmp_path) -> TestClient:
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.main import create_app

    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "totpenc-plain"),
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _enable_mfa(client: TestClient) -> str:
    """Register, sign in, enable MFA; returns the raw seed."""
    reg = client.post(
        "/auth/register",
        json={
            "email": "totp@example.com",
            "password": PASSWORD,
            "name": "Totp",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/auth/login",
        json={"email": "totp@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    seed = new_secret()
    uri = otpauth_uri(seed, "totp@example.com")
    assert uri.startswith("otpauth://")
    code = _current_code(seed)
    res = client.post(
        "/auth/mfa/verify",
        json={"password": PASSWORD, "secret": seed, "code": code},
    )
    assert res.status_code == 200, res.text
    return seed


def _raw_totp(engine, email: str) -> str | None:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT totp_secret FROM users WHERE email = :e"),
            {"e": email},
        ).scalar_one()
    return row


def _current_code(seed: str) -> str:
    """A code the app's own verifier accepts right now (±1 step window)."""
    import time

    from bangla_gpt_api.auth.mfa import _hotp  # noqa: PLC2701 - test-only

    step = int(time.time()) // 30
    return _hotp(seed, step)


def _engine_of(tmp_path, dbname: str = "totpenc"):
    """An engine on the SAME database file the app under test uses."""
    from sqlalchemy import create_engine

    return create_engine(engine_url(tmp_path, dbname))


def test_stored_value_is_ciphertext_not_the_seed(tmp_path) -> None:
    client = make_client(tmp_path)
    seed = _enable_mfa(client)
    stored = _raw_totp(_engine_of(tmp_path), "totp@example.com")
    assert stored is not None
    assert stored.startswith("totp1:"), stored[:12]
    assert seed not in stored
    assert decrypt_totp_secret(stored, PII_KEY) == seed


def test_mfa_challenge_works_with_ciphertext_at_rest(tmp_path) -> None:
    client = make_client(tmp_path)
    seed = _enable_mfa(client)
    # sign in again: login now returns the MFA step-up envelope
    login = client.post(
        "/auth/login",
        json={"email": "totp@example.com", "password": PASSWORD},
    )
    assert login.status_code == 202, login.text
    mfa_token = login.json()["access_token"]
    code = _current_code(seed)
    assert code is not None
    challenge = client.post(
        "/auth/mfa/challenge",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert challenge.status_code == 200, challenge.text
    assert challenge.json().get("access_token")


def test_legacy_plaintext_row_still_verifies_and_lazily_upgrades(tmp_path) -> None:
    client = make_client(tmp_path)
    seed = _enable_mfa(client)
    engine = _engine_of(tmp_path)
    # simulate a pre-fix row: overwrite the ciphertext with the raw seed
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET totp_secret = :s WHERE email = :e"),
            {"s": seed, "e": "totp@example.com"},
        )
    assert _raw_totp(engine, "totp@example.com") == seed

    login = client.post(
        "/auth/login",
        json={"email": "totp@example.com", "password": PASSWORD},
    )
    assert login.status_code == 202
    mfa_token = login.json()["access_token"]
    code = _current_code(seed)
    challenge = client.post(
        "/auth/mfa/challenge",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert challenge.status_code == 200, challenge.text
    # the successful challenge lazily upgraded the stored value
    stored = _raw_totp(engine, "totp@example.com")
    assert stored.startswith("totp1:")
    assert seed not in stored


def test_startup_sweep_encrypts_plaintext_rows(tmp_path) -> None:
    client = make_client(tmp_path)
    seed = _enable_mfa(client)
    engine = _engine_of(tmp_path)
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET totp_secret = :s WHERE email = :e"),
            {"s": seed, "e": "totp@example.com"},
        )
    # a fresh app instance runs the startup sweep over existing rows
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.main import create_app

    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "totpenc"),
        jwt_secret=SECRET,
        pii_enc_key=PII_KEY,
    )
    _ = TestClient(create_app(settings))
    stored = _raw_totp(engine, "totp@example.com")
    assert stored.startswith("totp1:")
    assert decrypt_totp_secret(stored, PII_KEY) == seed


def test_keyless_dev_stores_plaintext_with_warning(tmp_path) -> None:
    import logging

    client = make_client_keyless(tmp_path)
    # create_app's configure_logging clears root handlers (which is where
    # caplog attaches), so capture on the emitting logger itself.
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    security_logger = logging.getLogger("bangla_gpt_api.security")
    capture = _Capture()
    security_logger.addHandler(capture)
    try:
        seed = _enable_mfa(client)
    finally:
        security_logger.removeHandler(capture)
    stored = _raw_totp(_engine_of(tmp_path, "totpenc-plain"), "totp@example.com")
    assert stored == seed  # keyless dev: documented passthrough
    assert any("totp_encrypt_keyless" in m for m in records)


def test_decrypt_failure_is_fail_closed_without_leaking_the_value(tmp_path, caplog) -> None:
    client = make_client(tmp_path)
    seed = _enable_mfa(client)
    engine = _engine_of(tmp_path)
    # corrupt the ciphertext so decryption fails
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET totp_secret = :s WHERE email = :e"),
            {"s": "totp1:garbage-not-a-fernet-token", "e": "totp@example.com"},
        )
    login = client.post(
        "/auth/login",
        json={"email": "totp@example.com", "password": PASSWORD},
    )
    assert login.status_code == 202
    challenge = client.post(
        "/auth/mfa/challenge",
        json={"mfa_token": login.json()["access_token"], "code": "123456"},
    )
    assert challenge.status_code == 503  # fail-closed, coded, not a bypass
    assert "garbage" not in str(caplog.text)
    # and the seed itself never appears in any response
    assert seed not in challenge.text
