"""Baseline security headers on API responses."""

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url


def test_security_headers_present(tmp_path) -> None:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "headers"),
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    client = TestClient(create_app(settings))
    res = client.get("/health")
    assert res.status_code == 200
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "no-referrer"
