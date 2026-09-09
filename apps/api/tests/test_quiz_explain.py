"""S1.7 — quiz explain loop: context payload composition + /tutor/ask integration."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import QuizExplainContext
from bangla_gpt_api.services.quiz_explain import quiz_explain_instruction


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/explain.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def student(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "email": "ex@example.com",
            "password": "supersecret1",
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    login = client.post("/auth/login", json={"email": "ex@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


CTX = {
    "question": "কোষের একক কী?",
    "options": ["টাগার", "কোষ", "তালা", "পাতা"],
    "correct_index": 1,
    "user_answer": 0,
    "chapter": "কোষ",
}


def test_explain_instruction_contains_full_context() -> None:
    block = quiz_explain_instruction(QuizExplainContext(**CTX))
    assert "কোষের একক কী?" in block
    assert "কোষ" in block  # chapter line
    # Every option labelled (ক–ঘ).
    for opt in CTX["options"]:
        assert opt in block
    # Student's wrong answer and the correct one are both named.
    assert "শিক্ষার্থীর উত্তর: ক) টাগার" in block
    assert "সঠিক উত্তর: খ) কোষ" in block


def test_explain_instruction_handles_unanswered() -> None:
    block = quiz_explain_instruction(QuizExplainContext(**{**CTX, "user_answer": -1}))
    assert "শিক্ষার্থীর উত্তর: (কোনো উত্তর দেয়নি)" in block
    assert "সঠিক উত্তর: খ) কোষ" in block


def test_ask_with_explain_returns_grounded_answer(client: TestClient, student: dict) -> None:
    """End-to-end explain loop: quiz → wrong answer → explain the review item."""
    qz = client.post(
        "/quizzes",
        headers=student,
        json={"student_id": 1, "class_level": 6, "subject": "science", "num_questions": 3},
    )
    assert qz.status_code == 200, qz.text
    quiz = qz.json()
    sub = client.post(
        f"/quizzes/{quiz['attempt_id']}/submit",
        headers=student,
        json={"answers": [1] * len(quiz["questions"])},
    )
    assert sub.status_code == 200, sub.text
    review = sub.json()["review"]
    item = review[0]
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={
            "question": "এই কুইজ প্রশ্নের ব্যাখ্যা দাও",
            "class_level": 6,
            "subject": "science",
            "explain": {
                "question": item["question_text"],
                "options": item["options"],
                "correct_index": item["correct_index"],
                "user_answer": item["chosen"],
                "chapter": item["chapter"],
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grounded"] is True, body
    assert body["sources"]


def test_ask_rejects_bad_explain_payload(client: TestClient, student: dict) -> None:
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={
            "question": "ব্য়াক্যা দাও",
            "class_level": 6,
            "explain": {**CTX, "user_answer": -2},
        },
    )
    assert r.status_code == 422
    # Without explain, the plain ask still works (field is optional).
    ok = client.post(
        "/tutor/ask",
        headers=student,
        json={"question": "কোষ কি?", "class_level": 6},
    )
    assert ok.status_code == 200
