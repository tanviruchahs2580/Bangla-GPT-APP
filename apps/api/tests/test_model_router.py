"""S4.2 AI Model Router: rules-first routing + provider selection + logs.

PASS-WHEN: routing unit tests, and >=70% simple-route share on replayed
sample traffic (replay = real chapter titles from the sample corpus shaped
into the request mix: many short questions, few analytical ones, a slice
of teacher generation calls).
"""

import json
import logging

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.services import router
from bangla_gpt_api.services.router import (
    Route,
    classify,
    fast_eligible,
    route_distribution,
    simple_share,
)

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

# 'ki' (is what / what) -- short question tail, verified Bengali token.
KI = "কী"
# 'kosh' -- verified chapter token from the sample corpus.
KOISH = "কোষ"


class _NamedMock(MockLLMProvider):
    """Mock that remembers its lane name + every prompt it served."""

    def __init__(self, lane: str) -> None:
        super().__init__()
        self.lane = lane
        self.prompts: list[str] = []

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.lane

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return await super().generate(prompt, system=system)

    async def stream(self, prompt: str, *, system: str | None = None):
        self.prompts.append(prompt)
        async for delta in super().stream(prompt, system=system):
            yield delta


class _LogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def events(self, name: str) -> list[dict]:
        out = []
        for message in self.messages:
            try:
                payload = json.loads(message)
            except ValueError:
                continue
            if payload.get("event") == name:
                out.append(payload)
        return out


def _app(monkeypatch, tmp_path, *, fast: bool = True):
    main = _NamedMock("main")
    fast_provider = _NamedMock("fast") if fast else None
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: main)
    monkeypatch.setattr("bangla_gpt_api.main.get_fast_provider", lambda s: fast_provider)
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/router.db",
        jwt_secret=SECRET,
    )
    client = TestClient(create_app(settings))
    return client, main, fast_provider


def _student_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/register",
        json={
            "email": "r@router.test",
            "password": PASSWORD,
            "name": "Router Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "r@router.test", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- unit: rules -------------------------------------------------------------


def test_tool_goals_always_route_to_tool() -> None:
    for goal in ("chapter_content", "lesson_plan", "question_paper", "question_paper_replace"):
        assert classify("যেকোনো", goal=goal) is Route.TOOL


def test_short_facts_are_simple() -> None:
    assert classify(KOISH + " " + KI + "?") is Route.SIMPLE
    assert classify("What is a cell?") is Route.SIMPLE
    assert classify("root", goal="question") is Route.SIMPLE


def test_complex_signals_route_to_main() -> None:
    # too many questions
    assert classify((KOISH + " " + KI + "? ") * 4) is Route.COMPLEX
    # too long
    assert classify("cell " * 60) is Route.COMPLEX
    # Bengali analytical marker (imported constant, no retyping)
    marker = router._COMPLEX_MARKERS[0]
    assert classify(KOISH + " " + marker + " করো") is Route.COMPLEX
    # English marker
    assert classify("Compare plant and animal cells in detail.") is Route.COMPLEX
    # why-and-how multi-hop construction
    assert classify(KOISH + " " + router._MULTI_HOP + " " + KI + "?") is Route.COMPLEX
    # three short sentences = multi-part
    danda = chr(0x964)
    assert classify(KOISH + KI + danda + " বই " + KI + danda + " পাঠ " + KI + danda) is (
        Route.COMPLEX
    )


def test_fast_lane_eligibility() -> None:
    assert fast_eligible(Route.SIMPLE, object()) is True
    assert fast_eligible(Route.SIMPLE, None) is False
    assert fast_eligible(Route.COMPLEX, object()) is False
    assert fast_eligible(Route.TOOL, object()) is False


# --- PASS-WHEN: >=70% simple on replayed sample traffic -----------------------


def _replay_traffic() -> list[tuple[str, str | None]]:
    """Replay of realistic sample traffic. Short fact-recall questions are
    built from REAL chapter titles in the sample corpus; a minority slice is
    analytical, plus the teacher generation calls."""
    chapters = sorted({c.meta.chapter for c in load_sample_corpus() if c.meta.chapter})
    assert chapters, "sample corpus must expose chapter titles"
    traffic: list[tuple[str, str | None]] = []
    # ~74%: short "X ki?"-style fact questions per chapter (student default).
    for chapter in chapters:
        traffic.append((f"{chapter} {KI}?", None))
    # analytical long tail (all MUST classify COMPLEX).
    marker = router._COMPLEX_MARKERS[0]
    traffic += [
        (f"{KOISH} {marker} করো এবং বই এর সাথে মিলিয়ে লেখো", None),
        ("Compare plant and animal cells in detail.", None),
        (f"{KOISH} {KI}? {KOISH} {KI}? {KOISH} {KI}?", None),
        ("cell " * 60, None),
    ]
    # teacher tool calls (generation goals) -- TOOL by rule.
    traffic += [
        (KOISH, "chapter_content"),
        (KOISH, "lesson_plan"),
        (KOISH, "question_paper"),
    ]
    return traffic


def test_replayed_sample_traffic_simple_share_at_least_70pct() -> None:
    traffic = _replay_traffic()
    counts = route_distribution(traffic)
    share = simple_share(counts)
    assert share >= 0.70, f"simple share {share:.2%} < 70% (counts={counts})"
    # sanity: every analytical/tool item really classifies away from SIMPLE
    assert counts["complex"] == 4
    assert counts["tool"] == 3


# --- wiring: provider selection + route/latency/cost logging ------------------


def test_simple_route_uses_fast_provider_and_logs_route(monkeypatch, tmp_path) -> None:
    client, main, fast = _app(monkeypatch, tmp_path)
    headers = _student_headers(client)
    handler = _LogHandler()
    logging.getLogger("bangla_gpt_api").addHandler(handler)
    try:
        res = client.post(
            "/tutor/ask",
            json={"question": KOISH + " " + KI + "?", "class_level": 6, "subject": "science"},
            headers=headers,
        )
    finally:
        logging.getLogger("bangla_gpt_api").removeHandler(handler)
    assert res.status_code == 200, res.text
    assert res.json()["grounded"] is True
    assert len(fast.prompts) == 1 and not main.prompts
    calls = handler.events("ai_call")
    assert len(calls) == 1
    line = calls[0]
    assert line["route"] == "simple"
    assert line["model"] == "fast"
    # per-request route + latency + cost (chars as cost proxy)
    assert line["latency_ms"] >= 0
    assert line["prompt_chars"] > 0 and line["answer_chars"] > 0


def test_complex_route_stays_on_main(monkeypatch, tmp_path) -> None:
    client, main, fast = _app(monkeypatch, tmp_path)
    headers = _student_headers(client)
    handler = _LogHandler()
    logging.getLogger("bangla_gpt_api").addHandler(handler)
    try:
        res = client.post(
            "/tutor/ask",
            json={
                "question": f"{KOISH} {KI}? {KOISH} {KI}? {KOISH} {KI}?",
                "class_level": 6,
                "subject": "science",
            },
            headers=headers,
        )
    finally:
        logging.getLogger("bangla_gpt_api").removeHandler(handler)
    assert res.status_code == 200, res.text
    assert len(main.prompts) == 1 and not fast.prompts
    line = handler.events("ai_call")[-1]
    assert line["route"] == "complex" and line["model"] == "main"


def test_no_fast_provider_keeps_main_on_simple(monkeypatch, tmp_path) -> None:
    client, main, fast = _app(monkeypatch, tmp_path, fast=False)
    assert fast is None
    headers = _student_headers(client)
    res = client.post(
        "/tutor/ask",
        json={"question": KOISH + " " + KI + "?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert len(main.prompts) == 1


def test_generation_calls_route_tool_and_main(monkeypatch, tmp_path) -> None:
    client, main, fast = _app(monkeypatch, tmp_path)
    client.post(
        "/auth/register",
        json={
            "email": "rt@router.test",
            "password": PASSWORD,
            "name": "Router Teacher",
            "role": "teacher",
        },
    )
    login = client.post("/auth/login", json={"email": "rt@router.test", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    res = client.post(
        "/teacher/content/generate",
        json={"class_level": 6, "subject": "science", "chapter": KOISH},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    # TOOL route: never the fast lane, always the main (RAG-carrying) provider
    assert len(main.prompts) == 1 and not fast.prompts
