"""CORS configuration."""

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url


def make_client(**overrides):
    settings = Settings(
        env="test",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        **overrides,
    )
    return TestClient(create_app(settings))


def test_preflight_from_allowed_origin(tmp_path) -> None:
    client = make_client(
        database_url=engine_url(tmp_path, "cors"), allowed_origins="https://app.example.edu.bd"
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
        database_url=engine_url(tmp_path, "cors"), allowed_origins="https://app.example.edu.bd"
    )
    res = client.get(
        "/health",
        headers={"Origin": "https://evil.example.com"},
    )
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers


def test_no_cors_headers_when_unconfigured(tmp_path) -> None:
    client = make_client(database_url=engine_url(tmp_path, "cors"))
    res = client.get("/health", headers={"Origin": "https://anything.example.com"})
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers


def test_multiple_allowed_origins(tmp_path) -> None:
    client = make_client(
        database_url=engine_url(tmp_path, "cors"),
        allowed_origins="https://a.example.edu.bd, https://b.example.edu.bd",
    )
    for origin in ("https://a.example.edu.bd", "https://b.example.edu.bd"):
        res = client.options(
            "/auth/login",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert res.headers["access-control-allow-origin"] == origin


def test_rate_limited_response_is_readable_cross_origin(tmp_path) -> None:
    """A 429 must carry CORS headers, or the SPA sees an opaque network error.

    The rate-limit middleware short-circuits before the route handler, so it
    only reaches the browser readable if CORSMiddleware wraps it.
    """
    client = make_client(
        database_url=engine_url(tmp_path, "cors"),
        allowed_origins="https://app.example.edu.bd",
        rate_limit_login_per_minute=1,
    )
    headers = {"Origin": "https://app.example.edu.bd"}
    first = client.post("/auth/login", json={"email": "a@b.c", "password": "x"}, headers=headers)
    second = client.post("/auth/login", json={"email": "a@b.c", "password": "x"}, headers=headers)

    assert first.status_code != 429, "first attempt must be allowed by a limit of 1/min"
    assert second.status_code == 429
    assert second.headers.get("access-control-allow-origin") == "https://app.example.edu.bd"
    # The structured payload the web client maps to a friendly message.
    assert second.json()["detail"]["code"] == "rate_limited"


def test_oversized_body_response_is_readable_cross_origin(tmp_path) -> None:
    """A 413 from the body-size guard must also carry CORS headers."""
    client = make_client(
        database_url=engine_url(tmp_path, "cors"),
        allowed_origins="https://app.example.edu.bd",
        max_body_bytes=200,
    )
    res = client.post(
        "/auth/login",
        content=b"x" * 5000,
        headers={"Origin": "https://app.example.edu.bd", "Content-Type": "application/json"},
    )
    assert res.status_code == 413
    assert res.headers.get("access-control-allow-origin") == "https://app.example.edu.bd"


def test_preflight_does_not_consume_rate_limit_budget(tmp_path) -> None:
    """Preflights are not user attempts and must not count against the limit.

    Browser clients send an OPTIONS preflight before each non-simple request,
    so counting it halves the real budget the operator configured.
    """
    client = make_client(
        database_url=engine_url(tmp_path, "cors"),
        allowed_origins="https://app.example.edu.bd",
        rate_limit_login_per_minute=2,
    )
    preflight = client.options(
        "/auth/login",
        headers={
            "Origin": "https://app.example.edu.bd",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 200
    statuses = [
        client.post(
            "/auth/login",
            json={"email": "a@b.c", "password": "x"},
            headers={"Origin": "https://app.example.edu.bd"},
        ).status_code
        for _ in range(3)
    ]
    assert statuses[2] == 429, "the third login attempt must be the one that trips a 2/min limit"
    assert statuses[:2] == [401, 401]
