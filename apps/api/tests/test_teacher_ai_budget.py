"""Teacher AI generation: per-user budget enforcement and cost metering (SEC-002).

``AI_MONTHLY_BUDGET_USD_PER_USER`` was documented as applying to "generation
entry points" and enforced only in ``routers/tutor.py``. Every teacher-facing
generator -- question papers, chapter content, lesson plans, the four document
generators and the async AiJob runner -- reached the provider with no budget
check and no ledger row, so:

* the setting silently did nothing for the whole teaching staff, and
* ``GET /admin/ai/quality`` reported a cost total that excluded every teacher
  generation, i.e. understated real provider spend.

These tests pin the behaviour at the three shared generation seams
(``_generate_document``, ``_qp_fresh_draft``, chapter content) rather than at
each handler, because those seams are what all seven routes funnel through.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiUsage, User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.costs import estimate_cost_usd

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)


def _settings(tmp_path, **over) -> Settings:
    base = dict(env="test", database_url=f"sqlite:///{tmp_path}/teacherai.db", jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _teacher(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ledger(tmp_path, **over) -> list[AiUsage]:
    engine = make_engine(_settings(tmp_path, **over))
    with make_session_factory(engine)() as db:
        return list(db.execute(select(AiUsage).order_by(AiUsage.id)).scalars())


# --- metering ---------------------------------------------------------------


def test_document_generator_writes_a_ledger_row(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _teacher(client, "t@example.com")
    res = client.post(
        "/teacher/generate/worksheet",
        json={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    )
    assert res.status_code == 201, res.text

    rows = _ledger(tmp_path)
    assert len(rows) == 1, "teacher generation was never metered"
    assert rows[0].route == "teacher/worksheet"
    assert rows[0].prompt_tokens > 0


def test_lesson_plan_writes_a_ledger_row(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _teacher(client, "lp@example.com")
    res = client.post(
        "/teacher/lesson-plans",
        json={
            "class_level": 6,
            "subject": "science",
            "chapter": CHAPTER,
            "minutes": 40,
            "level": "average",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert [r.route for r in _ledger(tmp_path)] == ["teacher/lesson_plan"]


def test_question_paper_writes_a_ledger_row(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _teacher(client, "qp@example.com")
    res = client.post(
        "/teacher/qpapers",
        json={
            "class_level": 6,
            "subject": "science",
            "chapters": [CHAPTER],
            "marks": 10,
            "duration_min": 30,
            "exam_type": "unit",
            "difficulty": {"easy": 30, "medium": 40, "hard": 30},
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    rows = _ledger(tmp_path)
    assert [r.route for r in rows] == ["teacher/question_paper"]


def test_regenerate_writes_its_own_ledger_row(tmp_path) -> None:
    """Draft + regenerate are two provider calls and must be metered as two."""
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _teacher(client, "rg@example.com")
    draft = client.post(
        "/teacher/qpapers",
        json={
            "class_level": 6,
            "subject": "science",
            "chapters": [CHAPTER],
            "marks": 10,
            "duration_min": 30,
            "exam_type": "unit",
            "difficulty": {"easy": 30, "medium": 40, "hard": 30},
        },
        headers=headers,
    )
    assert draft.status_code == 201, draft.text
    again = client.post(f"/teacher/qpapers/{draft.json()['id']}/regenerate", headers=headers)
    assert again.status_code == 200, again.text
    assert len(_ledger(tmp_path)) == 2


def test_metering_shows_up_in_the_admin_cost_dashboard(tmp_path) -> None:
    """The reason metering exists: the admin total must include teacher spend."""
    settings = _settings(
        tmp_path,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    client.post(
        "/auth/register",
        json={"email": "meter@example.com", "password": PASSWORD, "name": "T", "role": "teacher"},
    )
    headers = _teacher(client, "meter2@example.com")
    assert (
        client.post(
            "/teacher/generate/homework",
            json={"class_level": 6, "subject": "science", "chapter": CHAPTER},
            headers=headers,
        ).status_code
        == 201
    )
    login = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    admin = {"Authorization": f"Bearer {login.json()['access_token']}"}
    res = client.get("/admin/ai/quality?days=30", headers=admin)
    assert res.status_code == 200, res.text
    # The mock provider is free, so the dollar total is legitimately 0.0 --
    # what matters is that the teacher generation produced a ledger row and
    # therefore appears in the per-model breakdown at all. Before the fix
    # this was {} because no teacher route ever wrote an AiUsage row.
    assert "mock" in res.json()["cost_usd_by_model"], res.json()


# --- budget enforcement -----------------------------------------------------


def test_teacher_generation_refused_once_the_budget_is_spent(tmp_path) -> None:
    """A positive cap must stop a teacher, exactly as it stops a student.

    The mock provider costs $0, so the cap is exercised by pre-seeding a
    ledger row rather than by pretending mock generation is billable.
    """
    settings = _settings(tmp_path, ai_monthly_budget_usd_per_user=0.000001)
    client = TestClient(create_app(settings))
    headers = _teacher(client, "poor@example.com")

    # Seed this month with spend above the cap.
    engine = make_engine(settings)
    with make_session_factory(engine)() as db:
        user = db.execute(select(User).where(User.email == "poor@example.com")).scalar_one()
        db.add(
            AiUsage(
                user_id=user.id,
                route="seed",
                model="gpt-4o-mini",
                prompt_tokens=1_000_000,
                completion_tokens=0,
                estimated_cost_usd=estimate_cost_usd("gpt-4o-mini", 1_000_000, 0),
            )
        )
        db.commit()
    assert estimate_cost_usd("gpt-4o-mini", 1_000_000, 0) > 0.000001

    res = client.post(
        "/teacher/generate/worksheet",
        json={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    )
    assert res.status_code == 429, res.text
    assert res.json()["detail"]["code"] == "ai_budget_exceeded"
    # Refused before the provider ran: nothing was added to the ledger.
    assert len(_ledger(tmp_path)) == 1


def test_zero_budget_stays_unlimited(tmp_path) -> None:
    """Default behaviour must not change: 0 means unlimited (no behaviour change)."""
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _teacher(client, "free@example.com")
    for _ in range(3):
        res = client.post(
            "/teacher/generate/worksheet",
            json={"class_level": 6, "subject": "science", "chapter": CHAPTER},
            headers=headers,
        )
        assert res.status_code == 201, res.text
