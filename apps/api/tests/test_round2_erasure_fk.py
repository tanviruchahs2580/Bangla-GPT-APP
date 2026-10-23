"""Erasure must work when OTHER users hold rows pointing at this account's data.

F-093: ``DELETE /users/me`` raised ForeignKeyViolation on
``feedback_message_id_fkey``. ``feedback.message_id`` is a nullable FK into
``chat_messages``, and the erasure path deleted the messages without clearing
the pointers. Because the feedback row belongs to whoever left the thumbs-up —
often a different account — the per-user ``delete(Feedback).where(user_id ==
me)`` on the next line never saw it. The whole erasure rolled back and the
data subject got a 500 from the endpoint that exists so they can leave.

SQLite does not enforce foreign keys by default, so a SQLite-only test would
pass against the broken code. These run against PostgreSQL when
``TEST_DATABASE_URL`` is set, and against a SQLite connection with
``PRAGMA foreign_keys=ON`` otherwise, which is the configuration that makes
the violation real.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import Base
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _register(client: TestClient, email: str, role: str) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()


@pytest.fixture()
def fk_enforced(tmp_path):
    """Client + session factory over a database that really enforces FKs.

    SQLite ignores foreign keys unless asked, per connection. Registering the
    PRAGMA on one engine is not enough: ``create_app`` builds its OWN engine,
    and the DELETE runs on that one. So the listener goes on the Engine class
    for the duration of this fixture and is removed afterwards, which covers
    every engine the app creates.

    With ``TEST_DATABASE_URL`` set (the CI Postgres job) PostgreSQL does the
    enforcing natively and no PRAGMA is involved.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    test_db = os.environ.get("TEST_DATABASE_URL")
    if test_db:
        settings = Settings(
            env="test",
            database_url=test_db,
            jwt_secret=SECRET,
            admin_email="root@example.test",
            admin_password=PASSWORD,
            force_admin_password_change=False,
        )
        engine = make_engine(settings)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        yield TestClient(create_app(settings)), make_session_factory(engine)
        return

    def _fk_on(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(Engine, "connect", _fk_on)
    try:
        settings = Settings(
            env="test",
            database_url=engine_url(tmp_path, "fk"),
            jwt_secret=SECRET,
            admin_email="root@example.test",
            admin_password=PASSWORD,
            force_admin_password_change=False,
        )
        engine = make_engine(settings)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        # Prove the guard is actually armed before trusting a pass.
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        yield TestClient(create_app(settings)), make_session_factory(engine)
    finally:
        event.remove(Engine, "connect", _fk_on)


def _seed_feedback_on_student_message(factory, student_email: str, reporter_email: str) -> None:
    """A DIFFERENT user leaves feedback on the student's tutor answer."""
    with factory() as db:
        from bangla_gpt_api.db.models import ChatMessage, Conversation, Feedback, Student, User

        student_user = db.query(User).filter(User.email == student_email).one()
        student = db.query(Student).filter(Student.user_id == student_user.id).one()
        conv = Conversation(student_id=student.id, title="maths")
        db.add(conv)
        db.flush()
        msg = ChatMessage(conversation_id=conv.id, role="assistant", content="2+2 = 4")
        db.add(msg)
        db.flush()
        reporter = db.query(User).filter(User.email == reporter_email).one()
        db.add(Feedback(user_id=reporter.id, message_id=msg.id, rating=1))
        db.commit()


def test_erasure_succeeds_despite_another_users_feedback(fk_enforced) -> None:
    client, factory = fk_enforced
    _register(client, "owner@example.test", "student")
    _register(client, "reporter@example.test", "student")
    _seed_feedback_on_student_message(factory, "owner@example.test", "reporter@example.test")

    login = client.post("/auth/login", json={"email": "owner@example.test", "password": PASSWORD})
    token = login.json()["access_token"]

    res = client.request(
        "DELETE",
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "supersecret1"},
    )

    assert res.status_code == 204, (
        f"erasure failed with {res.status_code}: {res.text}. "
        "Without the feedback-pointer fix this is a 500 from "
        "feedback_message_id_fkey and the account still exists."
    )


def test_feedback_row_survives_but_its_pointer_is_cleared(fk_enforced) -> None:
    """Policy: the product-feedback row is history and is kept.

    Only the pointer into the erased conversation is dropped — the same rule
    already applied to AuditLog.actor_user_id and ChapterContent.created_by.
    """
    from bangla_gpt_api.db.models import Feedback

    client, factory = fk_enforced
    _register(client, "owner2@example.test", "student")
    _register(client, "reporter2@example.test", "student")
    _seed_feedback_on_student_message(factory, "owner2@example.test", "reporter2@example.test")

    login = client.post("/auth/login", json={"email": "owner2@example.test", "password": PASSWORD})
    token = login.json()["access_token"]
    assert (
        client.request(
            "DELETE",
            "/users/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"password": "supersecret1"},
        ).status_code
        == 204
    )

    with factory() as db:
        rows = db.query(Feedback).all()
        assert len(rows) == 1, "the feedback event itself must survive erasure"
        assert rows[0].message_id is None, (
            "the pointer into the erased conversation must be cleared"
        )
