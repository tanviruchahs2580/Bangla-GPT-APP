"""AUD-A2-18 / A5-05: memory opt-out is honoured end to end, no cross-user leak.

"Memory disable" was code-verified but unproven. Pinned here, through the real
HTTP surface with a prompt-recording provider:

* a student with graded history and learning preferences gets the personalization
  line in the tutor prompt while memory is enabled;
* the moment the stored flag is false, the tutor prompt loses the block entirely
  (the derivation is skipped, not merely hidden) -- and the prompt is
  byte-identical to a no-history prompt for that student;
* another student's weakness facts and style directive never appear in this
  student's prompt, and vice versa (cross-user isolation).
"""

from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
QUESTION = "কোষ কী?"
WEAK_A = "কোষ"
WEAK_B = "বীজগণিত"
STYLE_A = "detailed"
STYLE_B = "simple"


class _RecordingProvider:
    name = "recording-mock"

    def __init__(self) -> None:
        self.inner = MockLLMProvider()
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, system: str | None = None, **_kwargs) -> str:
        self.calls.append(prompt)
        return await self.inner.generate(prompt, system=system)

    async def stream(self, prompt: str, *, system: str | None = None, **_kwargs):
        self.calls.append(prompt)
        async for delta in self.inner.stream(prompt, system=system):
            yield delta


def _app(monkeypatch, tmp_path, db_name: str) -> tuple[TestClient, _RecordingProvider]:
    provider = _RecordingProvider()
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    monkeypatch.setattr("bangla_gpt_api.main.get_fast_provider", lambda s: provider)
    settings = Settings(
        env="test", database_url=f"sqlite:///{tmp_path}/{db_name}", jwt_secret=SECRET
    )
    return TestClient(create_app(settings)), provider


def _register_login(client: TestClient, email: str) -> dict[str, str]:
    body = {
        "email": email,
        "password": PASSWORD,
        "name": "শিক্ষার্থী",
        "role": "student",
        "class_level": 6,
        "guardian_consent": True,
    }
    assert client.post("/auth/register", json=body).status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_student(db_path, email: str, *, weak: str, style: str, memory: int) -> None:
    """Graded history that makes ``weak`` a weak chapter, plus a style pref."""
    conn = sqlite3.connect(db_path)
    user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    student_id = conn.execute("SELECT id FROM students WHERE user_id=?", (user_id,)).fetchone()[0]
    conn.execute(
        "UPDATE students SET memory_enabled=?, learning_prefs=? WHERE id=?",
        (memory, json.dumps({"explanation_style": style}), student_id),
    )
    attempt = conn.execute(
        "INSERT INTO quiz_attempts (student_id, class_level, status, quiz_json, created_at)"
        " VALUES (?, 6, 'graded', '[]', datetime('now'))",
        (student_id,),
    )
    for seq in range(4):
        conn.execute(
            "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
            " is_correct, chapter, book) VALUES (?, ?, 'q', 0, 0, ?, ?, 'b')",
            (attempt.lastrowid, seq, 1 if seq == 3 else 0, weak),
        )
    conn.commit()
    conn.close()


def _ask(client: TestClient, headers: dict[str, str], provider: _RecordingProvider) -> str:
    before = len(provider.calls)
    res = client.post(
        "/tutor/ask",
        json={"question": QUESTION, "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert len(provider.calls) == before + 1
    return provider.calls[-1]


def test_memory_enabled_puts_the_personalization_line_in_the_prompt(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path, "mem-on.db")
    headers = _register_login(client, "mem-on@test.local")
    _seed_student(tmp_path / "mem-on.db", "mem-on@test.local", weak=WEAK_A, style=STYLE_A, memory=1)
    prompt = _ask(client, headers, provider)
    assert "memory: " in prompt
    assert f"weak_chapters={WEAK_A}" in prompt
    assert f"explanation_style={STYLE_A}" in prompt


def test_memory_disabled_removes_the_block_from_the_prompt(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path, "mem-off.db")
    headers = _register_login(client, "mem-off@test.local")
    _seed_student(
        tmp_path / "mem-off.db", "mem-off@test.local", weak=WEAK_A, style=STYLE_A, memory=0
    )
    prompt = _ask(client, headers, provider)
    assert "memory:" not in prompt
    # the trusted education-context block carries nothing learned about the
    # student; the evidence block legitimately names the chapter itself
    context_block = prompt.split("[/education-context]")[0]
    assert WEAK_A not in context_block, "weakness facts must not leak"
    assert "explanation_style" not in prompt
    assert "weak_chapters=" not in prompt
    # the derivation is skipped, so even the mastery snapshot is absent
    assert "mastery_recent=none" in prompt


def test_memory_disable_is_not_just_cosmetic_between_two_turns(monkeypatch, tmp_path) -> None:
    """Same student, same history: flipping the flag changes the prompt."""
    client, provider = _app(monkeypatch, tmp_path, "mem-flip.db")
    headers = _register_login(client, "mem-flip@test.local")
    db = tmp_path / "mem-flip.db"
    _seed_student(db, "mem-flip@test.local", weak=WEAK_A, style=STYLE_A, memory=1)
    with_memory = _ask(client, headers, provider)
    assert "weak_chapters=" in with_memory

    conn = sqlite3.connect(db)
    conn.execute("UPDATE students SET memory_enabled=0")
    conn.commit()
    conn.close()

    without_memory = _ask(client, headers, provider)
    assert with_memory != without_memory
    assert "memory:" not in without_memory
    assert "weak_chapters=" not in without_memory


def test_one_students_memory_never_reaches_another_students_prompt(monkeypatch, tmp_path) -> None:
    client, provider = _app(monkeypatch, tmp_path, "mem-cross.db")
    headers_a = _register_login(client, "student-a@test.local")
    headers_b = _register_login(client, "student-b@test.local")
    db = tmp_path / "mem-cross.db"
    _seed_student(db, "student-a@test.local", weak=WEAK_A, style=STYLE_A, memory=1)
    _seed_student(db, "student-b@test.local", weak=WEAK_B, style=STYLE_B, memory=1)

    prompt_a = _ask(client, headers_a, provider)
    prompt_b = _ask(client, headers_b, provider)

    def memory_line(prompt: str) -> str:
        # The evidence block legitimately mentions chapter names, so the
        # cross-user assertion is scoped to the personalization line itself.
        return next(line for line in prompt.splitlines() if line.startswith("memory:"))

    line_a = memory_line(prompt_a)
    line_b = memory_line(prompt_b)
    assert f"weak_chapters={WEAK_A}" in line_a
    assert WEAK_B not in line_a
    assert f"explanation_style={STYLE_A}" in line_a
    assert STYLE_B not in line_a

    assert f"weak_chapters={WEAK_B}" in line_b
    assert WEAK_A not in line_b
    assert f"explanation_style={STYLE_B}" in line_b
    assert STYLE_A not in line_b
