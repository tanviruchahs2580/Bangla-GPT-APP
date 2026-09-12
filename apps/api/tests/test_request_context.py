"""S4.1 Education Context Engine: one context for every AI call, logged safely.

Covers the PASS-WHEN trio: (a) tutor ask/chat/stream and the three teacher
generators are all context-driven, (b) every provider call carries the
trusted [education-context] block, (c) the log line contains the context --
counts and ids only, never message content (R11). System prompts must stay
byte-identical (R5).
"""

import json
import logging
import sqlite3

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.services.context import (
    RequestContext,
    history_summary,
    snapshot_mastery,
)
from bangla_gpt_api.services.generators.chapter_content import CONTENT_SYSTEM_PROMPT
from bangla_gpt_api.services.generators.lesson_plan import LESSON_SYSTEM_PROMPT
from bangla_gpt_api.services.generators.question_paper import QP_SYSTEM_PROMPT
from bangla_gpt_api.services.tutor import SYSTEM_PROMPT

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
SENTINEL = "SENTINEL-PII-must-never-reach-logs"

# 'kosh kima?' ('what is a cell?') -- sample class-6 science corpus question.
KOISH_QUESTION = "কোষ কী?"
# 'kosh' -- chapter title in the same corpus.
KOISH = "কোষ"
# 'bigganit' (algebra) -- used as a concept/chapter name.
ALGEBRA = "বীজগণিত"


class _RecordingProvider:
    """MockLLMProvider wrapper that captures every prompt/system pair."""

    name = "recording-mock"

    def __init__(self) -> None:
        self.inner = MockLLMProvider()
        self.calls: list[tuple[str, str | None]] = []

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return await self.inner.generate(prompt, system=system)

    async def stream(self, prompt: str, *, system: str | None = None):
        self.calls.append((prompt, system))
        async for delta in self.inner.stream(prompt, system=system):
            yield delta


def _app(monkeypatch, tmp_path, db_name: str = "ctx.db") -> tuple[TestClient, _RecordingProvider]:
    provider = _RecordingProvider()
    # Mock BOTH main and fast providers so every route goes through the recorder.
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    monkeypatch.setattr("bangla_gpt_api.main.get_fast_provider", lambda s: provider)
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/{db_name}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings)), provider


def _register_login(client: TestClient, email: str, role: str) -> dict[str, str]:
    body = {
        "email": email,
        "password": PASSWORD,
        "name": "Tester",
        "role": role,
    }
    if role == "student":
        body["guardian_consent"] = True
        body["class_level"] = 6
    res = client.post("/auth/register", json=body)
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class _LogHandler(logging.Handler):
    """Collect raw log lines: json_log handlers hang off the app logger and
    may not propagate, so caplog cannot be relied on here."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


# --- unit: pure context primitives -----------------------------------------


def test_render_block_is_deterministic_structured_header() -> None:
    ctx = RequestContext(
        role="student",
        class_level=6,
        subject="science",
        chapter_id=KOISH,
        goal="question",
        history_summary="2 turns",
        mastery_snapshot={"a": 42.4},
    )
    block = ctx.render_block()
    assert block.startswith("[education-context]")
    assert block.rstrip().endswith("[/education-context]")
    assert "role=student class_level=6" in block
    assert "subject=science" in block
    assert f"chapter={KOISH}" in block
    assert "goal=question" in block
    assert "history=2 turns" in block
    assert "mastery_recent=a=42" in block
    assert ctx.render_block() == block  # frozen dataclass -> byte-stable
    empty = RequestContext(role="admin", class_level=9).render_block()
    assert "subject=any" in empty and "chapter=any" in empty and "mastery_recent=none" in empty


def test_log_fields_are_counts_ids_only_and_json_safe() -> None:
    ctx = RequestContext(
        role="student",
        class_level=6,
        subject="science",
        goal="question",
        mastery_snapshot={"c1": 10.0, "c2": 20.0},
    )
    fields = ctx.log_fields()
    assert fields["ai_role"] == "student"
    assert fields["ai_goal"] == "question"
    assert fields["ai_mastery_concepts"] == 2  # count, never concept names
    json.dumps(fields)  # must be JSON-serialisable for json_log


def test_history_summary_counts_and_strategy_only() -> None:
    assert history_summary(0) == "0 turns"
    assert history_summary(6) == "6 turns"
    assert history_summary(4, "example") == "4 turns, strategy=example"


def test_snapshot_mastery_weakest_first_capped_rounded() -> None:
    snap = snapshot_mastery({"z": 90.0, "a": 30.0, "b": None, "c": 60.56, "d": 10.0}, limit=3)
    assert snap == {"d": 10.0, "a": 30.0, "c": 60.6}  # None skipped, weak first, cap+round
    assert list(snap) == sorted(snap, key=lambda k: snap[k])


# --- wiring: tutor paths -----------------------------------------------------


def test_tutor_ask_prompt_carries_context_system_unchanged(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path)
    headers = _register_login(client, "s1@ctx.test", "student")
    res = client.post(
        "/tutor/ask",
        json={"question": KOISH_QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["grounded"] is True
    assert len(provider.calls) == 1
    prompt, system = provider.calls[0]
    assert prompt.startswith("[education-context]")
    assert "role=student class_level=6" in prompt
    assert "goal=question" in prompt
    assert "mastery_recent=none" in prompt  # student has no attempt history yet
    assert prompt.index("[education-context]") < prompt.index("<evidence>")
    assert system == SYSTEM_PROMPT  # R5: byte-identical secrecy prompt untouched


def test_ai_request_context_log_has_context_but_never_message_content(
    monkeypatch, tmp_path
) -> None:
    client, _provider = _app(monkeypatch, tmp_path, "ctx-log.db")
    headers = _register_login(client, "s2@ctx.test", "student")
    handler = _LogHandler()
    app_logger = logging.getLogger("bangla_gpt_api")
    app_logger.addHandler(handler)
    try:
        client.post(
            "/tutor/ask",
            json={"question": f"{KOISH} {SENTINEL}", "class_level": 6, "subject": "science"},
            headers=headers,
        )
    finally:
        app_logger.removeHandler(handler)
    lines = []
    for message in handler.messages:
        try:
            payload = json.loads(message)
        except ValueError:
            continue
        if payload.get("event") == "ai_request_context":
            lines.append(payload)
    assert len(lines) == 1
    line = lines[0]
    assert line["ai_role"] == "student"
    assert line["ai_class_level"] == 6
    assert line["ai_subject"] == "science"
    assert line["ai_goal"] == "question"
    assert SENTINEL not in "\n".join(handler.messages)  # R11: content never reaches logs


def test_mastery_snapshot_reaches_prompt_from_attempt_history(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path, "ctx-mastery.db")
    headers = _register_login(client, "s3@ctx.test", "student")
    conn = sqlite3.connect(tmp_path / "ctx-mastery.db")
    user_id = conn.execute("SELECT id FROM users WHERE email='s3@ctx.test'").fetchone()[0]
    student_id = conn.execute("SELECT id FROM students WHERE user_id=?", (user_id,)).fetchone()[0]
    att = conn.execute(
        "INSERT INTO quiz_attempts (student_id, class_level, status, quiz_json, created_at)"
        " VALUES (?, 6, 'graded', '[]', datetime('now'))",
        (student_id,),
    )
    # KOISH weak (1/4 -> 25%), ALGEBRA strong (2/2 -> 100%).
    rows = [(0, False), (1, False), (2, False), (3, True)] + [(4, True), (5, True)]
    for seq, ok in rows:
        chapter = KOISH if seq < 4 else ALGEBRA
        conn.execute(
            "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
            " is_correct, chapter, book) VALUES (?, ?, 'q', 0, 0, ?, ?, 'b')",
            (att.lastrowid, seq, 1 if ok else 0, chapter),
        )
    conn.commit()
    conn.close()
    res = client.post(
        "/tutor/ask",
        json={"question": KOISH_QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200
    prompt, _system = provider.calls[-1]
    assert "mastery_recent=" in prompt
    assert f"{KOISH}=25" in prompt  # weakest chapter present in the trusted block


def test_chat_reteach_goal_and_history_count(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path, "ctx-chat.db")
    headers = _register_login(client, "s4@ctx.test", "student")
    conv = client.post("/tutor/conversations", json={}, headers=headers)
    assert conv.status_code == 201, conv.text
    cid = conv.json()["id"]
    url = f"/tutor/conversations/{cid}/messages"
    first = client.post(
        url, json={"message": KOISH_QUESTION, "subject": "science"}, headers=headers
    )
    assert first.status_code == 200, first.text
    assert provider.calls[0][0].startswith("[education-context]")
    assert "history=0 turns" in provider.calls[0][0]
    assert provider.calls[0][1] == SYSTEM_PROMPT
    second = client.post(
        url,
        json={"message": KOISH_QUESTION, "subject": "science", "reteach": True},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    prompt, system = provider.calls[1]
    assert "goal=reteach" in prompt
    assert "history=2 turns" in prompt  # user+assistant from the first turn
    assert "strategy=" in prompt
    assert system == SYSTEM_PROMPT


def test_stream_message_carries_context(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path, "ctx-stream.db")
    headers = _register_login(client, "s5@ctx.test", "student")
    conv = client.post("/tutor/conversations", json={}, headers=headers)
    cid = conv.json()["id"]
    res = client.post(
        f"/tutor/conversations/{cid}/messages/stream",
        json={"message": KOISH_QUESTION, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200
    assert "event: done" in res.text
    assert len(provider.calls) == 1
    prompt, system = provider.calls[0]
    assert prompt.startswith("[education-context]")
    assert "role=student" in prompt and "goal=chat" in prompt
    assert system == SYSTEM_PROMPT


# --- wiring: the three teacher generators -------------------------------------


def test_all_three_generators_are_context_driven(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path, "ctx-gen.db")
    headers = _register_login(client, "t1@ctx.test", "teacher")

    res = client.post(
        "/teacher/content/generate",
        json={"class_level": 6, "subject": "science", "chapter": KOISH},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    prompt, system = provider.calls[-1]
    assert prompt.startswith("[education-context]")
    assert "role=teacher" in prompt and "goal=chapter_content" in prompt
    assert f"chapter={KOISH}" in prompt
    assert system == CONTENT_SYSTEM_PROMPT

    res = client.post(
        "/teacher/lesson-plans",
        json={"class_level": 6, "subject": "science", "chapter": KOISH, "minutes": 35},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    prompt, system = provider.calls[-1]
    assert "goal=lesson_plan" in prompt and "role=teacher" in prompt
    assert system == LESSON_SYSTEM_PROMPT

    res = client.post(
        "/teacher/qpapers",
        json={
            "class_level": 6,
            "subject": "science",
            "chapters": [KOISH],
            "exam_type": "final",
            "marks": 10,
            "duration_min": 60,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    prompt, system = provider.calls[-1]
    assert prompt.startswith("[education-context]")
    assert "goal=question_paper" in prompt
    assert system == QP_SYSTEM_PROMPT
