"""AUD-B-06: offline breached-password check (NIST SP 800-63B §3.1.1.2).

The B register recorded "no breached-password corpus check": the existing
blocklist refused ``password``/``12345678`` but accepted ``qwertyuiop``,
``Iloveyou2!``, ``asdf1234`` and ``1q2w3e4r`` (reproduced against the
pre-fix HEAD; evidence E-R2-b2-001). ``services/breached_passwords.py`` now
carries an embedded corpus of the most common breached values, checked
offline (no network, no file IO) with the same folding the small blocklist
uses.

Also pins the NIST 800-63B posture this change is part of: length over
composition. The service imposes NO character-class requirements -- a long
all-lowercase passphrase is accepted, a short mixed-class one is still
refused by the length floor the schema owns
(``RegisterRequest.password: min_length=8``).
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.testclient import TestClient

import bangla_gpt_api
from bangla_gpt_api.auth.security import is_common_password
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.breached_passwords import (
    BREACHED_PASSWORDS,
    fold_variants,
    is_breached_password,
)

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "Str0ngPassphrase!234"


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/breached.db",
        jwt_secret=SECRET,
    )


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(_settings(tmp_path)))


# ---------------------------------------------------------------------------
# The list itself
# ---------------------------------------------------------------------------


def test_corpus_is_small_but_real() -> None:
    """A floor, not a replacement for a full corpus -- and not an empty one."""
    assert len(BREACHED_PASSWORDS) >= 400
    # The famous entries must be there in base form; variants are derived.
    assert {"qwertyuiop", "iloveyou2", "monkey123", "asdf1234"} <= BREACHED_PASSWORDS


def test_corpus_source_has_no_duplicate_entries() -> None:
    """Duplicates are cheap to introduce by hand and hide list rot."""
    src = pathlib.Path(
        bangla_gpt_api.services.breached_passwords.__file__  # type: ignore[attr-defined]
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    entries: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == (
            "BREACHED_PASSWORDS"
        ):
            entries = [e.value for e in node.value.args[0].elts]
    assert entries, "BREACHED_PASSWORDS literal not found"
    duplicates = sorted({e for e in entries if entries.count(e) > 1})
    assert duplicates == []


# ---------------------------------------------------------------------------
# The check: case, leet and trailing-junk folding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        "qwertyuiop",
        "QWERTYUIOP",
        "iloveyou2",
        "Iloveyou2!",
        "monkey123",
        "mOnKeY 123",
        "mon-key_123",
        "1q2w3e4r",
        "asdf1234",
        "bangladesh123",
        "trustno1",
    ],
)
def test_breached_candidates_are_caught(candidate: str) -> None:
    assert is_breached_password(candidate), candidate
    # The union check used on the real code paths sees the same value.
    assert is_common_password(candidate), candidate


@pytest.mark.parametrize(
    "candidate",
    [
        "Str0ngPassphrase!234",
        "monsoon-rain-42-mango",
        "correct horse battery",
        "t@chor-ঢাকা-9",
        "twelveletterslong",
        "correcthorsebatterystaple",
        "Banana-River-88-Cloud!",
    ],
)
def test_reasonable_passwords_still_pass(candidate: str) -> None:
    """The stronger check must not reject passphrase-style candidates."""
    assert not is_breached_password(candidate), candidate
    assert not is_common_password(candidate), candidate


def test_fold_variants_is_the_single_normalisation() -> None:
    """auth.security delegates to this function (AUD-B-06 seam)."""
    from bangla_gpt_api.auth.security import _variants

    assert _variants("P@ssw0rd1") == fold_variants("P@ssw0rd1")
    # Sanity on the folding itself (documented examples).
    assert "password" in fold_variants("Password123!")
    assert "monkey" in fold_variants("M0NK3Y")
    assert fold_variants("") == set()


# ---------------------------------------------------------------------------
# The API paths: register / reset / change-password all refuse
# ---------------------------------------------------------------------------


def test_registration_refuses_a_breached_password(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": "breached@example.test",
            "password": "Iloveyou2!",
            "name": "Kid",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert res.status_code == 400, res.text
    body = res.json()["detail"]
    assert body["code"] == "password_too_common"
    assert "breach" in body["message"].lower()


def test_change_password_refuses_a_breached_password(client: TestClient) -> None:
    register = client.post(
        "/auth/register",
        json={
            "email": "changer@example.test",
            "password": PASSWORD,
            "name": "Teacher",
            "role": "teacher",
        },
    )
    assert register.status_code == 201, register.text
    login = client.post("/auth/login", json={"email": "changer@example.test", "password": PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    res = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "qwertyuiop"},
        headers=headers,
    )
    assert res.status_code == 400, res.text
    assert res.json()["detail"]["code"] == "password_too_common"


def test_nist_length_over_composition(client: TestClient) -> None:
    """NIST 800-63B: no character-class rules; long lowercase is fine.

    "twelveletterslong" (17 lowercase letters, no digit/symbol) must register:
    imposing upper+digit+symbol composition is precisely what 800-63B tells
    verifiers not to do. The 8-character floor lives in the schema and is
    exercised by the 422 below.
    """
    ok = client.post(
        "/auth/register",
        json={
            "email": "passphrase@example.test",
            "password": "twelveletterslong",
            "name": "Teacher",
            "role": "teacher",
        },
    )
    assert ok.status_code == 201, ok.text

    too_short = client.post(
        "/auth/register",
        json={
            "email": "short@example.test",
            "password": "Ab1!x",
            "name": "Teacher",
            "role": "teacher",
        },
    )
    assert too_short.status_code == 422, too_short.text
