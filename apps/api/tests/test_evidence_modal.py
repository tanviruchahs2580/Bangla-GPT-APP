"""S1.6 — source → evidence modal payload: sanitized excerpts, never markup."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/evidence.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def student(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "email": "ev@example.com",
            "password": "supersecret1",
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    login = client.post("/auth/login", json={"email": "ev@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_grounded_sources_carry_sanitized_excerpt(client: TestClient, student: dict) -> None:
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={"question": "কোষের প্ৰধান অংশ কী কী?", "class_level": 6, "subject": "science"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grounded"] is True
    assert body["sources"]
    for src in body["sources"]:
        assert src["excerpt"], "every source must carry evidence for the modal"
        assert len(src["excerpt"]) > 10
        # Delimiter markup must never reach the client (sanitize_evidence applied).
        assert "<evidence>" not in src["excerpt"]
        assert "</evidence>" not in src["excerpt"]
        assert "<user_question>" not in src["excerpt"]


def test_sanitized_excerpt_still_shows_textbook_text(client: TestClient, student: dict) -> None:
    """Sanitization must not blank out the evidence — the modal needs it readable."""
    r = client.post(
        "/tutor/ask",
        headers=student,
        json={"question": "কোষের প্ৰধান অংশ কী কী?", "class_level": 6, "subject": "science"},
    )
    src = r.json()["sources"][0]
    assert "কোষ" in src["excerpt"]
    # Path info the modal shows as breadcrumb.
    assert src["book"] and src["chapter"]
