"""Read-only Learn catalog endpoint tests.

Covers the grounded subject → chapter → concept flow that backs the Learn
frontend. Content is real corpus text, never hallucinated.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.learn import (
    chapter_content,
    list_subjects,
    subject_chapters,
)

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def admin_client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/learn.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient) -> dict:
    res = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_learn_requires_auth(admin_client: TestClient):
    assert admin_client.get("/learn/subjects").status_code in (401, 403)


def test_learn_subjects(admin_client: TestClient):
    headers = _login(admin_client)
    res = admin_client.get("/learn/subjects?class_level=6", headers=headers)
    assert res.status_code == 200
    subjects = {s["subject"] for s in res.json()}
    assert {"science", "mathematics", "bangla"} <= subjects


def test_learn_subject_chapters(admin_client: TestClient):
    headers = _login(admin_client)
    res = admin_client.get("/learn/subjects/science/chapters?class_level=6", headers=headers)
    assert res.status_code == 200
    chapters = res.json()
    assert chapters
    for ch in chapters:
        assert ch["chapter"]
        assert ch["section_count"] >= 1


def test_learn_chapter_content(admin_client: TestClient):
    headers = _login(admin_client)
    chapters = admin_client.get(
        "/learn/subjects/science/chapters?class_level=6", headers=headers
    ).json()
    first = chapters[0]["chapter"]
    res = admin_client.get(
        f"/learn/subjects/science/chapters/{first}?class_level=6", headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["chapter"] == first
    assert body["book"]
    assert body["sections"], "concept authoring must provide grounded content"
    assert any(s["text"].strip() for s in body["sections"])


def test_learn_subject_404(admin_client: TestClient):
    headers = _login(admin_client)
    assert (
        admin_client.get("/learn/subjects/nonexistent/chapters", headers=headers).status_code == 404
    )


def test_learn_chapter_404(admin_client: TestClient):
    headers = _login(admin_client)
    assert (
        admin_client.get(
            "/learn/subjects/science/chapters/%E0%A6%85%E0%A6%9C%E0%A6%BE%E0%A6%A8%E0%A6%BE",
            headers=headers,
        ).status_code
        == 404
    )


def test_learn_service_functions():
    subjects = list_subjects(6)
    assert {s.subject for s in subjects} >= {"science", "mathematics", "bangla"}
    chapters = subject_chapters("science", 6)
    assert chapters
    content = chapter_content("science", 6, chapters[0].chapter)
    assert content is not None
    assert content.sections
