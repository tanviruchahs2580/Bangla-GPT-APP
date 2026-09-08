"""S1.3 — Unified Learning Workspace: chapter context flows to quiz + tutor."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/workspace.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def student(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "email": "ws@example.com",
            "password": "supersecret1",
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    login = client.post("/auth/login", json={"email": "ws@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _profile_id(client: TestClient, headers: dict) -> int:
    return client.get("/users/me", headers=headers).json()["profile_id"]


def test_quiz_honors_chapter_preselect(client: TestClient, student: dict) -> None:
    """Anুশীলন tab: quiz questions must come from the requested chapter only."""
    pid = _profile_id(client, student)
    r = client.post(
        "/quizzes",
        headers=student,
        json={
            "student_id": pid,
            "class_level": 6,
            "subject": "science",
            "chapter": "কোষ",
            "num_questions": 5,
        },
    )
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["questions"]
    submit = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        headers=student,
        json={"answers": [0] * len(started["questions"])},
    )
    assert submit.status_code == 200
    review = submit.json()["review"]
    assert review, "quiz should have produced reviewed items"
    # Every question must have been drawn from the preselected chapter.
    assert {item["chapter"] for item in review} == {"কোষ"}


def test_tutor_ask_honors_chapter_context(client: TestClient, student: dict) -> None:
    """িজ্ঞাসা tab: grounded answer sources stay inside the requested chapter."""
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={
            "question": "কোষের প্রধান অংশ কী কী?",
            "class_level": 6,
            "subject": "science",
            "chapter": "কোষ",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grounded"] is True
    assert body["sources"], "grounded answer must cite sources"
    assert {s["chapter"] for s in body["sources"]} == {"কোষ"}


def test_chapter_scoped_retrieval_falls_back_when_out_of_scope(
    client: TestClient, student: dict
) -> None:
    """A question about a different chapter still gets an answer via fallback."""
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={
            "question": "বল কাকে বলে?",
            "class_level": 6,
            "subject": "science",
            "chapter": "কোষ",
        },
    )
    assert r.status_code == 200, r.text
    # "বল" is not in the কোষ chapter — the fallback retrieval must still ground it
    # in the correct other chapter rather than refuse.
    body = r.json()
    assert body["grounded"] is True
    assert any(s["chapter"] == "বল ও গতি" for s in body["sources"])
