"""SEC-001: /metrics is never public in production.

- Prod boot refuses when METRICS_REQUIRE_AUTH is false or METRICS_TOKEN unset.
- In prod mode /metrics answers 403 without the token, 200 with it.
- Dev/test keep the open /metrics (documented local behavior).
"""

import os

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app, enforce_production_safety
from conftest import engine_url

SECRET = "test-secret-0123456789abcdef0123456789"


def _prod_settings(**over):
    # AUD-0025/0026/0027: this fixture is deliberately single-process and
    # uses the mock provider, both of which production now refuses.
    os.environ["ALLOW_MOCK_LLM_IN_PRODUCTION"] = "1"
    os.environ["WEB_CONCURRENCY"] = "1"
    base = dict(
        env="production",
        pii_allow_plaintext=False,
        database_url="sqlite://",
        jwt_secret=SECRET,
        admin_email="a@b.com",
        admin_password="longenoughpass1",
        allowed_origins="https://app.example.com",
        pii_enc_key="LjDorcxuiR0OrEApp_g6hwfAbKKwimZQOPIvEz1pRhk=",  # must be a real Fernet key (F-068)
        smtp_enabled=True,
        smtp_host="smtp.example.com",
        smtp_from="noreply@example.com",
    )
    base.update(over)
    return Settings(**base)


def test_prod_boot_refuses_open_metrics() -> None:
    with pytest.raises(RuntimeError, match="METRICS_REQUIRE_AUTH"):
        enforce_production_safety(_prod_settings(metrics_require_auth=False))
    with pytest.raises(RuntimeError, match="METRICS_TOKEN"):
        enforce_production_safety(_prod_settings(metrics_require_auth=True, metrics_token=None))


def test_prod_metrics_gated_by_token(tmp_path) -> None:
    app = create_app(
        _prod_settings(
            database_url=engine_url(tmp_path, "metrics"),
            metrics_require_auth=True,
            metrics_token="tok-" + "x" * 28,
        )
    )
    c = TestClient(app)
    assert c.get("/metrics").status_code == 403
    assert c.get("/metrics", headers={"x-metrics-token": "wrong"}).status_code == 403
    ok = c.get("/metrics", headers={"x-metrics-token": "tok-" + "x" * 28})
    assert ok.status_code == 200
    assert "bgpt_http_requests_total" in ok.text


def test_dev_metrics_stays_open(tmp_path) -> None:
    app = create_app(
        Settings(
            env="test",
            database_url=engine_url(tmp_path, "metrics-dev"),
            jwt_secret=SECRET,
        )
    )
    c = TestClient(app)
    assert c.get("/metrics").status_code == 200
