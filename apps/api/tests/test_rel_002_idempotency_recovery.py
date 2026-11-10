"""REL-002: a key reused OUTSIDE the replay window must still return its job.

``uq_ai_jobs_idempotency`` never expires, but the recovery read after the
INSERT's IntegrityError used the windowed ``find_idempotent_job`` and
re-raised when it found nothing. For a key reused between 24 h (the default
window) and the retention sweep, the client got ``500 internal_error`` and no
job -- the opposite of the replay contract documented in
``jobs.find_idempotent_job``. The unique index is the truth about "this key
was used", so the collision branch now replays the colliding job whatever its
age; the window still governs the fast path and keys that never collided.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiJob
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from conftest import engine_url, poll_until

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = "\u0995\u09cb\u09b7"
BODY = {
    "kind": "worksheet",
    "payload": {"class_level": 6, "subject": "science", "chapter": CHAPTER},
}
KEY = "reused-after-the-window"
OTHER_KEY = "a-different-key-42"


def _settings(tmp_path, name: str) -> Settings:
    return Settings(
        env="test",
        database_url=engine_url(tmp_path, name),
        jwt_secret=SECRET,
        # a 1-minute window makes "outside the window" unambiguous while
        # keeping the fast path inside it observable
        ai_job_idempotency_window_minutes=1,
        ai_job_max_attempts=1,
        ai_job_retry_backoff_seconds=0.01,
    )


@pytest.fixture
def env(tmp_path):
    settings = _settings(tmp_path, "rel002")
    factory = make_session_factory(make_engine(settings))
    return create_app(settings), factory


def _headers(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _wait_settled(factory, job_id: str, timeout: float = 30.0) -> str:
    last = {"status": "queued"}

    def settled() -> str | None:
        with factory() as session:
            status = (
                session.execute(select(AiJob.status).where(AiJob.id == job_id)).scalar_one_or_none()
                or "missing"
            )
        last["status"] = status
        return status if status in ("ready", "failed") else None

    return poll_until(
        settled, timeout=timeout, describe=lambda: f"job never settled: {last['status']}"
    )


def _post(client: TestClient, headers: dict, key: str | None):
    request_headers = dict(headers)
    if key is not None:
        request_headers["Idempotency-Key"] = key
    return client.post("/teacher/jobs", json=BODY, headers=request_headers)


def _age_job(factory, job_id: str, days: int = 30) -> None:
    """Move the row's created_at outside the replay window."""
    with factory() as session:
        job = session.get(AiJob, job_id)
        assert job is not None
        job.created_at = job.created_at - timedelta(days=days)
        session.commit()


def _job_count(factory) -> int:
    with factory() as session:
        return int(session.execute(select(func.count()).select_from(AiJob)).scalar_one())


def test_reusing_a_key_after_the_window_replays_the_same_job(env) -> None:
    """The regression: this used to be a 500 with no job."""
    app, factory = env
    with TestClient(app) as client:
        headers = _headers(client, "rel002-reuse@example.test")
        first = _post(client, headers, KEY)
        assert first.status_code == 202, first.text
        job_id = first.json()["id"]
        assert _wait_settled(factory, job_id) == "ready"

        _age_job(factory, job_id)
        again = _post(client, headers, KEY)

        assert again.status_code == 202, again.text
        assert again.json()["id"] == job_id, "the replay must return the colliding job"
        assert again.json()["status"] == "ready", "the replay must not re-run the job"
        assert _job_count(factory) == 1, "no second row may be created"


def test_the_fast_path_replays_inside_the_window(env) -> None:
    app, factory = env
    with TestClient(app) as client:
        headers = _headers(client, "rel002-fast@example.test")
        first = _post(client, headers, KEY)
        job_id = first.json()["id"]
        _wait_settled(factory, job_id)
        again = _post(client, headers, KEY)
        assert again.status_code == 202, again.text
        assert again.json()["id"] == job_id
        assert _job_count(factory) == 1


def test_an_out_of_window_key_that_never_collided_creates_a_new_job(env) -> None:
    """The window still means something: an aged key that is free is new."""
    app, factory = env
    with TestClient(app) as client:
        headers = _headers(client, "rel002-newkey@example.test")
        first = _post(client, headers, KEY)
        job_id = first.json()["id"]
        _wait_settled(factory, job_id)
        _age_job(factory, job_id)

        fresh = _post(client, headers, OTHER_KEY)
        assert fresh.status_code == 202, fresh.text
        assert fresh.json()["id"] != job_id
        assert _job_count(factory) == 2


def test_a_reused_key_whose_row_was_swept_still_creates_a_job(env) -> None:
    """A keyed row removed by retention cannot collide, so the key is free."""
    app, factory = env
    with TestClient(app) as client:
        headers = _headers(client, "rel002-swept@example.test")
        first = _post(client, headers, KEY)
        job_id = first.json()["id"]
        _wait_settled(factory, job_id)
        with factory() as session:
            session.delete(session.get(AiJob, job_id))
            session.commit()

        again = _post(client, headers, KEY)
        assert again.status_code == 202, again.text
        assert again.json()["id"] != job_id
        assert _job_count(factory) == 1
