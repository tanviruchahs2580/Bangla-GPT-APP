"""AI-002: usage ledger, estimates, budgets and cost dashboard.

- Token/cost math is unit-tested (heuristic is documented, not asserted as
  vendor truth).
- Every /tutor/ask writes one ledger row; the admin quality endpoint totals it.
- Budgets: 0 = unlimited (default, no behavior change); a positive cap is
  enforced with 429 ai_budget_exceeded.
- DELETE /users/me removes ledger rows (BUG-4 rule).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.costs import (
    check_ai_budget,
    estimate_cost_usd,
    estimate_tokens,
    month_cost_usd,
    record_ai_usage,
)

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "StrongPass123!"


def _settings(tmp_path, **over) -> Settings:
    base = dict(env="test", database_url=f"sqlite:///{tmp_path}/costs.db", jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _register_login(client: TestClient, email: str, role: str = "student"):
    payload = {"email": email, "password": PASSWORD, "name": "Cost", "role": role}
    if role == "student":
        payload.update({"class_level": 6, "guardian_consent": True})
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_estimate_math() -> None:
    assert estimate_tokens(None) == 0
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_cost_usd("mock", 100, 50) == 0.0
    assert estimate_cost_usd("unknown-model", 100, 50) == 0.0
    assert estimate_cost_usd("gpt-4o-mini", 1000, 1000) == pytest.approx(0.00075)


def test_ask_writes_ledger_row(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _register_login(client, "ledger@example.com")
    question = "ভগ্নাংশ কী?"
    res = client.post("/tutor/ask", json={"question": question, "class_level": 6}, headers=headers)
    assert res.status_code == 200, res.text

    engine = make_engine(_settings(tmp_path))
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        rows = db.execute(select(AiUsage)).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.route == "tutor.ask"
        assert row.model == "mock"
        assert row.prompt_tokens == estimate_tokens(question) > 0
        assert row.completion_tokens > 0
        assert row.estimated_cost_usd == 0.0


def test_budget_blocks_when_exhausted(tmp_path) -> None:
    budgeted = _settings(tmp_path, ai_monthly_budget_usd_per_user=0.000001)
    client = TestClient(create_app(budgeted))
    _register_login(client, "budget@example.com")
    engine = make_engine(_settings(tmp_path))
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        user_id = 1
        record_ai_usage(
            db,
            user_id=user_id,
            route="tutor.ask",
            model="gpt-4o-mini",
            prompt_text="x" * 40000,
            answer_text="y" * 40000,
        )
        db.commit()
        assert month_cost_usd(db, user_id) > 0.000001
        with pytest.raises(Exception, match="ai_budget_exceeded"):
            check_ai_budget(db, user_id=user_id, settings=budgeted)


def test_budget_zero_means_unlimited(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _register_login(client, "free@example.com")
    # mock costs nothing; repeated asks always pass with the default budget 0
    for _ in range(2):
        res = client.post(
            "/tutor/ask", json={"question": "ভগ্নাংশ কী?", "class_level": 6}, headers=headers
        )
        assert res.status_code == 200


def test_budget_enforced_on_route(tmp_path) -> None:
    app = create_app(_settings(tmp_path, ai_monthly_budget_usd_per_user=0.0000001))
    client = TestClient(app)
    headers = _register_login(client, "routebudget@example.com")
    engine = make_engine(_settings(tmp_path))
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        record_ai_usage(
            db,
            user_id=1,
            route="tutor.ask",
            model="gpt-4o-mini",
            prompt_text="x" * 40000,
            answer_text="y" * 40000,
        )
        db.commit()
    res = client.post(
        "/tutor/ask", json={"question": "ভগ্নাংশ কী?", "class_level": 6}, headers=headers
    )
    assert res.status_code == 429
    assert res.json()["detail"]["code"] == "ai_budget_exceeded"


def test_admin_quality_reports_cost(tmp_path) -> None:
    # Admins come from bootstrap (public registration has no admin role).
    app = create_app(
        _settings(
            tmp_path,
            admin_email="root@example.com",
            admin_password=PASSWORD,
            force_admin_password_change=False,
        )
    )
    client = TestClient(app)
    root = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert root.status_code == 200, root.text
    admin_headers = {"Authorization": f"Bearer {root.json()['access_token']}"}
    user_headers = _register_login(client, "costuser@example.com")
    res = client.post(
        "/tutor/ask", json={"question": "ভগ্নাংশ কী?", "class_level": 6}, headers=user_headers
    )
    assert res.status_code == 200
    quality = client.get("/admin/ai/quality", headers=admin_headers)
    assert quality.status_code == 200
    body = quality.json()
    assert body["cost_usd_total"] >= 0.0
    assert "mock" in body["cost_usd_by_model"]


def test_delete_me_cleans_ledger(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)
    headers = _register_login(client, "gone@example.com")
    res = client.post(
        "/tutor/ask", json={"question": "ভগ্নাংশ কী?", "class_level": 6}, headers=headers
    )
    assert res.status_code == 200
    assert client.delete("/users/me", headers=headers).status_code == 204
    engine = make_engine(_settings(tmp_path))
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        assert db.execute(select(func.count()).select_from(AiUsage)).scalar_one() == 0
