"""S1.4 — Structured AI response: sectioned answer contract + no prompt leak."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.answer_structure import (
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
)
from bangla_gpt_api.services.tutor import SYSTEM_PROMPT


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/structured.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def student(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "email": "sa@example.com",
            "password": "supersecret1",
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    login = client.post("/auth/login", json={"email": "sa@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_system_prompt_declares_all_sections() -> None:
    """The golden-sample section labels are declared by the system prompt itself."""
    for label in (SECTION_SIMPLE, SECTION_EXAMPLE, SECTION_POINTS, SECTION_CHECK):
        assert label in SYSTEM_PROMPT


def test_groundled_answer_shows_every_section(client: TestClient, student: dict) -> None:
    """Golden sample: a grounded answer contains all four sections in order."""
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={"question": "কোষের প্রধান অংশ কী কী?", "class_level": 6, "subject": "science"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grounded"] is True
    answer = body["answer"]
    positions = [
        answer.index(s) for s in (SECTION_SIMPLE, SECTION_EXAMPLE, SECTION_POINTS, SECTION_CHECK)
    ]
    assert positions == sorted(positions), "sections must appear in contract order"
    assert "\n- " in answer, "মূল বিষয় must be a bullet list"


def test_ungrounded_refusal_stays_plain(client: TestClient, student: dict) -> None:
    """Refusals are not forced into the sectioned layout (parser must fall back)."""
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={"question": "ফুটবল খেলায় কয়জন খেলে?", "class_level": 6, "subject": "science"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grounded"] is False
    for label in (SECTION_SIMPLE, SECTION_EXAMPLE, SECTION_POINTS, SECTION_CHECK):
        assert label not in body["answer"]


def test_structured_answer_never_leaks_prompt(client: TestClient, student: dict) -> None:
    """Sectioning must not expose the system prompt or evidence markup (AUD-01)."""
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={"question": "কোষের প্রধান অংশ কী কী?", "class_level": 6, "subject": "science"},
    )
    answer = r.json()["answer"]
    for token in ("<evidence>", "</evidence>", "<user_question>", "user_question"):
        assert token not in answer
