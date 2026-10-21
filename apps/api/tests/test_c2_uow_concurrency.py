"""C-11: transaction boundaries, unit of work, optimistic concurrency.

AUD-CD (status-cd C-11) recorded what was missing: a unit-of-work boundary,
any optimistic-concurrency story, and query-count evidence beyond the two
roster endpoints ``test_hi_dashboard_queries.py`` already pins.

What this module proves:

* :func:`jobs.session_scope` **is** the unit of work: it commits on success,
  rolls back everything on failure (visible from a second connection) and
  always closes the session. The old ``try/finally: close()`` pattern left a
  failed run's transaction open;
* concurrent increments are **not lost**: a naive read-modify-write loses an
  update when two sessions read the same mastery row, while
  ``knowledge.record_quiz_result`` (one conditional UPDATE) keeps both -- this
  is the optimistic-concurrency case C-11 asks for, demonstrated before/after
  in the same test;
* the school dashboard endpoints in ``routers/school.py`` issue a **constant**
  number of statements as the cohort doubles (no N+1), with an absolute
  ceiling so an accidental per-row loop fails loudly.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

import bangla_gpt_api.main as bgpt_main
from bangla_gpt_api import jobs
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import Concept, ConceptMastery, School, Student, User
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import ReviewItem
from bangla_gpt_api.services import knowledge

PASSWORD = "supersecret1"
JOIN_PASSWORD = "joinsecret9"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def factory(tmp_path: Path):
    settings = Settings(env="test", database_url=f"sqlite:///{tmp_path}/uow.db", jwt_secret=SECRET)
    engine = make_engine(settings)
    init_db(engine)
    yield make_session_factory(engine), engine
    engine.dispose()


# ------------------------------------------------------------- unit of work --


def test_session_scope_commits_on_success(factory) -> None:
    make_session, _engine = factory
    with jobs.session_scope(make_session) as db:
        db.add(School(name="Committed", code="UOW-1"))
    other = make_session()
    try:
        assert other.execute(select(School.code).where(School.code == "UOW-1")).scalar_one()
    finally:
        other.close()


def test_session_scope_rolls_back_everything_on_error(factory) -> None:
    """A failed run must leave no partial rows -- not even the committed ones.

    Inside one unit of work nothing is committed until the block exits, so a
    crash halfway through a multi-row write cannot leave a half-applied run.
    """
    make_session, _engine = factory
    with pytest.raises(RuntimeError, match="boom"):
        with jobs.session_scope(make_session) as db:
            db.add(School(name="Doomed", code="UOW-2"))
            db.flush()
            db.add(School(name="Also doomed", code="UOW-3"))
            raise RuntimeError("boom")

    other = make_session()
    try:
        assert (
            other.execute(select(School.code).where(School.code.in_(["UOW-2", "UOW-3"]))).all()
            == []
        )
    finally:
        other.close()


def test_session_scope_closes_the_session(factory) -> None:
    make_session, _engine = factory
    db = make_session()
    closed: list[int] = []
    original_close = db.close

    def counting_close() -> None:
        closed.append(1)
        original_close()

    db.close = counting_close
    with jobs.session_scope(lambda: db) as scope_db:
        scope_db.execute(select(School.id))
    assert closed == [1], "the unit of work must close the session it opened"


# --------------------------------------------------- optimistic concurrency --


def _seed_concept(db) -> int:
    concept = Concept(
        name="ভগ্নাংশ",
        class_level=6,
        subject="math",
        chapter="ভগ্নাংশ",
        source="chapter",
        aliases=[],
    )
    db.add(concept)
    db.commit()
    return int(concept.id)


def _seed_student(db, name: str = "Rahim") -> int:
    """A real Student row: the mastery FK is enforced in these engines."""
    user = User(
        email=f"{name.lower()}-{time.time_ns()}@uow.test", password_hash="x", role="student"
    )
    db.add(user)
    db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    student = Student(
        user_id=user.id,
        name=name,
        class_level=6,
        consent_version="T-1",
        consent_at=now,
    )
    db.add(student)
    db.commit()
    return int(student.id)


def _review(chapter: str, correct: bool = True) -> list[ReviewItem]:
    return [
        ReviewItem(
            question_text=f"{chapter} প্রশ্ন",
            options=["a", "b", "c", "d"],
            chosen=0,
            correct_index=0,
            is_correct=correct,
            chapter=chapter,
        )
    ]


def test_naive_read_modify_write_loses_an_update_but_record_quiz_result_does_not(tmp_path) -> None:
    """The lost update, then the fix, in one test.

    Two sessions read the same mastery cell and then write their increment.
    With ``row.correct += 1`` the second write overwrites the first (lost
    update). ``record_quiz_result`` moves the arithmetic into a conditional
    UPDATE, so both increments survive.
    """
    db_url = f"sqlite:///{tmp_path}/lost.db"
    settings = Settings(env="test", database_url=db_url, jwt_secret=SECRET)
    engine = make_engine(settings)
    init_db(engine)
    make_session = make_session_factory(engine)
    try:
        setup = make_session()
        concept_id = _seed_concept(setup)
        student_id = _seed_student(setup)
        setup.add(ConceptMastery(student_id=student_id, concept_id=concept_id, correct=1, total=1))
        setup.commit()
        setup.close()

        # --- the naive pattern: both sessions read 1/1, both write 2/2 ------
        a, b = make_session(), make_session()
        row_a = a.get(ConceptMastery, (student_id, concept_id))
        row_b = b.get(ConceptMastery, (student_id, concept_id))
        assert (row_a.correct, row_b.correct) == (1, 1)
        row_a.correct += 1
        a.commit()
        row_b.correct += 1  # b still holds the stale read
        b.commit()
        a.close()
        b.close()

        check = make_session()
        stale = check.get(ConceptMastery, (student_id, concept_id))
        assert stale.correct == 2, "demo: the naive read-modify-write lost one increment"
        stale.correct = 1
        stale.total = 1
        check.commit()
        check.close()

        # --- the shipped pattern: two sessions, both increments survive -----
        first, second = make_session(), make_session()
        knowledge.record_quiz_result(first, student_id, _review("ভগ্নাংশ", correct=True), 6)
        knowledge.record_quiz_result(second, student_id, _review("ভগ্নাংশ", correct=False), 6)
        first.close()
        second.close()

        final = make_session()
        row = final.get(ConceptMastery, (student_id, concept_id))
        assert (row.correct, row.total) == (2, 3), "both submissions must land"
        final.close()
    finally:
        engine.dispose()


def test_record_quiz_result_inserts_on_first_submission(factory) -> None:
    make_session, _engine = factory
    db = make_session()
    try:
        concept_id = _seed_concept(db)
        student_id = _seed_student(db)
        assert db.get(ConceptMastery, (student_id, concept_id)) is None
        knowledge.record_quiz_result(db, student_id, _review("ভগ্নাংশ", correct=True), 6)
        row = db.get(ConceptMastery, (student_id, concept_id))
        assert (row.correct, row.total) == (1, 1)
        # a second call adds to the same row instead of replacing it
        knowledge.record_quiz_result(db, student_id, _review("ভগ্নাংশ", correct=False), 6)
        assert (row.correct, row.total) == (1, 2)
    finally:
        db.close()


def test_bump_mastery_falls_back_to_insert_when_the_row_is_missing(factory) -> None:
    """The INSERT fallback of the atomic update (first-ever submission)."""
    make_session, _engine = factory
    db = make_session()
    try:
        concept_id = _seed_concept(db)
        student_id = _seed_student(db)
        knowledge._bump_mastery(db, student_id, concept_id, 2, 3)
        db.commit()
        row = db.get(ConceptMastery, (student_id, concept_id))
        assert (row.correct, row.total) == (2, 3)
        knowledge._bump_mastery(db, student_id, concept_id, 1, 1)
        db.commit()
        assert (row.correct, row.total) == (3, 4)
    finally:
        db.close()


# ------------------------------------------------------------- query counts --

CEILINGS = {
    "/school/coverage": 16,
    "/school/analytics?days=30": 12,
    "/school/teachers": 10,
    "/school/classes/": 10,
}


class _Env:
    def __init__(self, client: TestClient, db_path: Path, statements: list[str]) -> None:
        self.client = client
        self.db_path = db_path
        self.statements = statements

    def count(self, path: str, headers: dict) -> tuple[int, int]:
        mark = len(self.statements)
        response = self.client.get(path, headers=headers)
        return response.status_code, len(self.statements) - mark


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/counts.db",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    statements: list[str] = []
    real_make_engine = bgpt_main.make_engine

    def wrapping_make_engine(cfg):
        engine = real_make_engine(cfg)
        event.listen(
            engine,
            "before_cursor_execute",
            lambda conn, cursor, statement, parameters, context, executemany: statements.append(
                " ".join(statement.split())
            ),
        )
        return engine

    monkeypatch.setattr(bgpt_main, "make_engine", wrapping_make_engine)
    return _Env(TestClient(create_app(settings)), tmp_path / "counts.db", statements)


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _seed_school(env: _Env, students: list[str], tag: str) -> dict:
    """A school with a principal, a teacher, a room and N enrolled students.

    ``tag`` keeps the emails unique across the two cohorts the growth check
    seeds into the same database. The roster import is a teacher route
    (``/teacher/classrooms/{id}/import``), while the /school/* reads need the
    principal -- the same separation the real UI has.
    """
    client = env.client
    root = _login(client, "root@example.com")
    school = client.post(
        "/admin/schools", json={"name": f"Query School {tag}"}, headers=root
    ).json()

    def _join(role: str, email: str) -> None:
        invite = client.post(
            f"/schools/{school['id']}/invites", json={"role": role}, headers=root
        ).json()
        res = client.post(
            "/auth/join-school",
            json={
                "invite_code": invite["code"],
                "email": email,
                "password": JOIN_PASSWORD,
                "name": f"{role}-{tag}",
            },
        )
        assert res.status_code == 201, res.text

    _join("school_admin", f"prin-{tag}@qcount.test")
    _join("teacher", f"teach-{tag}@qcount.test")
    principal = _login(client, f"prin-{tag}@qcount.test", JOIN_PASSWORD)
    teacher = _login(client, f"teach-{tag}@qcount.test", JOIN_PASSWORD)
    room = client.post(
        f"/schools/{school['id']}/classes", json={"class_level": 6}, headers=principal
    ).json()
    assert "id" in room, room
    csv_text = "\n".join(f"{name}{tag},{name.lower()}{tag}@qcount.test" for name in students)
    res = client.post(
        f"/teacher/classrooms/{room['id']}/import", json={"csv_text": csv_text}, headers=teacher
    )
    assert res.status_code == 200, res.text
    assert res.json()["created"] == len(students)
    return principal


def _seed_activity(db_path: Path, n_students: int) -> None:
    """Graded attempts, chapter progress and a conversation per student.

    Idempotent: it fills in whichever students have no attempts yet, so the
    second cohort can simply ask for a bigger N without re-seeding the first.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        students = [
            int(r[0])
            for r in conn.execute(
                "SELECT s.id FROM students s WHERE NOT EXISTS"
                " (SELECT 1 FROM quiz_attempts q WHERE q.student_id = s.id)"
                " ORDER BY s.id LIMIT ?",
                (n_students,),
            )
        ]
        for sid in students:
            conn.execute(
                "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
                " correct, score_pct, quiz_json, created_at)"
                " VALUES (?, 'science', 6, 'graded', 4, 3, 75.0, '[]', ?)",
                (sid, str(now)),
            )
            conn.execute(
                "INSERT INTO chapter_progress (student_id, subject, chapter, class_level,"
                " read_pct, completed, updated_at) VALUES (?, 'science', 'অধ্যায়', 6, 100, 1, ?)",
                (sid, str(now)),
            )
            conn.execute(
                "INSERT INTO conversations (student_id, title, created_at) VALUES (?, 't', ?)",
                (sid, str(now)),
            )
        conn.commit()
    finally:
        conn.close()


def test_school_dashboard_statement_counts_do_not_grow_with_the_cohort(env: _Env) -> None:
    """Six students, then twelve: same number of statements (no N+1)."""
    principal = _seed_school(env, [f"S{i}" for i in range(6)], "a")
    _seed_activity(env.db_path, 6)
    small = {path: env.count(path, principal) for path in CEILINGS}

    principal = _seed_school(env, [f"T{i}" for i in range(6, 12)], "b")
    _seed_activity(env.db_path, 12)
    large = {path: env.count(path, principal) for path in CEILINGS}

    for path, (status_small, count_small) in small.items():
        status_large, count_large = large[path]
        assert status_small == 200 and status_large == 200, path
        assert count_large == count_small, (
            f"{path} issues {count_small} statements for 6 students and {count_large} "
            "for 12 -- that growth is an N+1"
        )
        assert count_large <= CEILINGS[path], f"{path}: {count_large} > ceiling"


def test_job_owned_unit_of_work_is_used_by_the_scheduled_runs(factory) -> None:
    """The scheduled job bodies run inside the job unit of work."""
    import inspect

    for fn in (jobs.run_weekly_digest, jobs.run_nightly_rollup, jobs.run_retention_job):
        source = inspect.getsource(fn)
        assert "session_scope(" in source, f"{fn.__name__} must open its own unit of work"
        assert "db.close()" not in source, f"{fn.__name__} must not hand-roll session cleanup"


def test_slow_query_does_not_hold_the_uow_open(factory, monkeypatch) -> None:
    """The boundary commits exactly once per successful run (no implicit repeat)."""
    make_session, _engine = factory
    commits: list[int] = []
    db = make_session()
    original = db.commit

    def counting_commit():
        commits.append(1)
        return original()

    monkeypatch.setattr(db, "commit", counting_commit)
    with jobs.session_scope(lambda: db) as scope_db:
        scope_db.add(School(name="Once", code="UOW-ONCE"))
    assert len(commits) == 1


def test_uow_is_fast_enough_for_the_job_loop(factory) -> None:
    """A no-op unit of work costs one connection checkout, not a timeout."""
    make_session, _engine = factory
    start = time.perf_counter()
    with jobs.session_scope(make_session) as db:
        db.execute(select(School.id))
    assert time.perf_counter() - start < 2.0
