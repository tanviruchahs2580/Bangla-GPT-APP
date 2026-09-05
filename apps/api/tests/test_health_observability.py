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
    reg = client.post(
        "/auth/register",
        json={
            "email": "obs@example.com",
            "password": "supersecret1",
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/auth/login", json={"email": "obs@example.com", "password": "supersecret1"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    res = client.post("/tutor/ask", json={"question": "কোষ কী?", "class_level": 6}, headers=headers)
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers


def test_metrics_exposes_prometheus_series(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    body = metrics.text
    assert "bgpt_http_requests_total" in body
    assert "bgpt_http_request_duration_seconds" in body
    assert "/health" in body


def test_request_id_propagated_into_json_logs(caplog) -> None:
    """S0.6: RequestId must appear in json_log when set."""
    import logging

    from bangla_gpt_api.logging_config import json_log, request_id_var

    logger = logging.getLogger("test_s06")
    token = request_id_var.set("test-req-12345678")
    try:
        with caplog.at_level(logging.INFO):
            json_log(logger, logging.INFO, "test_event", foo="bar")
        # Find the log record
        assert any("test_event" in rec.message for rec in caplog.records)
        rec = next(r for r in caplog.records if "test_event" in r.message)
        assert '"request_id": "test-req-12345678"' in rec.message
        assert '"foo": "bar"' in rec.message
    finally:
        request_id_var.reset(token)


def test_sentry_noop_when_dsn_absent(tmp_path) -> None:
    """S0.6: Sentry init must not fail when DSN absent."""
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.main import create_app

    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/sentry.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        sentry_dsn=None,
    )
    app = create_app(settings)
    assert app is not None
