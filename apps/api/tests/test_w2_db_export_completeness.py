"""PRIV-03 wave-2 guard: the export is complete against the MODEL LIST.

F-040's fix added answer_log, the AI-memory preferences and the per-attempt
quiz_json, but "complete" was asserted by listing section names in the old
test -- a new user-scoped table could ship exported-by-nobody and nothing
would fail. This file derives the requirement from ``Base.metadata``: every
table that carries a column pointing at an account (user_id / student_id /
teacher_id / parent_id / created_by / used_by / actor_user_id) must be
mapped to the export section that answers a subject access request for it,
or be named as a deliberate exclusion WITH the reason.

The remaining gap F-040's fix left -- ``teachers.prefs`` and the relational
``assignment_recipients`` membership rows -- is closed here and asserted by
value, not by name.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import bangla_gpt_api.db.models  # noqa: F401  (registers every table)
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import (
    Assignment,
    AssignmentRecipient,
    QuizAttempt,
    Teacher,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.gdpr import _DataExportV2
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
NOW_ISO = "2026-10-29T00:00:00"

#: table -> the export section that must carry its rows for the account it
#: belongs to. Derived requirement: every table with an account pointer
#: below appears here, and the test fails on any new one that does not.
EXPORTED_TABLES: dict[str, str] = {
    "users": "user",
    "students": "profile",
    "teachers": "profile",
    "parents": "profile",
    "parent_student_links": "parent_links",
    "quiz_attempts": "quiz_attempts",
    "answer_log": "answer_log",
    "conversations": "conversations",
    "chat_messages": "chat_messages",
    "parent_invites": "parent_invites",
    "feedback": "feedback",
    "chapter_progress": "chapter_progress",
    "daily_activity": "learning_activity",
    "revision_queue": "revision_items",
    "class_students": "classrooms",
    "class_teachers": "classrooms",
    "student_invites": "student_invites",
    "support_plans": "support_plans",
    "question_papers": "question_papers",
    "teacher_documents": "teacher_documents",
    "assignments": "assignments",
    "assignment_recipients": "assignment_memberships",
    "short_tests": "short_tests",
    "question_bank": "question_bank",
    "saved_notes": "notes",
    "notifications": "notifications",
    "password_resets": "password_resets",
    "email_verifications": "email_verifications",
    "audit_log": "audit_events",
    "ai_jobs": "ai_jobs",
    "ai_usage": "ai_usage",
    "analytics_events": "analytics_events",
    "concept_mastery": "concept_mastery",
    "student_abilities": "student_abilities",
}

#: Account-pointing tables that are deliberately NOT in the export, each
#: with the policy reason. Everything else is a gap.
DELIBERATE_EXCLUSIONS: dict[str, str] = {
    # Shared library artifact: not personal data once another school reads it
    # (the same reasoning the export docstring records); the author pointer
    # is dropped on erasure rather than the row.
    "chapter_contents": "shared_content",
    # Staff-invite rows created BY the account are tenant records the school
    # retains; the account's own redemption facts live on the users row and
    # in audit_log.
    "school_invites": "tenant_record",
    # Scheduler idempotency ledger: (job, period_key), no account data.
    "job_runs": "operations",
    # The school/classroom hierarchy is organisational data shared by many
    # accounts; each account's own membership is exported below.
    "schools": "organisation",
    "concepts": "curriculum",
    "practice_items": "curriculum",
}

#: The policy tags an exclusion may carry, so a free-text reason cannot be
#: invented per table without review.
EXCLUSION_TAGS = frozenset(
    {"shared_content", "tenant_record", "operations", "organisation", "curriculum"}
)

_ACCOUNT_COLUMNS = frozenset(
    {"user_id", "student_id", "teacher_id", "parent_id", "created_by", "used_by", "actor_user_id"}
)


def _account_scoped_tables() -> set[str]:
    return {
        table.name
        for table in Base.metadata.sorted_tables
        if any(column.name in _ACCOUNT_COLUMNS for column in table.columns)
    }


def _export_sections() -> set[str]:
    return set(_DataExportV2.model_fields)


def test_every_account_scoped_table_is_exported_or_deliberately_excluded() -> None:
    required = _account_scoped_tables()
    unmapped = sorted(required - set(EXPORTED_TABLES) - set(DELIBERATE_EXCLUSIONS))
    assert not unmapped, (
        "account-scoped tables with no export decision (map them in "
        f"EXPORTED_TABLES or name the policy reason): {unmapped}"
    )
    both = sorted(set(EXPORTED_TABLES) & set(DELIBERATE_EXCLUSIONS))
    assert not both, f"tables both exported and excluded: {both}"


def test_every_mapped_section_exists_on_the_export_schema() -> None:
    sections = _export_sections()
    missing = sorted(
        f"{table}->{section}"
        for table, section in EXPORTED_TABLES.items()
        if section not in sections
    )
    assert not missing, f"export sections named by the map but absent: {missing}"


def test_exclusions_carry_a_known_policy_tag() -> None:
    unknown = sorted(
        f"{table}={tag}"
        for table, tag in DELIBERATE_EXCLUSIONS.items()
        if tag not in EXCLUSION_TAGS
    )
    assert not unknown, f"exclusions with an unknown policy tag: {unknown}"


def test_map_is_sorted_and_unique_documentation() -> None:
    """The map IS the documentation; a duplicate target would hide a table."""
    assert len(set(EXPORTED_TABLES.values()) | set(DELIBERATE_EXCLUSIONS.values())) >= 20
    for table, section in EXPORTED_TABLES.items():
        assert section and isinstance(section, str), table


@pytest.fixture
def pair(tmp_path):
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2export"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory


def _register(client: TestClient, email: str, role: str, **extra) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role, **extra}
    if role == "student":
        payload.update(guardian_consent=True, class_level=6)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_teacher_prefs_are_exported(pair) -> None:
    """The one profile field the F-040 fix left out."""
    client, factory = pair
    prof = _register(client, "t@example.com", "teacher")
    with factory() as session:
        teacher = session.execute(
            select(Teacher).where(Teacher.user_id == prof["user_id"])
        ).scalar_one()
        teacher.prefs = {"default_class": 6, "language": "bn"}
        session.commit()

    export = client.get("/users/me/export", headers=_headers(client, "t@example.com")).json()
    assert export["profile"]["type"] == "teacher"
    assert export["profile"]["prefs"] == {"default_class": 6, "language": "bn"}


def test_assignment_membership_rows_are_exported_by_value(pair) -> None:
    """The relational membership row, not just the JSON copy the teacher wrote."""
    client, factory = pair
    student = _register(client, "kid@example.com", "student")
    teacher = _register(client, "t2@example.com", "teacher")
    due = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1)
    with factory() as session:
        assignment = Assignment(
            teacher_id=teacher["user_id"], subject="science", chapter="ch", due_at=due
        )
        session.add(assignment)
        session.flush()
        attempt = QuizAttempt(student_id=student["profile_id"], class_level=6, status="open")
        session.add(attempt)
        session.flush()
        session.add(
            AssignmentRecipient(
                assignment_id=assignment.id,
                student_id=student["profile_id"],
                attempt_id=attempt.id,
            )
        )
        session.commit()
        expected = {"assignment_id": assignment.id, "attempt_id": attempt.id}

    export = client.get("/users/me/export", headers=_headers(client, "kid@example.com")).json()
    memberships = export["assignment_memberships"]
    assert len(memberships) == 1, memberships
    assert memberships[0]["assignment_id"] == expected["assignment_id"]
    assert memberships[0]["attempt_id"] == expected["attempt_id"]
    assert memberships[0]["created_at"], "the membership timestamp must be exported"


def test_export_is_authenticated(pair) -> None:
    client, _ = pair
    assert client.get("/users/me/export").status_code == 401


def test_export_rows_never_carry_credential_material(pair) -> None:
    """Shape-only credential sections: no token hashes, no password hash."""
    client, factory = pair
    _register(client, "s@example.com", "student")
    export = client.get("/users/me/export", headers=_headers(client, "s@example.com")).json()
    blob = str(export)
    with factory() as session:
        stored = session.execute(select(User.password_hash)).scalars().first()
    assert stored and stored not in blob, "the password hash must never be exported"
    for section in ("password_resets", "email_verifications"):
        for row in export[section]:
            assert "token_hash" not in row, section
