"""SEC-15: /docs, /redoc and /openapi.json must not be served in production.

FastAPI enables all three by default. Left alone they are served in production
too -- measured against a production-config container before this fix:
/docs 200, /redoc 200, /openapi.json 200 with 158477 bytes describing all 135
routes. They are also the only paths exempt from the per-response nonce CSP,
so the one surface without protection was the one publishing the full map.

These tests build the app twice from the same factory: once in development
(docs must work) and once with a settings object that satisfies every
production boot guard (docs must 404). Nothing is monkeypatched away -- if the
production guard rejects the settings, the test fails loudly instead of
silently testing a different app.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

DEV_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _production_settings(tmp_path, **overrides) -> Settings:
    """Settings that pass enforce_production_safety unchanged."""
    # AUD-0025/0026/0027: deliberately single-process, mock provider.
    os.environ["ALLOW_MOCK_LLM_IN_PRODUCTION"] = "1"
    os.environ["WEB_CONCURRENCY"] = "1"
    base = {
        "env": "production",
        "jwt_secret": "Zk7Qp2XvN8mR4tYcW1bH6jL3sD9fG5aE0uI2oP7xV4qM8nC6rT1wY3zB5",
        "database_url": f"sqlite:///{(tmp_path / 'prod.db').as_posix()}",
        "allowed_origins": "https://app.example.test",
        "admin_email": "admin@example.test",
        "admin_password": "Str0ngAdminPassw0rd!",
        "metrics_require_auth": True,
        "metrics_token": "metric" + "0" * 32,
        "pii_enc_key": "LjDorcxuiR0OrEApp_g6hwfAbKKwimZQOPIvEz1pRhk=",
        "smtp_enabled": True,
        "smtp_host": "smtp.example.test",
        "smtp_from": "noreply@example.test",
        "llm_provider": "mock",
    }
    base.update(overrides)
    return Settings(**base)


def test_production_refuses_to_serve_the_api_reference(tmp_path):
    settings = _production_settings(tmp_path)
    assert settings.is_production, "guard fixture must actually be production"

    with TestClient(create_app(settings)) as client:
        for path in DEV_DOC_PATHS:
            res = client.get(path)
            assert res.status_code == 404, f"{path} returned {res.status_code} in production"
            assert b"swagger" not in res.content.lower()
            assert b'"paths"' not in res.content


def test_development_still_serves_the_api_reference(tmp_path):
    settings = Settings(
        env="development", database_url=f"sqlite:///{(tmp_path / 'dev.db').as_posix()}"
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert schema.json()["paths"], "schema must not be empty in development"


def test_openapi_is_still_generatable_in_production(tmp_path):
    """Closing the HTTP route must not break the schema generator.

    ci.yml asserts on app.openapi()['paths'], so a production app that cannot
    produce a schema at all would break a legitimate consumer.
    """
    app = create_app(_production_settings(tmp_path))
    paths = app.openapi()["paths"]
    assert len(paths) > 100, f"expected the full route set, got {len(paths)}"
    assert "/auth/login" in paths


@pytest.mark.parametrize("env_name", ["staging", "prod", "production"])
def test_every_production_alias_closes_the_reference(tmp_path, env_name):
    settings = _production_settings(tmp_path, env=env_name)
    with TestClient(create_app(settings)) as client:
        assert client.get("/openapi.json").status_code == 404


def test_case_and_whitespace_cannot_evade_the_production_check(tmp_path):
    """config.is_production strips and lowercases; prove the alias set holds."""
    for variant in ("Production", "PRODUCTION", " staging "):
        settings = _production_settings(tmp_path, env=variant)
        assert settings.is_production is True, f"{variant!r} should be production"
        with TestClient(create_app(settings)) as client:
            assert client.get("/openapi.json").status_code == 404
