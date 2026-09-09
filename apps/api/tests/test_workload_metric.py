"""Wave 1: GET /teacher/workload -- counts x documented planning minutes."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)

MINUTES = {
    "question_paper": 180,
    "short_test": 40,
    "lesson_plan": 60,
    "worksheet": 45,
    "study_material": 90,
    "answer_key": 30,
    "homework": 20,
    "rubric": 40,
}


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/wl.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _teacher(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_fresh_teacher_sees_all_zero_estimate(client: TestClient) -> None:
    teach = _teacher(client, "fresh@example.com")
    res = client.get("/teacher/workload", headers=teach)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["counts"]) == set(MINUTES)
    assert all(v == 0 for v in body["counts"].values())
    assert all(v == 0 for v in body["minutes_saved"].values())
    assert body["total_minutes_saved"] == 0
    assert body["estimate"] is True
    assert "estimate" in body["methodology"].lower()


def test_counts_and_minutes_follow_generated_artifacts(client: TestClient) -> None:
    teach = _teacher(client, "busy@example.com")
    doc = {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    for _ in range(2):
        assert (
            client.post("/teacher/generate/worksheet", json=doc, headers=teach).status_code == 201
        )
    for kind in ("homework", "rubric"):
        assert client.post(f"/teacher/generate/{kind}", json=doc, headers=teach).status_code == 201
    assert (
        client.post(
            "/teacher/generate/answer_key",
            json={**doc, "questions": ["q1?", "q2?"]},
            headers=teach,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/teacher/lesson-plans",
            json={"class_level": 6, "subject": "science", "chapter": CHAPTER, "minutes": 35},
            headers=teach,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/teacher/qpapers",
            json={
                "class_level": 6,
                "subject": "science",
                "chapters": [CHAPTER],
                "exam_type": "Exam 2026",
                "marks": 10,
                "duration_min": 10,
            },
            headers=teach,
        ).status_code
        == 201
    )

    body = client.get("/teacher/workload", headers=teach).json()
    counts = body["counts"]
    assert counts["worksheet"] == 2
    assert counts["homework"] == 1
    assert counts["rubric"] == 1
    assert counts["answer_key"] == 1
    assert counts["lesson_plan"] == 1
    assert counts["question_paper"] == 1
    assert counts["short_test"] == 0
    assert counts["study_material"] == 0

    minutes = body["minutes_saved"]
    assert minutes["worksheet"] == 2 * MINUTES["worksheet"]
    assert minutes["question_paper"] == MINUTES["question_paper"]
    for kind in MINUTES:
        assert minutes[kind] == counts[kind] * MINUTES[kind]
    assert body["total_minutes_saved"] == sum(minutes.values())
    assert body["total_minutes_saved"] == (2 * 45 + 20 + 40 + 30 + 60 + 180)


def test_workload_is_scoped_per_teacher(client: TestClient) -> None:
    busy = _teacher(client, "busy@example.com")
    doc = {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    assert client.post("/teacher/generate/worksheet", json=doc, headers=busy).status_code == 201
    other = _teacher(client, "idle@example.com")
    body = client.get("/teacher/workload", headers=other).json()
    assert body["total_minutes_saved"] == 0


def test_workload_requires_teacher_role(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": "kid@example.com",
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201
    login = client.post("/auth/login", json={"email": "kid@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/teacher/workload", headers=headers).status_code == 403
    assert client.get("/teacher/workload").status_code == 401
