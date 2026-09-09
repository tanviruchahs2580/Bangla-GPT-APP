"""Wave 1: AiJob background generation (queued -> generating -> ready|failed).

The runner executes as an asyncio task inside the app's portal, so the tests
MUST use TestClient as a context manager (`with ...`) to keep that event loop
alive between requests, and poll the job until it settles.
"""

import time

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)

WORKSHEET_BODY = {"class_level": 6, "subject": "science", "chapter": CHAPTER}


def _client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/jobs.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _wait(client: TestClient, headers: dict, job_id: str, target: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        res = client.get(f"/teacher/jobs/{job_id}", headers=headers)
        assert res.status_code == 200
        body = res.json()
        if body["status"] in (target, "failed"):
            return body
        time.sleep(0.05)
    pytest.fail(f"job never reached {target}: last={body}")


def test_job_ready_with_document_result(tmp_path) -> None:
    with _client(tmp_path) as client:
        _register(client, "teach@example.com")
        headers = _headers(client, "teach@example.com")

        res = client.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": WORKSHEET_BODY}, headers=headers
        )
        assert res.status_code == 202, res.text
        job = res.json()
        assert job["status"] == "queued"
        assert job["result"] is None and job["error"] is None

        done = _wait(client, headers, job["id"], "ready")
        assert done["error"] is None
        doc_id = done["result"]["document_id"]
        doc = client.get(f"/teacher/documents/{doc_id}", headers=headers)
        assert doc.status_code == 200
        assert doc.json()["kind"] == "worksheet"

        listed = client.get("/teacher/jobs", headers=headers).json()
        assert [j["id"] for j in listed] == [job["id"]]
        assert listed[0]["status"] == "ready"


def test_unsupported_kind_fails_visibly(tmp_path) -> None:
    with _client(tmp_path) as client:
        _register(client, "teach@example.com")
        headers = _headers(client, "teach@example.com")
        res = client.post(
            "/teacher/jobs",
            json={"kind": "totally_bogus_kind", "payload": {}},
            headers=headers,
        )
        # accepted into a VISIBLE failed job instead of a bare 422 at the door
        assert res.status_code == 202, res.text
        done = _wait(client, headers, res.json()["id"], "failed")
        assert done["status"] == "failed"
        assert done["error"], "failed job must carry an error message"
        assert done["result"] is None


def test_bad_payload_fails_job(tmp_path) -> None:
    with _client(tmp_path) as client:
        _register(client, "teach@example.com")
        headers = _headers(client, "teach@example.com")
        res = client.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": {}}, headers=headers
        )
        assert res.status_code == 202, res.text
        done = _wait(client, headers, res.json()["id"], "failed")
        assert done["status"] == "failed" and done["error"]


def test_jobs_are_owner_scoped(tmp_path) -> None:
    with _client(tmp_path) as client:
        _register(client, "teach@example.com")
        headers = _headers(client, "teach@example.com")
        _register(client, "other@example.com")
        other = _headers(client, "other@example.com")

        res = client.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": WORKSHEET_BODY}, headers=headers
        )
        job_id = res.json()["id"]
        _wait(client, headers, job_id, "ready")

        assert client.get(f"/teacher/jobs/{job_id}", headers=other).status_code == 404
        assert client.get("/teacher/jobs", headers=other).json() == []


def test_jobs_endpoints_require_auth(tmp_path) -> None:
    with _client(tmp_path) as client:
        assert (
            client.post("/teacher/jobs", json={"kind": "worksheet", "payload": {}}).status_code
            == 401
        )
        assert client.get("/teacher/jobs").status_code == 401
        assert client.get("/teacher/jobs/some-id").status_code == 401
