"""W2/API-10: every timestamp on the wire is ISO-8601 UTC with a Z (F-063).

The same row serialised as ``...Z`` on the create response (the aware
in-memory default survives ``expire_on_commit=False``) and ``...`` on the
re-read (the naive column comes back), and ECMAScript parses an offset-less
date-time as LOCAL time -- a viewer-offset shift for any client that does not
special-case it. These tests pin the Z on both paths.
"""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import UtcDateTime
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

Z_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "wiretime"),
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student") -> None:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Person", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    assert client.post("/auth/register", json=payload).status_code == 201


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_created_and_reread_timestamps_both_end_in_z(client: TestClient) -> None:
    """Create response and list response agree -- the defect was the split."""
    _register(client, "kid@example.com")
    headers = _headers(client, "kid@example.com")

    created = client.post("/notes", json={"body": "t" * 40}, headers=headers)
    assert created.status_code == 201, created.text
    created_at = created.json()["created_at"]
    assert Z_ISO_RE.match(created_at), created_at

    listed = client.get("/notes", headers=headers)
    assert listed.status_code == 200
    reread = next(r for r in listed.json() if r["id"] == created.json()["id"])
    assert Z_ISO_RE.match(reread["created_at"]), reread["created_at"]
    # Same instant, not merely the same format.
    assert reread["created_at"] == created_at


def test_status_checked_at_still_ends_in_z(client: TestClient) -> None:
    res = client.get("/status")
    assert res.status_code == 200
    assert Z_ISO_RE.match(res.json()["checked_at"]), res.json()["checked_at"]


def test_naive_values_are_read_as_utc() -> None:
    """A naive column value is UTC, not local: the serialiser must say Z."""
    from pydantic import BaseModel

    class Row(BaseModel):
        at: UtcDateTime

    naive = Row(at=datetime(2026, 1, 2, 3, 4, 5))
    aware = Row(at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    assert naive.model_dump(mode="json")["at"] == "2026-01-02T03:04:05Z"
    assert naive.model_dump(mode="json") == aware.model_dump(mode="json")
    # Python-mode dumps keep datetimes for ORM/template use.
    assert isinstance(naive.model_dump()["at"], datetime)

    # Non-UTC offsets normalise to UTC before the Z is appended.
    plus_six = timezone(timedelta(hours=6))
    shifted = Row(at=datetime(2026, 1, 2, 9, 4, 5, tzinfo=plus_six))
    assert shifted.model_dump(mode="json")["at"] == "2026-01-02T03:04:05Z"
