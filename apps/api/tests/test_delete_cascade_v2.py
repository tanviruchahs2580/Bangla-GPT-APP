"""BUG-4 regression: DELETE /users/me must be FK-complete.

Postgres enforces foreign keys (SQLite silently does not), so EVERY table
referencing the erased account has to be cleaned inside delete_me or the
production engine aborts the erasure mid-transaction (the CI Postgres job
caught this on daily_activity; every later child table had the same bomb).

These tests seed one row into every student/teacher/parent child table via
a second session over the same database, erase the account through the
public API, and assert zero residue -- plus the two deliberate NON-deletes:
audit rows survive anonymised, shared chapter content survives authorless.

New file kept ASCII-only (repo rule for new files).
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    Assignment,
    AuditLog,
    ChapterContent,
    ChapterProgress,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    Concept,
    ConceptMastery,
    DailyActivity,
    EmailVerification,
    Feedback,
    Parent,
    ParentInvite,
    PasswordReset,
    QuestionBankEntry,
    QuestionPaper,
    RevisionItem,
    School,
    SchoolInvite,
    ShortTest,
    Student,
    StudentAbility,
    StudentInvite,
    SupportPlan,
    Teacher,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
NOW = datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
def pair(tmp_path):
    """Client + session factory over the SAME sqlite file (seed/assert directly)."""
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/cascade.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    factory = make_session_factory(make_engine(settings))
    return client, factory


def _register(client: TestClient, email: str, role: str) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tester", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _count(factory, model, *conditions) -> int:
    with factory() as s:
        stmt = select(func.count()).select_from(model)
        for cond in conditions:
            stmt = stmt.where(cond)
        return s.execute(stmt).scalar_one()


def test_student_delete_removes_every_child_row(pair) -> None:
    client, factory = pair
    prof = _register(client, "s@example.com", "student")
    sid, uid = prof["profile_id"], prof["user_id"]

    with factory() as s:
        school = School(name="Cascade School", code="CSC-1")
        s.add(school)
        s.flush()
        room = ClassRoom(school_id=school.id, class_level=6, section="GEN")
        concept = Concept(name="alpha", class_level=6, subject="math", chapter="alpha")
        s.add_all([room, concept])
        s.flush()
        s.add_all(
            [
                ChapterProgress(student_id=sid, subject="math", chapter="a", class_level=6),
                DailyActivity(student_id=sid, date="2026-09-08", questions=1),
                RevisionItem(student_id=sid, question="q?", due_date="2026-09-09"),
                ClassStudent(classroom_id=room.id, student_id=sid),
                StudentInvite(
                    code_hash="0" * 64,
                    email="s@example.com",
                    classroom_id=room.id,
                    student_id=sid,
                    expires_at=NOW + timedelta(days=30),
                ),
                SupportPlan(student_id=sid, teacher_id=sid, class_level=6, focus_concepts=["a"]),
                ConceptMastery(student_id=sid, concept_id=concept.id, correct=1, total=2),
                StudentAbility(student_id=sid, concept="alpha", class_level=6),
                PasswordReset(user_id=uid, token_hash="0" * 64, expires_at=NOW + timedelta(days=1)),
                EmailVerification(
                    user_id=uid, token_hash="1" * 64, expires_at=NOW + timedelta(days=1)
                ),
                Feedback(user_id=uid, rating=1),
            ]
        )
        s.commit()

    # every seeded row is present before the erasure
    assert _count(factory, DailyActivity, DailyActivity.student_id == sid) == 1
    assert _count(factory, StudentAbility, StudentAbility.student_id == sid) == 1

    deleted = client.delete("/users/me", headers=_headers(client, "s@example.com"))
    assert deleted.status_code == 204

    for model in (
        Student,
        ChapterProgress,
        DailyActivity,
        RevisionItem,
        ClassStudent,
        StudentInvite,
        SupportPlan,
        ConceptMastery,
        StudentAbility,
        PasswordReset,
        EmailVerification,
        Feedback,
    ):
        assert _count(factory, model) == 0, f"{model.__tablename__} survived the erasure"
    assert _count(factory, User, User.id == uid) == 0


def test_teacher_delete_removes_artifacts_keeps_anonymised_audit(pair) -> None:
    client, factory = pair
    prof = _register(client, "t@example.com", "teacher")
    tid, uid = prof["profile_id"], prof["user_id"]

    with factory() as s:
        school = School(name="Cascade School", code="CSC-1")
        s.add(school)
        s.flush()
        room = ClassRoom(school_id=school.id, class_level=6, section="GEN")
        s.add(room)
        s.flush()
        other = User(email="x@example.com", password_hash="x", role="teacher")
        s.add(other)
        s.flush()
        s.add_all(
            [
                ClassTeacher(classroom_id=room.id, teacher_id=tid),
                QuestionPaper(
                    teacher_id=uid,
                    class_level=6,
                    subject="math",
                    exam_type="exam",
                    marks=10,
                    duration_min=30,
                ),
                ShortTest(
                    classroom_id=room.id, teacher_id=uid, subject="math", chapter="a", questions=[]
                ),
                Assignment(
                    teacher_id=uid, subject="math", chapter="a", due_at=NOW + timedelta(days=1)
                ),
                QuestionBankEntry(
                    teacher_id=uid,
                    dedupe_key="k" * 64,
                    question_text="q?",
                    subject="math",
                    chapter="a",
                    class_level=6,
                ),
                ChapterContent(subject="math", class_level=6, chapter="a", created_by=uid),
                AuditLog(actor_user_id=uid, actor_role="teacher", action="qp_finalize"),
                SchoolInvite(code_hash="2" * 64, school_id=school.id, created_by=uid),
                SchoolInvite(
                    code_hash="3" * 64,
                    school_id=school.id,
                    created_by=uid,
                    used_by=other.id,
                    used_at=NOW,
                ),
            ]
        )
        s.commit()

    deleted = client.delete("/users/me", headers=_headers(client, "t@example.com"))
    assert deleted.status_code == 204

    assert _count(factory, Teacher, Teacher.id == tid) == 0
    for model in (ClassTeacher, QuestionPaper, ShortTest, Assignment, QuestionBankEntry):
        assert _count(factory, model) == 0, f"{model.__tablename__} survived the erasure"
    assert _count(factory, SchoolInvite) == 0
    # audit survives but loses attribution to the erased account
    with factory() as s:
        row = s.execute(select(AuditLog)).scalar_one()
        assert row.actor_user_id is None
        assert row.action == "qp_finalize"
    # shared content survives, authorless
    with factory() as s:
        content = s.execute(select(ChapterContent)).scalar_one()
        assert content.created_by is None


def test_parent_delete_nulls_redeemed_invite_pointer(pair) -> None:
    client, factory = pair
    prof = _register(client, "p@example.com", "parent")
    pid = prof["profile_id"]

    with factory() as s:
        kid_user = User(email="kid@example.com", password_hash="x", role="student")
        s.add(kid_user)
        s.flush()
        kid = Student(
            user_id=kid_user.id,
            name="Kid",
            class_level=6,
            consent_version="test-v1",
            consent_at=NOW,
        )
        s.add(kid)
        s.flush()
        s.add(
            ParentInvite(
                code_hash="4" * 64,
                student_id=kid.id,
                expires_at=NOW + timedelta(days=30),
                used_by_parent_id=pid,
                used_at=NOW,
            )
        )
        s.commit()

    deleted = client.delete("/users/me", headers=_headers(client, "p@example.com"))
    assert deleted.status_code == 204
    assert _count(factory, Parent, Parent.id == pid) == 0
    with factory() as s:
        invite = s.execute(select(ParentInvite)).scalar_one()
        assert invite.used_by_parent_id is None
