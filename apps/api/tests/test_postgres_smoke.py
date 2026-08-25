"""B9 — real-PostgreSQL smoke flows.

Skipped unless ``TEST_DATABASE_URL`` is set (e.g.
``postgresql+psycopg://postgres:postgres@localhost:5432/bgpt_test``).
Exercises the same user journeys the sqlite suite covers, but against the
production database engine, including the alembic-managed schema.
"""

import os

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="TEST_DATABASE_URL not set (Postgres CI job only)"
)

PASSWORD = "supersecret1"


@pytest.fixture
def client() -> TestClient:
    # Per-process database name keeps parallel runs isolated without xdist.
    settings = Settings(
        env="test",
        database_url=f"{DATABASE_URL}_{os.getpid()}",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def test_postgres_full_journey(client: TestClient) -> None:
    register = client.post(
        "/auth/register",
        json={
            "email": "pg-student@example.com",
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert register.status_code == 201, register.text

    login = client.post(
        "/auth/login", json={"email": "pg-student@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    started = client.post(
        "/quizzes",
        json={"student_id": register.json()["profile_id"], "num_questions": 3},
        headers=headers,
    )
    assert started.status_code == 200
    submitted = client.post(
        f"/quizzes/{started.json()['attempt_id']}/submit",
        json={"answers": [0] * len(started.json()["questions"])},
        headers=headers,
    )
    assert submitted.status_code == 200

    progress = client.get(f"/students/{register.json()['profile_id']}/progress", headers=headers)
    assert progress.status_code == 200
    assert progress.json()["attempts_graded"] == 1

    export = client.get("/users/me/export", headers=headers)
    assert export.status_code == 200
    assert export.json()["profile"]["type"] == "student"

    deleted = client.delete("/users/me", headers=headers)
    assert deleted.status_code == 204
