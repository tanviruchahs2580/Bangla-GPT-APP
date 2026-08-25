import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/tutor.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def _register_and_login(client: TestClient, email: str = "student@example.com") -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_ask_requires_authentication(client: TestClient) -> None:
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
    )
    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"


def test_ask_grounds_answer_in_curriculum(client: TestClient) -> None:
    headers = _register_and_login(client)
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["grounded"] is True
    assert body["sources"], "grounded answers must cite sources"
    assert body["sources"][0]["book"] == "বিজ্ঞান"
    assert "[mock]" in body["answer"]


def test_ask_refuses_out_of_domain_question(client: TestClient) -> None:
    headers = _register_and_login(client)
    res = client.post(
        "/tutor/ask",
        json={
            "question": "গত বিশ্বকাপ ফুটবল ফাইনালে কোন দল জিতেছিল?",
            "class_level": 6,
            "subject": "science",
        },
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["grounded"] is False
    assert body["sources"] == []
    assert "সম্ভব নয়" in body["answer"]


def test_ask_validates_payload(client: TestClient) -> None:
    headers = _register_and_login(client)
    res = client.post("/tutor/ask", json={"question": "কোষ কী?", "class_level": 0}, headers=headers)
    assert res.status_code == 422
    res = client.post("/tutor/ask", json={"question": "ab", "class_level": 6}, headers=headers)
    assert res.status_code == 422


def test_rejected_token_is_401_not_500(client: TestClient) -> None:
    _register_and_login(client)
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6},
        headers={"Authorization": "Bearer garbage.token.value"},
    )
    assert res.status_code == 401


def test_ready_still_reports_mock_provider(client: TestClient) -> None:
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "provider": "mock"}


def test_tutor_unavailable_when_provider_unconfigured() -> None:
    settings = Settings(
        env="test",
        llm_provider="nope",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    client = TestClient(create_app(settings))
    res = client.get("/ready")
    assert res.status_code == 503
    headers = _register_and_login(client)
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6},
        headers=headers,
    )
    assert res.status_code == 503
