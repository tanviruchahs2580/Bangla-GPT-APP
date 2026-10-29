"""F-039 / PRIV-02: /events sanitizes prop VALUES, not only prop key names.

The probe behind the finding posted ``{"note": "call me at 01898765432"}`` and
``{"label": "Karim Rahman"}``; both were stored verbatim for the 180-day
analytics window because only key NAMES were filtered. Values now have an
allowlist: primitives pass, strings must be short machine codes. This is the
regression guard (phone number + Bangla name never survive any key) plus the
safe-value side of the contract.
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import text

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers.common import _sanitize_event_props
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"


def _client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "event-values"),
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _student_headers(client: TestClient) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": "kid@example.test",
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "kid@example.test", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _stored_props(tmp_path) -> dict:
    settings = Settings(database_url=engine_url(tmp_path, "event-values"))
    from bangla_gpt_api.db.session import make_engine

    # Read through the engine, not a raw sqlite3 connection: this file runs in
    # the engine-parity lane too (BGPT_TEST_DATABASE_URL), where url.database
    # is a database name rather than a file and a sqlite3 handle cannot open it
    # (measured: 2 failed / 1322 passed on the Postgres job of PR #94).
    engine = make_engine(settings)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT props FROM analytics_events ORDER BY id DESC LIMIT 1")
            ).fetchone()
    finally:
        engine.dispose()
    # SQLite hands back the JSON text; psycopg deserializes JSON columns for us.
    props = row[0]
    return props if isinstance(props, dict) else json.loads(props)


def test_pii_shaped_values_never_survive_any_key(tmp_path) -> None:
    client = _client(tmp_path)
    headers = _student_headers(client)
    res = client.post(
        "/events",
        json={
            "name": "privacy_probe",
            "props": {
                "note": "call me at 01898765432",
                "label": "Karim Rahman",
                "val": "01712345678",
                "txt": "করিম রহমান",
                "tag": "শিশু",
                "ref": "20261029",
                "contact": "kid@example.test",
                "bidi": "abc\u202edef",
            },
        },
        headers=headers,
    )
    assert res.status_code == 202, res.text
    props = _stored_props(tmp_path)
    dumped = json.dumps(props, ensure_ascii=False)
    for needle in (
        "01898765432",
        "01712345678",
        "Karim",
        "Rahman",
        "করিম",
        "শিশু",
        "20261029",
        "kid@example.test",
        "\u202e",
    ):
        assert needle not in dumped, f"{needle!r} survived sanitization: {dumped}"
    assert props == {}, f"nothing in that payload was machine-code shaped: {props}"


def test_machine_code_values_still_persist(tmp_path) -> None:
    client = _client(tmp_path)
    headers = _student_headers(client)
    res = client.post(
        "/events",
        json={
            "name": "screen_view",
            "props": {
                "screen": "home",
                "page": "quiz_result",
                "mode": "sync",
                "period": "30d",
                "date": "2026-10-29",
                "n": 3,
                "ok": True,
            },
        },
        headers=headers,
    )
    assert res.status_code == 202, res.text
    props = _stored_props(tmp_path)
    assert props["screen"] == "home"
    assert props["page"] == "quiz_result"
    assert props["mode"] == "sync"
    assert props["period"] == "30d"
    # ISO dates carry no six-digit run, so they stay usable as analytics values.
    assert props["date"] == "2026-10-29"
    assert props["n"] == 3 and props["ok"] is True


def test_sanitizer_unit_contract() -> None:
    clean = _sanitize_event_props(
        {
            "screen": "home",
            "label": "Karim Rahman",
            "phone_like": "01712345678",
            "shape": "x" * 60,
            "nested": {"a": 1},
        }
    )
    assert clean == {"screen": "home", "shape": "x" * 40}
