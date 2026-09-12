"""SEC-001: /metrics is never public in production.

- Prod boot refuses when METRICS_REQUIRE_AUTH is false or METRICS_TOKEN unset.
- In prod mode /metrics answers 403 without the token, 200 with it.
- Dev/test keep the open /metrics (documented local behavior).
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app, enforce_production_safety

SECRET = "test-secret-0123456789abcdef0123456789"


def _prod_settings(**over):
    base = dict(
        env="production",
        database_url="sqlite://",
        jwt_secret=SECRET,
        admin_email="a@b.com",
        admin_password="longenoughpass1",
        allowed_origins="https://app.example.com",
        pii_enc_key="k" * 32,
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
            database_url=f"sqlite:///{tmp_path}/metrics.db",
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
            database_url=f"sqlite:///{tmp_path}/metrics-dev.db",
            jwt_secret=SECRET,
        )
    )
    c = TestClient(app)
    assert c.get("/metrics").status_code == 200
