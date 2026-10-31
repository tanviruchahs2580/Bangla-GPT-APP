"""F-115 (API half): Bangladeshi conventions the API owns.

The audit found the guardian phone accepted any <=32-character string while
only pasted text was recognised as a BD mobile, and that every test fixture
used English names. This file pins the phone validator on the request schema
and drives the shared Bangla-name fixtures (``conftest.BANGLA_NAMES``) through
the mail header encoder, the first rendering path that can mangle a long
matra-heavy name.
"""

from __future__ import annotations

import email
import email.header
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import RegisterRequest, canonical_guardian_phone
from bangla_gpt_api.services import mailer
from conftest import BANGLA_NAMES, engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.mark.parametrize(
    "typed",
    [
        "01712345678",
        "+8801712345678",
        "8801712345678",
        "+880 171 234-5678",
        "017-1234-5678",
        "(017) 1234 5678",
    ],
)
def test_bd_mobiles_canonicalise_to_the_local_form(typed: str) -> None:
    assert canonical_guardian_phone(typed) == "01712345678"


def _is_invalid_phone_error(exc: BaseException) -> bool:
    """The stable error type, from a raw PydanticCustomError or a wrapped one."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return any(item.get("type") == "invalid_phone" for item in errors())
    return getattr(exc, "type", None) == "invalid_phone"


@pytest.mark.parametrize(
    "typed",
    ["029556677", "12345", "+8801712345", "017123456789", "not-a-phone", ""],
)
def test_non_bd_mobile_shapes_are_refused(typed: str) -> None:
    with pytest.raises(Exception) as excinfo:
        canonical_guardian_phone(typed)
    assert _is_invalid_phone_error(excinfo.value)


def test_schema_canonicalises_and_blank_phones_become_none() -> None:
    base = {
        "email": "phone-schema@example.com",
        "password": PASSWORD,
        "name": "অভিভাবক",
        "role": "parent",
    }
    assert RegisterRequest(**base, phone="+880 171 234-5678").phone == "01712345678"
    assert RegisterRequest(**base, phone="").phone is None
    assert RegisterRequest(**base, phone=None).phone is None
    with pytest.raises(Exception) as excinfo:
        RegisterRequest(**base, phone="029556677")
    assert _is_invalid_phone_error(excinfo.value)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "bd_phone"),
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register_parent(client: TestClient, email: str, phone: str):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "অভিভাবক",
            "role": "parent",
            "phone": phone,
        },
    )


def test_registration_stores_the_canonical_phone(client: TestClient) -> None:
    res = _register_parent(client, "guardian-phone@example.com", "+880 171 234-5678")
    assert res.status_code == 201, res.text
    token = client.post(
        "/auth/login", json={"email": "guardian-phone@example.com", "password": PASSWORD}
    ).json()["access_token"]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["phone"] == "01712345678"


def test_registration_refuses_a_non_mobile_phone(client: TestClient) -> None:
    res = _register_parent(client, "guardian-landline@example.com", "029556677")
    assert res.status_code == 422, res.text
    assert "invalid_phone" in res.text


class _CapturingSMTP:
    """SMTP stand-in that records the bytes ``send_message`` would transmit."""

    sent: ClassVar[list[bytes]] = []

    def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
        self.host = host
        self.port = port

    def __enter__(self) -> _CapturingSMTP:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self, context: object | None = None) -> None:
        return None

    def send_message(self, message: email.message.EmailMessage) -> None:
        _CapturingSMTP.sent.append(message.as_bytes())


def test_bangla_fixture_names_survive_the_mail_header(
    bangla_names: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every shared fixture name must round-trip through RFC 2047 exactly:
    the display name is the first place a long matra-heavy name can be split
    or re-encoded incorrectly, and the fixtures exist to catch that."""
    assert bangla_names == list(BANGLA_NAMES)
    _CapturingSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _CapturingSMTP)
    settings = Settings(
        env="test",
        smtp_enabled=True,
        smtp_host="smtp.example.edu.bd",
        smtp_from="no-reply@example.edu.bd",
    )
    for name in bangla_names:
        assert mailer.send_mail(
            settings,
            to=f"{name} <guardian@example.edu.bd>",
            subject="নমুনা",
            body="নমুনা বার্তা",
        )
    assert len(_CapturingSMTP.sent) == len(bangla_names)
    for name, raw in zip(bangla_names, _CapturingSMTP.sent, strict=True):
        parsed = email.message_from_bytes(raw)
        display = str(email.header.make_header(email.header.decode_header(parsed["To"])))
        assert display == f"{name} <guardian@example.edu.bd>"
