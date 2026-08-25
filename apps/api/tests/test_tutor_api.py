import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(env="test")))


def test_ask_grounds_answer_in_curriculum(client: TestClient) -> None:
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["grounded"] is True
    assert body["sources"], "grounded answers must cite sources"
    assert body["sources"][0]["book"] == "বিজ্ঞান"
    assert "[mock]" in body["answer"]


def test_ask_refuses_out_of_domain_question(client: TestClient) -> None:
    res = client.post(
        "/tutor/ask",
        json={
            "question": "গত বিশ্বকাপ ফুটবল ফাইনালে কোন দল জিতেছিল?",
            "class_level": 6,
            "subject": "science",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["grounded"] is False
    assert body["sources"] == []
    assert "সম্ভব নয়" in body["answer"]


def test_ask_validates_payload(client: TestClient) -> None:
    res = client.post("/tutor/ask", json={"question": "কোষ কী?", "class_level": 0})
    assert res.status_code == 422
    res = client.post("/tutor/ask", json={"question": "ab", "class_level": 6})
    assert res.status_code == 422


def test_ready_still_reports_mock_provider(client: TestClient) -> None:
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "provider": "mock"}


def test_tutor_unavailable_when_provider_unconfigured() -> None:
    client = TestClient(create_app(Settings(llm_provider="nope")))
    res = client.get("/ready")
    assert res.status_code == 503
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6},
    )
    assert res.status_code == 503
