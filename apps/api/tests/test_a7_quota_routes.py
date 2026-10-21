"""AUD-A2-10 / A7-05: every quota control is wired into the tutor routes.

The controls themselves live in services/costs.py and ratelimit.py and are
unit-tested in tests/test_rag2_quota_breakers.py. What this file pins is the
ROUTE wiring the audit found missing (handoff: .audit/handoffs/api-rag2.md,
section 2): a request against the real HTTP surface is refused with the
documented 429 body when

* the deployment-wide daily cost breaker is tripped,
* the school daily breaker is tripped (and only for that school's users),
* the conversation message cap is reached (both chat routes),
* the per-identity in-flight cap is saturated -- and the slot is released
  after the turn, so a refusal does not poison the next request.

The provider is a recording mock behind the main.get_provider seam; the
breakers read the same estimated ledger the routes write.

Bengali literals are Unicode escapes only (repo rule for new files).
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"  # "kosh ki?"


class _RecordingProvider:
    name = "recording-mock"
    supports_vision = False

    def __init__(self) -> None:
        self.inner = MockLLMProvider()

    async def generate(self, prompt, *, system=None, **kwargs):
        return await self.inner.generate(prompt, system=system)

    async def stream(self, prompt, *, system=None, **kwargs):
        async for delta in self.inner.stream(prompt, system=system):
            yield delta


def _app(monkeypatch, tmp_path, db_name: str) -> TestClient:
    provider = _RecordingProvider()
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    monkeypatch.setattr("bangla_gpt_api.main.get_fast_provider", lambda s: provider)
    settings = Settings(
        env="test", database_url=f"sqlite:///{tmp_path}/{db_name}", jwt_secret=SECRET
    )
    return TestClient(create_app(settings))


def _register_login(client: TestClient, email: str) -> dict[str, str]:
    body = {
        "email": email,
        "password": PASSWORD,
        "name": "\u09b6\u09bf\u0995\u09cd\u09b7\u09be\u09b0\u09cd\u09a5\u09c0",
        "role": "student",
        "class_level": 6,
        "guardian_consent": True,
    }
    assert client.post("/auth/register", json=body).status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ask(client: TestClient, headers: dict[str, str]):
    return client.post(
        "/tutor/ask",
        json={"question": QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )


def _new_conversation(client: TestClient, headers: dict[str, str]) -> int:
    res = client.post("/tutor/conversations", json={}, headers=headers)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _seed_usage(db_path, email: str, cost: float) -> None:
    conn = sqlite3.connect(db_path)
    user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    conn.execute(
        "INSERT INTO ai_usage (user_id, route, model, prompt_tokens, completion_tokens,"
        " estimated_cost_usd, created_at) VALUES (?, 'tutor.ask', 'mock', 1, 1, ?,"
        " datetime('now'))",
        (user_id, cost),
    )
    conn.commit()
    conn.close()


def _attach_school(db_path, email: str, school_name: str = "S1") -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO schools (name, code, created_at) VALUES (?, ?, datetime('now'))",
        (school_name, school_name),
    )
    school_id = cur.lastrowid
    conn.execute("UPDATE users SET school_id=? WHERE email=?", (school_id, email))
    conn.commit()
    conn.close()
    return int(school_id)


# ------------------------------------------------------- daily breaker -------
def test_daily_breaker_refuses_tutor_ask_with_the_documented_429(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "1.0")
    client = _app(monkeypatch, tmp_path, "daily.db")
    headers = _register_login(client, "daily@test.local")
    assert _ask(client, headers).status_code == 200  # under budget
    _seed_usage(tmp_path / "daily.db", "daily@test.local", 5.0)
    res = _ask(client, headers)
    assert res.status_code == 429, res.text
    assert res.json()["detail"]["code"] == "ai_daily_budget_exceeded"


def test_daily_breaker_refuses_the_stream_route_before_streaming(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "1.0")
    client = _app(monkeypatch, tmp_path, "daily-stream.db")
    headers = _register_login(client, "daily-stream@test.local")
    conv_id = _new_conversation(client, headers)
    _seed_usage(tmp_path / "daily-stream.db", "daily-stream@test.local", 5.0)
    res = client.post(
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": QUESTION},
        headers=headers,
    )
    assert res.status_code == 429, res.text
    assert res.json()["detail"]["code"] == "ai_daily_budget_exceeded"


# ------------------------------------------------------ school breaker -------
def test_school_breaker_counts_only_that_school(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_DAILY_BUDGET_USD_PER_SCHOOL", "1.0")
    client = _app(monkeypatch, tmp_path, "school.db")
    db = tmp_path / "school.db"
    rich = _register_login(client, "rich-school@test.local")
    other = _register_login(client, "other-school@test.local")
    _attach_school(db, "rich-school@test.local", school_name="Rich")
    _attach_school(db, "other-school@test.local", school_name="Other")
    _seed_usage(db, "rich-school@test.local", 5.0)
    res = _ask(client, rich)
    assert res.status_code == 429, res.text
    assert res.json()["detail"]["code"] == "ai_school_budget_exceeded"
    assert _ask(client, other).status_code == 200  # the other school is fine


# ------------------------------------------------------ conversation cap -----
def test_conversation_cap_refuses_the_next_chat_turn(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_MAX_CONVERSATION_MESSAGES", "2")
    client = _app(monkeypatch, tmp_path, "conv.db")
    headers = _register_login(client, "conv@test.local")
    conv_id = _new_conversation(client, headers)
    first = client.post(
        f"/tutor/conversations/{conv_id}/messages", json={"message": QUESTION}, headers=headers
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/tutor/conversations/{conv_id}/messages", json={"message": QUESTION}, headers=headers
    )
    assert second.status_code == 429, second.text
    assert second.json()["detail"]["code"] == "conversation_limit_reached"
    # A new conversation is unaffected.
    fresh = _new_conversation(client, headers)
    third = client.post(
        f"/tutor/conversations/{fresh}/messages", json={"message": QUESTION}, headers=headers
    )
    assert third.status_code == 200, third.text


def test_conversation_cap_also_guards_the_stream_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_MAX_CONVERSATION_MESSAGES", "2")
    client = _app(monkeypatch, tmp_path, "conv-stream.db")
    headers = _register_login(client, "conv-stream@test.local")
    conv_id = _new_conversation(client, headers)
    first = client.post(
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": QUESTION},
        headers=headers,
    )
    assert first.status_code == 200
    assert "event: done" in first.text
    second = client.post(
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": QUESTION},
        headers=headers,
    )
    assert second.status_code == 429, second.text
    assert second.json()["detail"]["code"] == "conversation_limit_reached"


# ---------------------------------------------------------- in-flight cap ----
def _student_user_id(db_path, email: str) -> int:
    conn = sqlite3.connect(db_path)
    user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    conn.close()
    return int(user_id)


def test_inflight_cap_refuses_a_saturated_identity_and_releases_afterward(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AI_MAX_INFLIGHT_PER_USER", "1")
    client = _app(monkeypatch, tmp_path, "inflight.db")
    headers = _register_login(client, "inflight@test.local")
    user_id = _student_user_id(tmp_path / "inflight.db", "inflight@test.local")

    from bangla_gpt_api.routers.tutor import _concurrency_limiter

    ctx = client.app.state.ctx
    limiter = _concurrency_limiter(ctx)
    key = f"user:{user_id}"
    assert limiter.acquire(key, 1) is True

    refused = _ask(client, headers)
    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"]["code"] == "rate_limited"
    assert refused.headers.get("Retry-After") == "2"

    limiter.release(key)
    assert _ask(client, headers).status_code == 200

    # The successful turn released its own slot again (no leak).
    from bangla_gpt_api.ratelimit import MemoryConcurrencyLimiter

    if isinstance(limiter, MemoryConcurrencyLimiter):
        assert limiter.acquire(key, 1) is True
        limiter.release(key)


def test_inflight_cap_refuses_the_stream_route_before_streaming(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_MAX_INFLIGHT_PER_USER", "1")
    client = _app(monkeypatch, tmp_path, "inflight-stream.db")
    headers = _register_login(client, "inflight-stream@test.local")
    user_id = _student_user_id(tmp_path / "inflight-stream.db", "inflight-stream@test.local")
    conv_id = _new_conversation(client, headers)

    from bangla_gpt_api.routers.tutor import _concurrency_limiter

    limiter = _concurrency_limiter(client.app.state.ctx)
    key = f"user:{user_id}"
    assert limiter.acquire(key, 1) is True
    refused = client.post(
        f"/tutor/conversations/{conv_id}/messages/stream",
        json={"message": QUESTION},
        headers=headers,
    )
    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"]["code"] == "rate_limited"
    limiter.release(key)


def test_inflight_cap_default_is_two_for_chat_and_one_for_ask(monkeypatch, tmp_path) -> None:
    """The documented policy values, resolved with no env and no field."""
    from bangla_gpt_api.routers.tutor import (
        DEFAULT_INFLIGHT_CHAT,
        DEFAULT_INFLIGHT_SINGLE,
        _inflight_limit,
    )

    class _NoField:
        pass

    assert DEFAULT_INFLIGHT_CHAT == 2 and DEFAULT_INFLIGHT_SINGLE == 1
    assert _inflight_limit(_NoField(), default=DEFAULT_INFLIGHT_CHAT) == 2
    assert _inflight_limit(_NoField(), default=DEFAULT_INFLIGHT_SINGLE) == 1
    monkeypatch.setenv("AI_MAX_INFLIGHT_PER_USER", "0")
    assert _inflight_limit(_NoField(), default=DEFAULT_INFLIGHT_CHAT) == 0  # disabled
    monkeypatch.setenv("AI_MAX_INFLIGHT_PER_USER", "junk")
    assert _inflight_limit(_NoField(), default=DEFAULT_INFLIGHT_CHAT) == 2  # warned, default

    class _Field:
        ai_max_inflight_per_user = 4

    assert _inflight_limit(_Field(), default=DEFAULT_INFLIGHT_CHAT) == 4  # field wins
