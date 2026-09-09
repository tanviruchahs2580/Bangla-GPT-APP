"""Wave 1: POST /events persists a sanitized analytics row.

PII-ish property keys are dropped, values are truncated, and the audit
trail deliberately has no FK so it survives account deletion.
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "events.db"


@pytest.fixture
def client(db_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _student(client: TestClient) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": "kid@example.com",
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "kid@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _event_rows(db_path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT user_id, name, role, props FROM analytics_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def test_event_persists_with_sanitized_props(client: TestClient, db_path) -> None:
    headers = _student(client)
    res = client.post(
        "/events",
        json={
            "name": "screen_view",
            "props": {
                "screen": "home",
                "visits": 3,
                "fresh": True,
                "long": "x" * 60,
                "email": "kid@example.com",
                "user_name": "Kid",
                "phone": "01700000000",
                "home_address": "Dhaka",
                "token": "abc",
                "secret_code": "1234",
                "password_hint": "nope",
                "question_text": "leak",
                "last_message": "leak",
                "page_content": "leak",
                "answer": "leak",
            },
        },
        headers=headers,
    )
    assert res.status_code == 202, res.text
    assert res.json() == {"status": "accepted"}

    rows = _event_rows(db_path)
    assert len(rows) == 1
    user_id, name, role, props_raw = rows[0]
    assert name == "screen_view"
    assert role == "student"
    assert isinstance(user_id, int) and user_id > 0
    props = json.loads(props_raw)
    # only safe primitives survive; every PII-ish key is gone
    assert set(props) == {"screen", "visits", "fresh", "long"}
    assert props["screen"] == "home"
    assert props["visits"] == 3
    assert props["fresh"] is True
    assert len(props["long"]) == 40
    dumped = json.dumps(props).lower()
    for needle in ("kid@example.com", "01700000000", "dhaka", "leak"):
        assert needle not in dumped


def test_event_accepts_minimal_body(client: TestClient, db_path) -> None:
    headers = _student(client)
    res = client.post("/events", json={"name": "tap"}, headers=headers)
    assert res.status_code == 202, res.text
    rows = _event_rows(db_path)
    assert len(rows) == 1 and json.loads(rows[0][3]) == {}


def test_event_validation_and_auth(client: TestClient) -> None:
    headers = _student(client)
    assert client.post("/events", json={"name": "Bad Name!"}).status_code == 401
    assert client.post("/events", json={"name": "Bad Name!"}, headers=headers).status_code == 422
    # nested non-primitive props fail schema before the sanitizer
    assert (
        client.post(
            "/events", json={"name": "tap", "props": {"a": {"b": 1}}}, headers=headers
        ).status_code
        == 422
    )
