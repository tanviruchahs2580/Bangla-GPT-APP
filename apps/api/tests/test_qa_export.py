"""F-040 / PRIV-03: the export carries answer_log, AI-memory prefs and quiz_json.

The erasure cascade deleted ``answer_log`` while the export never showed it, so
a subject access request answered without the child's graded-answer record
(question text + chosen index); ``Student.learning_prefs``/``memory_enabled``
and ``quiz_attempts.quiz_json`` were equally absent. These tests extend the
completeness guard beyond section names to the field coverage those findings
call out. Erasure behaviour is untouched (covered by test_delete_cascade_v2).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AnswerLog, QuizAttempt, Student
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.gdpr import EXPORT_SCHEMA_VERSION
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"

QUIZ_JSON = [{"question_text": "১+১=?", "options": ["১", "২", "৩"], "correct_index": 1}]


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "export-v3"),
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _student(client: TestClient, tmp_path) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": "kid@example.test",
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "kid@example.test", "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_attempt_with_answer_log(tmp_path) -> int:
    settings = Settings(database_url=engine_url(tmp_path, "export-v3"))
    with make_session_factory(make_engine(settings))() as db:
        student = db.execute(select(Student).where(Student.user_id == 1)).scalar_one()
        attempt = QuizAttempt(
            student_id=student.id,
            subject="mathematics",
            class_level=6,
            status="graded",
            total=1,
            correct=0,
            score_pct=0.0,
            quiz_json=QUIZ_JSON,
        )
        db.add(attempt)
        db.flush()
        db.add(
            AnswerLog(
                attempt_id=attempt.id,
                seq=0,
                question_text="১+১=?",
                chosen=0,
                correct_index=1,
                is_correct=False,
                chapter="যোগ",
                book="গণিত",
            )
        )
        db.commit()
        return attempt.id


def test_export_includes_answer_log_prefs_and_quiz_json(client: TestClient, tmp_path) -> None:
    headers = _student(client, tmp_path)
    prefs = client.patch(
        "/students/me/prefs",
        json={
            "learning_prefs": {"explanation_style": "simple", "subject_focus": "science"},
            "memory_enabled": False,
        },
        headers=headers,
    )
    assert prefs.status_code == 200, prefs.text
    attempt_id = _seed_attempt_with_answer_log(tmp_path)

    body = client.get("/users/me/export", headers=headers).json()

    assert body["schema_version"] == EXPORT_SCHEMA_VERSION
    assert "answer_log" in body, "export must carry the child's graded-answer record"
    assert body["profile"]["learning_prefs"] == {
        "explanation_style": "simple",
        "subject_focus": "science",
    }
    assert body["profile"]["memory_enabled"] is False

    attempts = {a["id"]: a for a in body["quiz_attempts"]}
    assert attempts[attempt_id]["quiz_json"] == QUIZ_JSON

    assert len(body["answer_log"]) == 1
    row = body["answer_log"][0]
    assert row["attempt_id"] == attempt_id
    assert row["question_text"] == "১+১=?"
    assert row["chosen"] == 0 and row["correct_index"] == 1 and row["is_correct"] is False
    assert row["chapter"] == "যোগ" and row["book"] == "গণিত"
    assert row["created_at"]


def test_export_answer_log_is_empty_without_attempts(client: TestClient, tmp_path) -> None:
    headers = _student(client, tmp_path)
    body = client.get("/users/me/export", headers=headers).json()
    assert body["answer_log"] == []
    assert body["quiz_attempts"] == []
    # Defaults are exported honestly too.
    assert body["profile"]["memory_enabled"] is True
    assert body["profile"]["learning_prefs"] is None
