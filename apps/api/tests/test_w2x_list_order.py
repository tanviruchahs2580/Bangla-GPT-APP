"""BE-20 residual: newest-first lists carry a unique tiebreaker.

Two rows written in the same clock tick share `created_at`/`updated_at`; with
no secondary key the database may return them in any order, so the "latest
first" contract silently depended on the storage engine's scan order. Both
lists now order by (timestamp desc, id desc), and these tests pin the tie.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import ChapterProgress, Conversation, Student
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
_SAME_TICK = datetime(2026, 10, 30, 12, 0, 0)


def _client_and_student(tmp_path, name: str) -> tuple[TestClient, int, dict[str, str]]:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, name),
        jwt_secret=SECRET,
    )
    app = create_app(settings)
    client = TestClient(app)
    res = client.post(
        "/auth/register",
        json={
            "email": "student@example.com",
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "student@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    session = app.state.ctx.session_factory()
    try:
        student = session.execute(select(Student).order_by(Student.id.desc())).scalars().first()
        assert student is not None
        return client, student.id, headers
    finally:
        session.close()


def test_conversations_with_equal_timestamps_order_by_id(tmp_path) -> None:
    client, student_id, headers = _client_and_student(tmp_path, "w2xorder-conv")
    session = client.app.state.ctx.session_factory()
    try:
        first = Conversation(student_id=student_id, title="first", created_at=_SAME_TICK)
        second = Conversation(student_id=student_id, title="second", created_at=_SAME_TICK)
        session.add_all([first, second])
        session.commit()
        ids = [first.id, second.id]
    finally:
        session.close()
    res = client.get("/tutor/conversations", headers=headers)
    assert res.status_code == 200, res.text
    listed = [row["id"] for row in res.json()]
    assert listed[:2] == [ids[1], ids[0]], "the later row must win the tie"


def test_learn_progress_with_equal_timestamps_orders_by_id(tmp_path) -> None:
    client, student_id, headers = _client_and_student(tmp_path, "w2xorder-learn")
    session = client.app.state.ctx.session_factory()
    try:
        # ASCII names whose index order equals insertion order: without the id
        # tiebreaker the engine answers a, b (the old hash/index order), so the
        # assertion below can only pass on the fixed query.
        for chapter in ("chapter-a", "chapter-b"):
            session.add(
                ChapterProgress(
                    student_id=student_id,
                    subject="science",
                    chapter=chapter,
                    class_level=6,
                    updated_at=_SAME_TICK,
                )
            )
        session.commit()
    finally:
        session.close()
    res = client.get("/learn/progress", headers=headers)
    assert res.status_code == 200, res.text
    chapters = [row["chapter"] for row in res.json()]
    assert chapters == ["chapter-b", "chapter-a"], "the later row must win the timestamp tie"
