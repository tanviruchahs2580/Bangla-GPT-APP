"""B5 — CORS configuration."""

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app


def make_client(**overrides):
    settings = Settings(
        env="test",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        **overrides,
    )
    return TestClient(create_app(settings))


def test_preflight_from_allowed_origin(tmp_path) -> None:
    client = make_client(
        database_url=f"sqlite:///{tmp_path}/cors.db", allowed_origins="https://app.example.edu.bd"
    )
    res = client.options(
        "/auth/login",
        headers={
            "Origin": "https://app.example.edu.bd",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "https://app.example.edu.bd"


def test_unknown_origin_gets_no_allow_header(tmp_path) -> None:
    client = make_client(
        database_url=f"sqlite:///{tmp_path}/cors.db", allowed_origins="https://app.example.edu.bd"
    )
    res = client.get(
        "/health",
        headers={"Origin": "https://evil.example.com"},
    )
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers


def test_no_cors_headers_when_unconfigured(tmp_path) -> None:
    client = make_client(database_url=f"sqlite:///{tmp_path}/cors.db")
    res = client.get("/health", headers={"Origin": "https://anything.example.com"})
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers


def test_multiple_allowed_origins(tmp_path) -> None:
    client = make_client(
        database_url=f"sqlite:///{tmp_path}/cors.db",
        allowed_origins="https://a.example.edu.bd, https://b.example.edu.bd",
    )
    for origin in ("https://a.example.edu.bd", "https://b.example.edu.bd"):
        res = client.options(
            "/auth/login",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert res.headers["access-control-allow-origin"] == origin
