"""F-031: the AI generation kill switch (`AI_GENERATION_ENABLED`).

With the flag off, every student generation surface must answer the standard
refusal envelope (`refused_reason=ai_generation_disabled`, HTTP 200) while
retrieval, ``/search``, ``/ready`` and the non-AI features keep working, and
no ledger row may be reserved for a generation that never reached a provider.
With the default (on) the same ask must take the normal provider path, so an
inverted default cannot pass this file.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
#: "কোষ কী?" -- the question other route tests use against the sample corpus.
QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"
#: "কোষ" -- enough for /search's min_length=1.
SEARCH_TERM = "\u0995\u09cb\u09b7"


def _settings(tmp_path, **over) -> Settings:
    base = dict(env="test", database_url=engine_url(tmp_path, "killswitch"), jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _student_headers(client: TestClient) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": "s@example.com",
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "s@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ledger(tmp_path) -> list[AiUsage]:
    engine = make_engine(_settings(tmp_path))
    with make_session_factory(engine)() as db:
        return list(db.execute(select(AiUsage).order_by(AiUsage.id)).scalars())


def _ask(client: TestClient, headers: dict) -> dict:
    res = client.post(
        "/tutor/ask",
        json={"question": QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_tutor_ask_refuses_with_the_envelope_and_books_no_spend(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, ai_generation_enabled=False)))
    headers = _student_headers(client)
    body = _ask(client, headers)
    assert body["refused_reason"] == "ai_generation_disabled"
    assert body["grounded"] is False
    assert body["answer"], "a refusal must still carry localized copy"
    assert body["confidence"] == 0.0
    assert body["sources"] == []
    assert _ledger(tmp_path) == [], "a paused generation must not reserve a ledger row"


def test_search_and_ready_stay_green_while_generation_is_off(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, ai_generation_enabled=False)))
    headers = _student_headers(client)
    search = client.get("/search", params={"q": SEARCH_TERM}, headers=headers)
    assert search.status_code == 200, search.text
    ready = client.get("/ready")
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"


def test_generation_on_by_default_takes_the_provider_path(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _student_headers(client)
    body = _ask(client, headers)
    assert body["refused_reason"] != "ai_generation_disabled", "default must keep generation on"
    assert len(_ledger(tmp_path)) == 1, "an enabled generation owns its ledger row"


def test_chat_turn_persists_the_refusal_without_ledger_spend(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, ai_generation_enabled=False)))
    headers = _student_headers(client)
    conv = client.post("/tutor/conversations", json={"title": "kill switch"}, headers=headers)
    assert conv.status_code == 201, conv.text
    cid = conv.json()["id"]
    res = client.post(
        f"/tutor/conversations/{cid}/messages",
        json={"message": QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["refused_reason"] == "ai_generation_disabled"
    rows = client.get(f"/tutor/conversations/{cid}/messages", headers=headers).json()
    assert [m["role"] for m in rows] == ["user", "assistant"]
    assert rows[0]["content"] == QUESTION
    assert rows[1]["refused_reason"] == "ai_generation_disabled"
    assert _ledger(tmp_path) == [], "the persisted refusal never reached a provider"


def test_stream_chat_turn_emits_the_refusal_envelope(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, ai_generation_enabled=False)))
    headers = _student_headers(client)
    conv = client.post("/tutor/conversations", json={"title": "kill switch"}, headers=headers)
    cid = conv.json()["id"]
    res = client.post(
        f"/tutor/conversations/{cid}/messages/stream",
        json={"message": QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert "event: token" in res.text
    assert "event: done" in res.text
    assert "ai_generation_disabled" in res.text
    rows = client.get(f"/tutor/conversations/{cid}/messages", headers=headers).json()
    assert [m["role"] for m in rows] == ["user", "assistant"]
    assert rows[1]["refused_reason"] == "ai_generation_disabled"
