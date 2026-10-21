"""H-06 / I-07: query-count assertions for the heaviest dashboard endpoints.

The audit found exactly one statement-count assertion in the whole suite
(``test_scale_v2.py``) and no evidence about the teacher/school/admin
dashboards at scale. These tests pin the property that makes a dashboard
survive 100,000 rows: **the number of SQL statements a request issues must not
grow with the number of rows or students it summarises** (no 1+N).

Two assertions per endpoint, deliberately:

* an absolute ceiling (with headroom over today's count, so a legitimate extra
  query for one more aggregate does not fail the build), and
* equality between a small and a larger seeded cohort — the growth check. Only
  the second one actually catches an N+1; the first one catches an accidental
  cartesian join or a per-row lookup loop.

The recorded 100k-row benchmark lives in
``apps/api/scripts/bench_dashboards.py`` ->
``docs/operations/bench-dashboards-100k.json``.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import bangla_gpt_api.main as bgpt_main
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JWT_SECRET = "test-secret-0123456789abcdef0123456789"

#: Absolute ceilings, chosen with headroom over the measured counts (see the
#: benchmark output); the important assertion is the growth check below.
CEILINGS = {
    "/teacher/students?class_level=6": 8,
    "/teacher/classes/6/analytics": 12,
    "/dashboard/summary": 6,
    "/admin/analytics/overview": 10,
    "/school/students": 14,
    "/school/overview": 14,
}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/hi_dash.db",
        jwt_secret=JWT_SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )


class _Env:
    def __init__(self, client: TestClient, db_path: Path, statements: list[str]) -> None:
        self.client = client
        self.db_path = db_path
        self.statements = statements

    def count(self, method: str, path: str, headers: dict) -> tuple[int, int]:
        mark = len(self.statements)
        response = self.client.request(method, path, headers=headers)
        return response.status_code, len(self.statements) - mark


@pytest.fixture
def env(tmp_path, monkeypatch) -> _Env:
    settings = _settings(tmp_path)
    db_path = tmp_path / "hi_dash.db"
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
    client = TestClient(create_app(settings))
    return _Env(client, db_path, statements)


def _seed_cohort(db_path: Path, students: int, start_index: int = 0) -> None:
    """One school + classroom + N students with attempts and answer rows."""
    now = datetime.now(UTC).replace(tzinfo=None)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if not conn.execute("SELECT id FROM schools WHERE code='BGPT-DEFAULT'").fetchone():
            conn.execute(
                "INSERT INTO schools (name, code, created_at) VALUES ('Default', 'BGPT-DEFAULT', ?)",
                (str(now),),
            )
        school_id = conn.execute("SELECT id FROM schools WHERE code='BGPT-DEFAULT'").fetchone()[0]
        if not conn.execute(
            "SELECT id FROM classrooms WHERE school_id=? AND class_level=6 AND section='HI'",
            (school_id,),
        ).fetchone():
            conn.execute(
                "INSERT INTO classrooms (school_id, class_level, section, created_at)"
                " VALUES (?, 6, 'HI', ?)",
                (school_id, str(now)),
            )
        classroom_id = conn.execute(
            "SELECT id FROM classrooms WHERE school_id=? AND class_level=6 AND section='HI'",
            (school_id,),
        ).fetchone()[0]
        for i in range(start_index, start_index + students):
            email = f"dash-student-{i}@example.com"
            conn.execute(
                "INSERT INTO users (email, password_hash, role, created_at)"
                " VALUES (?, 'x', 'student', ?)",
                (email, str(now)),
            )
            user_id = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
            conn.execute(
                "INSERT INTO students (user_id, name, class_level, consent_version, consent_at,"
                " created_at) VALUES (?, ?, 6, 'T-1', ?, ?)",
                (user_id, f"শিক্ষার্থী {i}", str(now), str(now)),
            )
            student_id = conn.execute(
                "SELECT id FROM students WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO class_students (classroom_id, student_id, created_at) VALUES (?, ?, ?)",
                (classroom_id, student_id, str(now)),
            )
            conn.execute(
                "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
                " correct, score_pct, quiz_json, created_at)"
                " VALUES (?, 'math', 6, 'graded', 4, 3, 75.0, '[]', ?)",
                (student_id, str(now - timedelta(hours=1))),
            )
            attempt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.executemany(
                "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
                " is_correct, chapter, book) VALUES (?, ?, 'q', 0, 0, ?, ?, 'গণিত')",
                [(attempt_id, seq, seq % 2, "math-chapter-1") for seq in range(20)],
            )
        conn.commit()
    finally:
        conn.close()


def _teacher(env: _Env, email: str = "dash-teacher@example.com") -> dict:
    res = env.client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    login = env.client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _school_admin(env: _Env, email: str = "dash-admin@example.com") -> dict:
    res = env.client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "School Admin", "role": "teacher"},
    )
    assert res.status_code == 201, res.text
    conn = sqlite3.connect(env.db_path)
    try:
        conn.execute(
            "UPDATE users SET role='school_admin', school_id="
            "(SELECT id FROM schools WHERE code='BGPT-DEFAULT') WHERE email=?",
            (email,),
        )
        conn.commit()
    finally:
        conn.close()
    login = env.client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _admin(env: _Env) -> dict:
    login = env.client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _headers_for(env: _Env, path: str, teacher: dict, school_admin: dict, admin: dict) -> dict:
    if path.startswith("/admin/"):
        return admin
    if path.startswith("/school"):
        return school_admin
    return teacher


def test_dashboard_endpoints_issue_a_bounded_number_of_statements(env: _Env) -> None:
    _seed_cohort(env.db_path, 20)
    teacher = _teacher(env)
    school_admin = _school_admin(env)
    admin = _admin(env)
    for path, ceiling in CEILINGS.items():
        headers = _headers_for(env, path, teacher, school_admin, admin)
        status, statements = env.count("GET", path, headers)
        assert status == 200, f"{path} -> {status}"
        assert statements <= ceiling, f"{path} issued {statements} statements (ceiling {ceiling})"


def test_dashboard_statement_counts_do_not_grow_with_the_cohort(env: _Env) -> None:
    """The N+1 check: double the cohort, the statement count must not move."""
    _seed_cohort(env.db_path, 20)
    teacher = _teacher(env)
    school_admin = _school_admin(env)
    admin = _admin(env)

    before = {
        path: env.count("GET", path, _headers_for(env, path, teacher, school_admin, admin))
        for path in CEILINGS
    }
    _seed_cohort(env.db_path, 40, start_index=20)
    after = {
        path: env.count("GET", path, _headers_for(env, path, teacher, school_admin, admin))
        for path in CEILINGS
    }

    for path in CEILINGS:
        assert before[path][0] == 200 and after[path][0] == 200, (path, before[path], after[path])
        # ``<=`` rather than ``==``: a response cache (dashboard summary) can
        # make the second call issue *fewer* statements, which is not an N+1.
        # Growth is the failure mode this test exists to catch.
        assert after[path][1] <= before[path][1], (
            f"{path} statement count grew with the cohort "
            f"({before[path][1]} -> {after[path][1]}) -- that is an N+1"
        )
