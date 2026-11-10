"""DAT-003: the own-data export carries the stored consent IP.

``students.consent_ip`` is written at guardian-consent registration (and
refreshed on re-confirm) as the evidence trail for a child's consent. The
export served ``consent_version``/``consent_at`` and skipped the IP, so a
subject access request answered "what do you hold about me" without one of the
three fields the consent row actually stores.

This is an additive field in the existing student profile section: the version
marker, the section names and every other key must stay exactly as they were.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.gdpr import EXPORT_SCHEMA_VERSION
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "dat003-export"),
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _register_student(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_export_carries_the_students_consent_ip(client: TestClient) -> None:
    """The registered consent evidence -- version, at and ip -- all come back."""
    headers = _register_student(client, "kid-consent-ip@example.test")

    res = client.get("/users/me/export", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["schema_version"] == EXPORT_SCHEMA_VERSION, "additive field only; no version bump"
    profile = body["profile"]
    assert profile["type"] == "student"
    assert profile["consent_version"], "the consent version was already exported"
    assert profile["consent_at"], "the consent timestamp was already exported"
    assert "consent_ip" in profile, "the consent evidence trail must not be answered partially"
    assert profile["consent_ip"] == "testclient", (
        "the exported ip must be the value recorded at registration (the caller's address)"
    )


def test_export_keeps_the_other_sections_untouched(client: TestClient) -> None:
    """Additive means additive: no key renamed, no section moved."""
    headers = _register_student(client, "kid-consent-shape@example.test")
    body = client.get("/users/me/export", headers=headers).json()

    # The v2 section list is asserted by name elsewhere; this pins the two the
    # subject reaches through the same profile dict, plus the user section.
    assert set(body["user"]) == {"id", "email", "role", "created_at"}
    assert set(body["profile"]) == {
        "type",
        "id",
        "name",
        "class_level",
        "learning_prefs",
        "memory_enabled",
        "consent_version",
        "consent_at",
        "consent_ip",
    }


def test_a_student_without_recorded_consent_ip_exports_null(client: TestClient, tmp_path) -> None:
    """A row written before the consent-ip column existed exports honestly."""
    from sqlalchemy import update

    from bangla_gpt_api.db.models import Student
    from bangla_gpt_api.db.session import make_engine, make_session_factory

    headers = _register_student(client, "kid-consent-none@example.test")
    settings = Settings(
        env="test", database_url=engine_url(tmp_path, "dat003-export"), jwt_secret=JWT
    )
    with make_session_factory(make_engine(settings))() as db:
        db.execute(update(Student).values(consent_ip=None))
        db.commit()

    profile = client.get("/users/me/export", headers=headers).json()["profile"]
    assert profile["consent_ip"] is None
