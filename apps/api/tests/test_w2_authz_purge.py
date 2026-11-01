"""SEC-17 wave-2 guards: the destructive maintenance sweep is confirmed,
bounded and audited, and the ops surfaces stay closed per ENV.

F-140: any holder of an admin token could trigger irreversible retention
deletions with a single unconfirmed request; the audit probe sent two purge
calls and got two 200s. The endpoint now requires an explicit confirmation
(``confirm=true`` or ``X-Confirm-Purge: true``), stays dry-run capable and
idempotent, is rate-limited, and every real run lands in the audit trail.
The second half of the SEC-17 check -- /metrics and /docs exposure per ENV
-- is asserted here as the ENV PAIR; the exhaustive per-path coverage lives
in test_metrics_auth.py and test_docs_exposure.py.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.initialize.middleware_stack import _effective_rules
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.retention import run_retention_sweep
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        env="test",
        database_url=engine_url(tmp_path, "w2purge"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return Settings(**base)


def _client(tmp_path, **over) -> TestClient:
    return TestClient(create_app(_settings(tmp_path, **over)))


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _rule_for(rules: dict[str, tuple[int, str]], path: str) -> tuple[int, str] | None:
    for prefix, rule in rules.items():
        if path == prefix or path.startswith(prefix + "/"):
            return rule
    return None


# --- F-140: the purge endpoint is confirmation-gated ------------------------


def test_unconfirmed_purge_is_refused_and_writes_no_audit_row(tmp_path) -> None:
    client = _client(tmp_path)
    admin = _headers(client, "root@example.com")
    refused = client.post("/admin/maintenance/purge", headers=admin)
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "purge_confirmation_required"
    # nothing happened, so nothing is claimed to have happened
    audit = client.get("/admin/audit", params={"action": "purge"}, headers=admin).json()
    assert audit["total"] == 0

    # the dry run needs no confirmation: it deletes nothing by contract
    dry = client.post("/admin/maintenance/purge", params={"dry_run": "true"}, headers=admin)
    assert dry.status_code == 200 and dry.json()["dry_run"] is True


@pytest.mark.parametrize(
    "params,headers_extra",
    [
        ({"confirm": "true"}, {}),
        ({}, {"X-Confirm-Purge": "true"}),
    ],
)
def test_confirmed_purge_runs_idempotently_and_is_audited(tmp_path, params, headers_extra) -> None:
    client = _client(tmp_path)
    admin = _headers(client, "root@example.com")
    admin.update(headers_extra)

    first = client.post("/admin/maintenance/purge", params=params, headers=admin)
    assert first.status_code == 200, first.text
    assert first.json()["dry_run"] is False

    # idempotent: the sweep only deletes rows past their window, so a repeat
    # reports zero and writes a second audit row for the second run
    second = client.post("/admin/maintenance/purge", params=params, headers=admin)
    assert second.status_code == 200
    assert all(v == 0 for k, v in second.json().items() if k != "dry_run"), second.json()

    rows = client.get("/admin/audit", params={"action": "purge"}, headers=admin).json()
    assert rows["total"] == 2
    assert rows["rows"][0]["target"] == "retention_sweep"


def test_purge_rule_ships_by_default() -> None:
    """A destructive sweep must also be bounded, not only confirmed."""
    rules = _effective_rules(Settings(env="test"))
    rule = _rule_for(rules, "/admin/maintenance/purge")
    assert rule is not None and rule[0] > 0 and rule[1] == "user"


def test_purge_is_rate_limited_after_the_confirmation(tmp_path) -> None:
    """Even a confirmed caller cannot loop the sweep at full speed."""
    client = _client(tmp_path, rate_limit_rules={"/admin/maintenance": (3, "user")})
    admin = _headers(client, "root@example.com")
    statuses = [
        client.post("/admin/maintenance/purge", params={"confirm": "true"}, headers=admin)
        for _ in range(4)
    ]
    assert [s.status_code for s in statuses[:3]] == [200, 200, 200]
    assert statuses[3].status_code == 429
    assert statuses[3].json()["detail"]["code"] == "rate_limited"


# --- SEC-17: docs and metrics exposure follow ENV --------------------------


def test_docs_and_metrics_exposure_follows_env(tmp_path) -> None:
    """Production closes the contract docs; development keeps them usable.

    The exhaustive per-path coverage lives in test_docs_exposure.py and
    test_metrics_auth.py; this is the ENV-pair assertion the SEC-17 check
    asks for, driven through the real app factory.
    """
    dev = _client(tmp_path)
    assert dev.get("/docs").status_code == 200
    assert dev.get("/openapi.json").status_code == 200
    assert dev.get("/metrics").status_code == 200

    os.environ["ALLOW_MOCK_LLM_IN_PRODUCTION"] = "1"
    os.environ["WEB_CONCURRENCY"] = "1"
    prod = TestClient(
        create_app(
            Settings(
                env="production",
                pii_allow_plaintext=False,
                jwt_secret="Zk7Qp2XvN8mR4tYcW1bH6jL3sD9fG5aE0uI2oP7xV4qM8nC6rT1wY3zB5",
                database_url=f"sqlite:///{(tmp_path / 'prod_limits.db').as_posix()}",
                allowed_origins="https://app.example.test",
                admin_email="admin@example.test",
                admin_password="ProdAdminPass!234",
                force_admin_password_change=False,
                metrics_require_auth=True,
                metrics_token="metrics-token-for-test",
                pii_enc_key="LjDorcxuiR0OrEApp_g6hwfAbKKwimZQOPIvEz1pRhk=",
                smtp_enabled=True,
                smtp_host="smtp.example.test",
                smtp_from="noreply@example.test",
                # a shared revocation store is a production boot requirement
                # (a memory deny-list dies with the process); nothing in this
                # test reaches the network.
                rate_limit_backend="redis",
                redis_url="redis://127.0.0.1:6399/0",
            )
        )
    )
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert prod.get(path).status_code == 404, path
    assert prod.get("/metrics").status_code == 403
    assert (
        prod.get("/metrics", headers={"x-metrics-token": "metrics-token-for-test"}).status_code
        == 200
    )


def test_retention_sweep_report_includes_the_job_window() -> None:
    """SEC-17 wording: the sweep is dry-run capable AND complete.

    The report is the compliance artifact; a table the sweep can age but
    does not report would silently over-retain.
    """
    from bangla_gpt_api.db.base import Base

    settings = Settings(env="test", database_url="sqlite://")
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        report = run_retention_sweep(session, settings=settings, dry_run=True)
    for key in (
        "conversations_deleted",
        "chat_messages_deleted",
        "password_resets_deleted",
        "email_verifications_deleted",
        "used_invites_deleted",
        "analytics_events_deleted",
        "answer_log_deleted",
        "ai_usage_deleted",
        "ai_jobs_deleted",
    ):
        assert key in report, key
