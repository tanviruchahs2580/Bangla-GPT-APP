import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.quiz import ClozeQuizGenerator


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(env="test", database_url=f"sqlite:///{tmp_path}/test.db")
    return TestClient(create_app(settings))


def _make_student(client: TestClient, name: str = "রাহাত", class_level: int = 6) -> int:
    res = client.post("/students", json={"name": name, "class_level": class_level})
    assert res.status_code == 201
    return res.json()["id"]


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
    student_id = _make_student(client)
    res = client.post(
        "/quizzes",
        json={"student_id": student_id, "num_questions": 4},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["questions"]
    raw = res.text
    assert "answer_index" not in raw and "answer" not in raw.replace("answer_index", "")
    for question in body["questions"]:
        assert set(question.keys()) == {"id", "question_text", "options"}


def test_submit_grades_consistently(client: TestClient) -> None:
    student_id = _make_student(client)
    started = client.post("/quizzes", json={"student_id": student_id, "num_questions": 3}).json()
    answers = [1] * len(started["questions"])
    res = client.post(f"/quizzes/{started['attempt_id']}/submit", json={"answers": answers})
    assert res.status_code == 200
    result = res.json()
    total = len(started["questions"])
    assert result["total"] == total
    assert result["correct"] == sum(1 for r in result["review"] if r["is_correct"])
    expected_pct = round(100.0 * result["correct"] / total, 2)
    assert result["score_pct"] == expected_pct
    for item in result["review"]:
        assert item["is_correct"] == (item["chosen"] == item["correct_index"])


def test_submit_rejects_mismatch_and_double_grade(client: TestClient) -> None:
    student_id = _make_student(client)
    started = client.post("/quizzes", json={"student_id": student_id, "num_questions": 3}).json()
    bad = client.post(f"/quizzes/{started['attempt_id']}/submit", json={"answers": [0]})
    assert bad.status_code == 400
    good = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
    )
    assert good.status_code == 200
    again = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
    )
    assert again.status_code == 400


def test_progress_aggregates_and_flags_weak_chapters(client: TestClient) -> None:
    student_id = _make_student(client)
    started = client.post("/quizzes", json={"student_id": student_id, "num_questions": 5}).json()
    submitted = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [9 % 4 if i % 2 else 0 for i in range(len(started["questions"]))]},
    )
    assert submitted.status_code == 200

    profile = client.get(f"/students/{student_id}")
    assert profile.status_code == 200
    progress = client.get(f"/students/{student_id}/progress").json()
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
    assert client.get("/students/999").status_code == 404
    assert client.get("/students/999/progress").status_code == 404
    assert client.post("/quizzes/999/submit", json={"answers": [0]}).status_code == 404
    assert client.post("/quizzes", json={"student_id": 999}).status_code == 404


def test_student_validation(client: TestClient) -> None:
    short = client.post("/students", json={"name": "আ", "class_level": 6})
    assert short.status_code == 422
    bad_class = client.post("/students", json={"name": "রাহাত", "class_level": 13})
    assert bad_class.status_code == 422
