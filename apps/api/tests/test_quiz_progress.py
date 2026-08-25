import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.quiz import ClozeQuizGenerator

PASSWORD = "supersecret1"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/test.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def _register(
    client: TestClient,
    email: str,
    role: str = "student",
    name: str = "à¦°à¦¾à¦¹à¦¾à¦¤",
    class_level: int | None = 6,
) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": name, "role": role}
    if class_level is not None:
        payload["class_level"] = class_level
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _make_student(client: TestClient, email: str, class_level: int = 6):
    profile = _register(client, email, class_level=class_level)
    headers = _login(client, email)
    return profile["profile_id"], headers


def test_generator_is_deterministic_and_valid() -> None:
    gen = ClozeQuizGenerator(load_sample_corpus())
    first = gen.generate(class_level=6, num=5, seed=42)
    second = gen.generate(class_level=6, num=5, seed=42)
    assert [q.question_text for q in first] == [q.question_text for q in second]
    assert [q.options for q in first] == [q.options for q in second]
    assert first, "expected questions from sample corpus"
    for question in first:
        assert len(question.options) == 4
        assert len(set(question.options)) == 4
        assert 0 <= question.answer_index < 4
        assert "____" in question.question_text


def test_start_quiz_hides_answers(client: TestClient) -> None:
    student_id, headers = _make_student(client, "hide@example.com")
    res = client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 4}, headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["questions"]
    raw = res.text
    assert "answer_index" not in raw and "answer" not in raw.replace("answer_index", "")
    for question in body["questions"]:
        assert set(question.keys()) == {"id", "question_text", "options"}


def test_submit_grades_consistently(client: TestClient) -> None:
    student_id, headers = _make_student(client, "grade@example.com")
    started = client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 3}, headers=headers
    ).json()
    answers = [1] * len(started["questions"])
    res = client.post(
        f"/quizzes/{started['attempt_id']}/submit", json={"answers": answers}, headers=headers
    )
    assert res.status_code == 200
    result = res.json()
    total = len(started["questions"])
    assert result["total"] == total
    assert result["correct"] == sum(1 for r in result["review"] if r["is_correct"])
    expected_pct = round(100.0 * result["correct"] / total, 2)
    assert result["score_pct"] == expected_pct


def test_submit_rejects_mismatch_and_double_grade(client: TestClient) -> None:
    student_id, headers = _make_student(client, "reject@example.com")
    started = client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 3}, headers=headers
    ).json()
    bad = client.post(
        f"/quizzes/{started['attempt_id']}/submit", json={"answers": [0]}, headers=headers
    )
    assert bad.status_code == 400
    good = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=headers,
    )
    assert good.status_code == 200
    again = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=headers,
    )
    assert again.status_code == 400


def test_progress_aggregates_and_flags_weak_chapters(client: TestClient) -> None:
    student_id, headers = _make_student(client, "progress@example.com")
    started = client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 5}, headers=headers
    ).json()
    submitted = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [2] * len(started["questions"])},
        headers=headers,
    )
    assert submitted.status_code == 200

    progress = client.get(f"/students/{student_id}/progress", headers=headers).json()
    assert progress["attempts_graded"] == 1
    assert progress["avg_score_pct"] is not None
    assert progress["by_chapter"]
    asked_total = sum(c["asked"] for c in progress["by_chapter"])
    correct_total = sum(c["correct"] for c in progress["by_chapter"])
    assert asked_total == submitted.json()["total"]
    assert correct_total == submitted.json()["correct"]
    weak = {c["chapter"] for c in progress["by_chapter"] if c["accuracy"] < 60.0}
    assert set(progress["weak_chapters"]) == weak


def test_unknown_student_and_attempt_return_404(client: TestClient) -> None:
    _, headers = _make_student(client, "notfound@example.com")
    assert client.get("/students/999", headers=headers).status_code == 404
    assert client.get("/students/999/progress", headers=headers).status_code == 404
    assert (
        client.post("/quizzes/999/submit", json={"answers": [0]}, headers=headers).status_code
        == 404
    )
    assert client.post("/quizzes", json={"student_id": 999}, headers=headers).status_code == 404
