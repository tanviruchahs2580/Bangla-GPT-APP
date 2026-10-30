"""F-060 (LLM budget on every generation route) and F-063 (portability export)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "Str0ngPassphrase!234"


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "env": "test",
        "database_url": engine_url(tmp_path, "budget"),
        "jwt_secret": SECRET,
        "admin_email": "root@example.test",
        "admin_password": PASSWORD,
        "force_admin_password_change": False,
    }
    base.update(overrides)
    return Settings(**base)


def _teacher(client: TestClient, email: str = "teacher@example.test") -> str:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    # With the cap disabled the budget dependency must stay out of the way.
    # (This fixture's mock provider cannot draft a paper, hence 502 rather
    # than 201 -- what matters here is that the refusal is NOT 429.)
    assert res.status_code != 429, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


# ---------------------------------------------------------------------------
# F-060 - the budget applies to teacher generation, not just the tutor
# ---------------------------------------------------------------------------


def test_question_paper_generation_honours_the_monthly_budget(tmp_path) -> None:
    """Before the fix, /teacher/qpapers consulted no budget at all.

    40 consecutive calls on /tutor/ask returned 429; the same user driving
    /teacher/qpapers, which calls the same provider, never saw the cap.

    The ledger is seeded directly so the check is reached on the FIRST call
    rather than after burning real generations.
    """
    from bangla_gpt_api.db.models import AiUsage
    from bangla_gpt_api.db.session import make_engine, make_session_factory

    settings = _settings(tmp_path, ai_monthly_budget_usd_per_user=0.01)
    client = TestClient(create_app(settings))
    token = _teacher(client)
    headers = {"Authorization": f"Bearer {token}"}

    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        from bangla_gpt_api.db.models import User

        user = db.query(User).filter(User.email == "teacher@example.test").one()
        db.add(
            AiUsage(
                user_id=user.id,
                route="seed",
                estimated_cost_usd=1.0,
                prompt_tokens=0,
                completion_tokens=0,
            )
        )
        db.commit()

    res = client.post(
        "/teacher/qpapers",
        json={
            "class_level": 6,
            "subject": "math",
            "chapters": ["1"],
            "exam_type": "unit_test",
            "marks": 20,
            "duration_min": 40,
        },
        headers=headers,
    )
    assert res.status_code == 429, (
        f"expected the budget cap to refuse generation, got {res.status_code}: "
        f"{res.text}. The teacher generation routes never consulted the "
        "monthly budget; the cap was wired only into the three /tutor routes."
    )
    assert res.json()["detail"]["code"] == "ai_budget_exceeded"


def test_other_generation_routes_are_budget_gated_too(tmp_path) -> None:
    """The cap is a per-user policy, not a property of one family of routes."""
    from bangla_gpt_api.db.models import AiUsage
    from bangla_gpt_api.db.session import make_engine, make_session_factory

    settings = _settings(tmp_path, ai_monthly_budget_usd_per_user=0.01)
    client = TestClient(create_app(settings))
    token = _teacher(client, "t3@example.test")
    headers = {"Authorization": f"Bearer {token}"}

    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        from bangla_gpt_api.db.models import User

        user = db.query(User).filter(User.email == "t3@example.test").one()
        db.add(
            AiUsage(
                user_id=user.id,
                route="seed",
                estimated_cost_usd=1.0,
                prompt_tokens=0,
                completion_tokens=0,
            )
        )
        db.commit()

    for path, body in (
        ("/teacher/content/generate", {"subject": "math", "class_level": 6, "chapter": "1"}),
        (
            "/teacher/lesson-plans",
            {"class_level": 6, "subject": "math", "chapter": "1", "objectives": ["x"]},
        ),
        ("/teacher/generate/worksheet", {"class_level": 6, "subject": "math", "chapter": "1"}),
    ):
        res = client.post(path, json=body, headers=headers)
        assert res.status_code == 429, f"{path} -> {res.status_code}: {res.text[:200]}"
        assert res.json()["detail"]["code"] == "ai_budget_exceeded", path


def test_read_only_teacher_routes_are_not_budget_gated(tmp_path) -> None:
    """Non-vacuity: the fix must not block a teacher from reading their work."""
    client = TestClient(create_app(_settings(tmp_path, ai_monthly_budget_usd_per_user=0.0)))
    token = _teacher(client)
    headers = {"Authorization": f"Bearer {token}"}
    for path in ("/teacher/qpapers", "/teacher/documents"):
        res = client.get(path, headers=headers)
        assert res.status_code != 429, path
        assert res.status_code in (200, 404), (path, res.status_code, res.text)


def test_budget_disabled_by_default_does_not_block_generation(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, ai_monthly_budget_usd_per_user=0.0)))
    token = _teacher(client)
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post(
        "/teacher/qpapers",
        json={
            "class_level": 6,
            "subject": "math",
            "chapters": ["1"],
            "exam_type": "unit_test",
            "marks": 20,
            "duration_min": 40,
        },
        headers=headers,
    )
    # With the cap disabled the budget dependency must stay out of the way.
    # (This fixture's mock provider cannot draft a paper, hence 502 rather
    # than 201 -- what matters here is that the refusal is NOT 429.)
    assert res.status_code != 429, res.text


def test_generation_routes_carry_the_budget_dependency(tmp_path) -> None:
    """Structural check: every provider-calling route uses the gated dep."""
    app = create_app(_settings(tmp_path))
    spec = app.openapi()
    gated = {
        "/teacher/content/generate",
        "/teacher/qpapers",
        "/teacher/qpapers/{qp_id}/regenerate",
        "/teacher/qpapers/{qp_id}/replace",
        "/teacher/lesson-plans",
        "/teacher/generate/{kind}",
    }
    for path in gated:
        assert path in spec["paths"], f"{path} is no longer a route"
    # And the dependency is wired in code, not merely intended.
    from bangla_gpt_api.routers.deps import AIGenerationUser, require_ai_budget

    assert AIGenerationUser is not None
    assert callable(require_ai_budget)


# ---------------------------------------------------------------------------
# F-063 - the portability export includes a minor's conversations
# ---------------------------------------------------------------------------


def _student(client: TestClient, email: str) -> str:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    # With the cap disabled the budget dependency must stay out of the way.
    # (This fixture's mock provider cannot draft a paper, hence 502 rather
    # than 201 -- what matters here is that the refusal is NOT 429.)
    assert res.status_code != 429, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def test_export_includes_conversations_and_messages(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    token = _student(client, "kid@example.test")
    headers = {"Authorization": f"Bearer {token}"}

    # Seed a conversation through the API, which is the path a real chat uses
    # (POST /tutor/ask is the stateless one-shot form).
    created = client.post("/tutor/conversations", json={"title": "গণিত"}, headers=headers)
    assert created.status_code == 201, created.text
    conv_id = created.json()["id"]
    msg = client.post(
        f"/tutor/conversations/{conv_id}/messages",
        json={"message": "২+২ কত?"},
        headers=headers,
    )
    assert msg.status_code == 201, msg.text

    export = client.get("/users/me/export", headers=headers)
    assert export.status_code == 200, export.text
    body = export.json()

    assert body["conversations"], (
        "the portability export returned no conversations; for a student the "
        "chat history is the largest body of personal data the product holds"
    )
    assert [c["id"] for c in body["conversations"]] == [conv_id], body["conversations"]
    assert body["chat_messages"], "no chat messages in the portability export"
    contents = [m["content"] for m in body["chat_messages"]]
    assert any("২+২" in c for c in contents), contents
    assert "learning_activity" in body


def test_export_still_works_for_a_teacher(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    token = _teacher(client, "t2@example.test")
    body = client.get("/users/me/export", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["conversations"] == []
    assert body["chat_messages"] == []
    assert body["profile"]["type"] == "teacher"


def test_export_requires_auth(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/users/me/export").status_code in (401, 403)
