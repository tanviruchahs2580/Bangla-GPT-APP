"""Wave 1: POST /teacher/lesson-plans now ALSO persists a TeacherDocument.

The pre-existing response contract (test_lesson_plan.py) must stay intact;
this file only checks the additive persistence + document_id + PDF export.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.generators.lesson_plan import LESSON_KEYS

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/lessonpersist.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def teach(client: TestClient) -> dict:
    client.post(
        "/auth/register",
        json={
            "email": "teach@example.com",
            "password": PASSWORD,
            "name": "Teacher",
            "role": "teacher",
        },
    )
    res = client.post("/auth/login", json={"email": "teach@example.com", "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _plan(client: TestClient, headers: dict) -> dict:
    res = client.post(
        "/teacher/lesson-plans",
        json={"class_level": 6, "subject": "science", "chapter": CHAPTER, "minutes": 35},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_response_shape_unchanged_plus_document_id(client: TestClient, teach) -> None:
    body = _plan(client, teach)
    # every pre-existing field keeps its exact shape...
    assert list(body["sections"].keys()) == list(LESSON_KEYS)
    assert all(v.strip() for v in body["sections"].values())
    assert body["minutes"] == 35 and body["level"] == "average"
    assert body["class_level"] == 6 and body["subject"] == "science"
    assert body["chapter"] == CHAPTER and body["sources"]
    # ...and document_id is the additive Wave-1 field
    assert isinstance(body["document_id"], int)


def test_document_persisted_and_printable(client: TestClient, teach) -> None:
    body = _plan(client, teach)
    doc_id = body["document_id"]

    listed = client.get("/teacher/documents", params={"kind": "lesson_plan"}, headers=teach).json()
    assert [d["id"] for d in listed] == [doc_id]
    assert listed[0]["title"]
    assert listed[0]["chapter"] == CHAPTER

    got = client.get(f"/teacher/documents/{doc_id}", headers=teach)
    assert got.status_code == 200
    payload = got.json()["payload"]
    assert list(payload["sections"].keys()) == list(LESSON_KEYS)
    assert payload["sections"] == body["sections"]
    assert payload["minutes"] == 35 and payload["level"] == "average"

    res = client.get(f"/teacher/documents/{doc_id}/pdf", headers=teach)
    assert res.status_code == 200
    assert res.content[:5] == b"%PDF-"
    assert f"document-{doc_id}-lesson_plan.pdf" in res.headers["content-disposition"]


def test_each_plan_call_creates_its_own_document(client: TestClient, teach) -> None:
    first = _plan(client, teach)
    second = _plan(client, teach)
    assert first["document_id"] != second["document_id"]
    listed = client.get("/teacher/documents", headers=teach).json()
    assert len(listed) == 2
