"""F-171 / BE-17: the `validating` job status covers the validation work.

The payload checks (parse/echo/MCQ) run inside the generator call, so the job
row must read `validating` while that call is in flight -- previously the
label appeared only for the persistence write that follows it, which made the
state-machine's V step cosmetic.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiJob
from bangla_gpt_api.main import create_app
from conftest import engine_url, poll_until

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/register",
        json={
            "email": "teach@example.com",
            "password": PASSWORD,
            "name": "Teach",
            "role": "teacher",
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "teach@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _wait(client: TestClient, headers: dict, job_id: str, timeout: float = 20.0) -> dict:
    last: dict = {}

    def settled() -> dict | None:
        res = client.get(f"/teacher/jobs/{job_id}", headers=headers)
        assert res.status_code == 200
        body = res.json()
        last.update(body)
        return body if body["status"] in ("ready", "failed") else None

    return poll_until(
        settled,
        timeout=timeout,
        describe=lambda: f"job never settled: last={last}",
    )


def test_job_reads_validating_while_the_generator_runs(tmp_path, monkeypatch) -> None:
    from bangla_gpt_api.routers import workspace

    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2xjobstatus"),
        jwt_secret=SECRET,
    )
    app = create_app(settings)
    original = workspace._generate_document
    observed: dict[str, str] = {}

    async def spy(app_ctx, db, actor, kind, gen):
        session = app_ctx.session_factory()
        try:
            row = (
                session.execute(
                    select(AiJob)
                    .where(AiJob.user_id == actor.id)
                    .order_by(AiJob.created_at.desc(), AiJob.id.desc())
                )
                .scalars()
                .first()
            )
            observed["status"] = row.status if row is not None else "missing"
        finally:
            session.close()
        return await original(app_ctx, db, actor, kind, gen)

    monkeypatch.setattr(workspace, "_generate_document", spy)
    with TestClient(app) as client:
        headers = _headers(client)
        created = client.post(
            "/teacher/jobs",
            json={
                "kind": "worksheet",
                "payload": {"class_level": 6, "subject": "science", "chapter": "কোষ"},
            },
            headers=headers,
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        done = _wait(client, headers, job_id)
    assert done["status"] == "ready", done
    assert observed["status"] == "validating", (
        "the generator call ran under a different status than the V step names"
    )
