"""S-021: /users/me/export carries every per-user table, plus a schema version.

The export used to stop at profile/attempts/links/conversations/messages/
activity while ``DELETE /users/me`` cascaded through notes, notifications,
chapter progress, revision items, the AI-usage ledger, analytics events and
more. These tests build a synthetic user with a note + progress + notification
and assert each appears, and that the credential rows are shape-only (their
token hashes never leave the database).
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import Notification
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers.users import EXPORT_SCHEMA_VERSION

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"

#: Every per-user section v2 adds; each must exist even when empty.
V2_SECTIONS = (
    "notes",
    "notifications",
    "chapter_progress",
    "revision_items",
    "concept_mastery",
    "student_abilities",
    "classrooms",
    "ai_usage",
    "analytics_events",
    "feedback",
    "ai_jobs",
    "teacher_documents",
    "question_papers",
    "question_bank",
    "short_tests",
    "assignments",
    "support_plans",
    "parent_invites",
    "student_invites",
    "password_resets",
    "email_verifications",
    "audit_events",
)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/export-v2.db",
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _student(client: TestClient, email: str = "kid@example.test") -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_export_contains_note_progress_and_notification(client: TestClient, tmp_path) -> None:
    headers = _student(client)

    note = client.post(
        "/notes",
        json={"title": "My note", "body": "নোটের অংশ", "source": "other"},
        headers=headers,
    )
    assert note.status_code == 201, note.text
    progress = client.post(
        "/learn/progress",
        json={"subject": "science", "chapter": "কোষ", "class_level": 6, "read_pct": 40},
        headers=headers,
    )
    assert progress.status_code == 200, progress.text

    # Notifications are written by other flows; seed one directly to keep this
    # test focused on the export.
    settings = Settings(database_url=f"sqlite:///{tmp_path}/export-v2.db")
    with make_session_factory(make_engine(settings))() as db:
        db.add(
            Notification(
                user_id=1,
                kind="test",
                code="notif_export_check",
                params={"count": 1},
            )
        )
        db.commit()

    body = client.get("/users/me/export", headers=headers).json()
    assert body["schema_version"] == EXPORT_SCHEMA_VERSION == "2"
    for section in V2_SECTIONS:
        assert section in body, f"export v2 is missing the {section!r} section"

    assert [n["title"] for n in body["notes"]] == ["My note"]
    assert body["notes"][0]["body"] == "নোটের অংশ"
    assert body["chapter_progress"] == [
        {
            "subject": "science",
            "chapter": "কোষ",
            "class_level": 6,
            "read_pct": 40,
            "completed": False,
            "bookmarked": False,
            "updated_at": body["chapter_progress"][0]["updated_at"],
        }
    ]
    assert [n["code"] for n in body["notifications"]] == ["notif_export_check"]
    assert body["notifications"][0]["params"] == {"count": 1}


def test_export_credential_rows_are_shape_only(client: TestClient) -> None:
    headers = _student(client)
    assert client.post("/auth/forgot", json={"email": "kid@example.test"}).status_code == 202

    body = client.get("/users/me/export", headers=headers).json()
    assert len(body["password_resets"]) == 1
    row = body["password_resets"][0]
    assert set(row) == {"id", "expires_at", "used_at", "created_at"}
    assert row["used_at"] is None


def test_teacher_export_carries_new_user_scoped_sections(client: TestClient) -> None:
    res = client.post(
        "/auth/register",
        json={"email": "t@example.test", "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "t@example.test", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    body = client.get("/users/me/export", headers=headers).json()
    assert body["profile"]["type"] == "teacher"
    # The v1 lists stay present and empty for a teacher.
    assert body["quiz_attempts"] == []
    assert body["chapter_progress"] == []
    # Audit rows from this very export (and the login) are visible to the owner.
    assert any(e["action"] == "data_export" for e in body["audit_events"])
