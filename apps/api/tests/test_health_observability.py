import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/health.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def test_health_live_ready_and_request_id(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["app"] == "Bangla GPT API"
    assert "X-Request-ID" in health.headers
    assert len(health.headers["X-Request-ID"]) >= 8

    rid = "my-req-id-12345678"
    echoed = client.get("/health", headers={"X-Request-ID": rid})
    assert echoed.headers["X-Request-ID"] == rid

    live = client.get("/live")
    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert "X-Request-ID" in live.headers

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "provider": "mock"}


def test_tutor_ask_also_carries_request_id(client: TestClient) -> None:
    res = client.post("/tutor/ask", json={"question": "কোষ কী?", "class_level": 6})
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
