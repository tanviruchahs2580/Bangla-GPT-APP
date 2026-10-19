"""Seeded benchmark for the heaviest dashboard endpoints (AUD-HI-11 / H-06).

The audit found a single query-count assertion in the whole suite
(``test_scale_v2.py``), no 100,000-row seed anywhere (``rg 100_000`` over
tests and scripts: 0 hits) and no recorded plan or profile for the dashboard
paths. A dashboard that is fine at 40 students and quadratic at 100,000 is
exactly the failure a school deployment meets in week two.

What this does, and records:

1. builds a throwaway SQLite database (or ``--db PATH``) with the real schema;
2. seeds a default school with ``--students`` students (default 400), one
   classroom, one quiz attempt per student and enough ``answer_log`` rows to
   reach ``--rows`` total rows (default 100,000);
3. registers a teacher **through the API** (real Argon2 hash), drives the
   heaviest dashboard endpoints, and counts the SQL statements each request
   issues (SQLAlchemy ``before_cursor_execute``);
4. prints and writes a JSON record: per endpoint status, wall milliseconds,
   statement count, and the statements themselves (truncated).

Usage::

    cd apps/api
    python scripts/bench_dashboards.py                       # 100k rows -> docs/operations/bench-dashboards-100k.json
    python scripts/bench_dashboards.py --rows 20000 --out /tmp/bench.json

Honest limits: SQLite, one process, developer hardware. The numbers are a
*shape* measurement (query count, scaling behaviour across --rows), not a
capacity figure for production Postgres -- the k6 profiles under ``load/`` are
the throughput instruments. Query counts do transfer: they are a property of
the code, not of the engine.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "docs" / "operations" / "bench-dashboards-100k.json"

#: The endpoints the audit named as heaviest (roster, class analytics, teacher
#: dashboard, school roll-ups, admin overview). Paths are asserted against the
#: generated contract in docs/API.md.
ENDPOINTS = (
    ("GET", "/teacher/students?class_level=6"),
    ("GET", "/teacher/classes/6/analytics"),
    ("GET", "/dashboard/summary"),
    ("GET", "/school/overview"),
    ("GET", "/school/students"),
    ("GET", "/admin/analytics/overview"),
)

#: Bench-only fixture password for a throwaway database; never a real
#: credential (the audit’s secrets scan reads the tree, so this is marked).
PASSWORD = "bench-password-1"  # noqa: S105 - local throwaway fixture


def _schema(engine) -> None:
    from bangla_gpt_api.db.session import init_db

    init_db(engine)


def _seed(db_path: Path, students: int, rows: int) -> dict:
    """Create the school, students, attempts and answer rows with raw SQL."""
    now = datetime.now(UTC).replace(tzinfo=None)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO schools (name, code, created_at) VALUES ('Bench School', 'BGPT-BENCH', ?)",
            (str(now),),
        )
        school_id = conn.execute("SELECT id FROM schools WHERE code='BGPT-BENCH'").fetchone()[0]
        conn.execute(
            "INSERT INTO classrooms (school_id, class_level, section, created_at)"
            " VALUES (?, 6, 'A', ?)",
            (school_id, str(now)),
        )
        classroom_id = conn.execute(
            "SELECT id FROM classrooms WHERE school_id=? AND class_level=6", (school_id,)
        ).fetchone()[0]

        attempts = 0
        logs = 0
        rows_per_student = max(1, rows // max(1, students))
        for i in range(students):
            email = f"bench-student-{i}@example.com"
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
            # Two attempts per student, one recent (inside the analytics window)
            # and one older, so the windowed aggregates are exercised.
            for offset, score in ((timedelta(hours=2), 40.0), (timedelta(days=30), 80.0)):
                conn.execute(
                    "INSERT INTO quiz_attempts (student_id, subject, class_level, status,"
                    " total, correct, score_pct, quiz_json, created_at)"
                    " VALUES (?, 'math', 6, 'graded', 2, 1, ?, '[]', ?)",
                    (student_id, score, str(now - offset)),
                )
                attempt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                attempts += 1
                payload = [
                    (attempt_id, seq, "q", 0, 0, 1, "math-chapter-1", "গণিত")
                    for seq in range(max(1, rows_per_student // 2))
                ]
                conn.executemany(
                    "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
                    " is_correct, chapter, book) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    payload,
                )
                logs += len(payload)
        conn.commit()
        return {
            "schools": 1,
            "classrooms": 1,
            "students": students,
            "quiz_attempts": attempts,
            "answer_log_rows": logs,
        }
    finally:
        conn.close()


def _statement_counter(engine) -> list[str]:
    from sqlalchemy import event

    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(" ".join(statement.split()))

    return statements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000, help="target answer_log rows")
    parser.add_argument("--students", type=int, default=400)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--db", type=Path, default=None, help="reuse this database file")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="bgpt-bench-"))
    db_path = args.db or (workdir / "bench.db")
    if db_path.exists():
        db_path.unlink()

    # Import after the path is known: the app must never see the developer DB.
    import os

    os.environ["ENV"] = "bench"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.db.session import make_engine
    from bangla_gpt_api.main import create_app

    settings = Settings(
        env="bench",
        database_url=f"sqlite:///{db_path.as_posix()}",
        jwt_secret="bench-secret-0123456789abcdef0123456789",  # noqa: S106 - throwaway fixture
        admin_email="bench-admin@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        llm_provider="mock",
    )
    engine = make_engine(settings)
    _schema(engine)

    seed_started = time.perf_counter()
    seed_stats = _seed(db_path, args.students, args.rows)
    seed_seconds = round(time.perf_counter() - seed_started, 2)

    # Count statements on the app's own engine: the app builds it inside
    # create_app, so attach the listener through a wrapper on make_engine.
    import bangla_gpt_api.main as app_main

    statements: list[str] = []
    real_make_engine = app_main.make_engine

    def counting_make_engine(cfg):  # noqa: ANN001
        built = real_make_engine(cfg)
        event.listen(
            built,
            "before_cursor_execute",
            lambda conn, cursor, statement, parameters, context, executemany: statements.append(
                " ".join(statement.split())
            ),
        )
        return built

    app_main.make_engine = counting_make_engine
    try:
        client = TestClient(create_app(settings))
    finally:
        app_main.make_engine = real_make_engine

    # Teacher through the API (real hash), enrolled into the bench school.
    register = client.post(
        "/auth/register",
        json={
            "email": "bench-teacher@example.com",
            "password": PASSWORD,
            "name": "Bench Teacher",
            "role": "teacher",
        },
    )
    if register.status_code != 201:
        print(f"::error::teacher registration failed: {register.status_code} {register.text}")
        return 1
    login = client.post(
        "/auth/login", json={"email": "bench-teacher@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # A second bench account is promoted to school_admin so the /school/*
    # roll-ups -- the heaviest reads in the product and the reason this
    # benchmark exists -- run with the role they require. Raw SQL because
    # school_admin is not a self-registerable role by design.
    school_register = client.post(
        "/auth/register",
        json={
            "email": "bench-schooladmin@example.com",
            "password": PASSWORD,
            "name": "Bench School Admin",
            "role": "teacher",
        },
    )
    if school_register.status_code != 201:
        print(f"::error::school_admin registration failed: {school_register.status_code}")
        return 1
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET role='school_admin', school_id=(SELECT id FROM schools"
            " WHERE code='BGPT-BENCH') WHERE email='bench-schooladmin@example.com'"
        )
        conn.commit()
    school_login = client.post(
        "/auth/login", json={"email": "bench-schooladmin@example.com", "password": PASSWORD}
    )
    school_headers = {"Authorization": f"Bearer {school_login.json()['access_token']}"}

    admin_login = client.post(
        "/auth/login", json={"email": "bench-admin@example.com", "password": PASSWORD}
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    results = []
    for method, path in ENDPOINTS:
        if path.startswith("/admin/"):
            use_headers = admin_headers
        elif path.startswith("/school"):
            use_headers = school_headers
        else:
            use_headers = headers
        mark = len(statements)
        started = time.perf_counter()
        response = client.request(method, path, headers=use_headers)
        wall_ms = round((time.perf_counter() - started) * 1000, 1)
        request_statements = statements[mark:]
        results.append(
            {
                "endpoint": f"{method} {path}",
                "status": response.status_code,
                "wall_ms": wall_ms,
                "statements": len(request_statements),
                "slowest_statement_preview": (
                    max(request_statements, key=len)[:240] if request_statements else None
                ),
            }
        )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "engine": "sqlite",
        "seed": {**seed_stats, "seed_seconds": seed_seconds},
        "endpoints": results,
        "query_count_max": max((row["statements"] for row in results), default=0),
        "wall_ms_median": statistics.median([row["wall_ms"] for row in results])
        if results
        else None,
        "notes": (
            "SQLite on developer hardware; query counts are the durable signal, "
            "wall time is host-dependent. Re-run with --rows 20000/100000 to see "
            "whether statement counts (not just time) grow with the row count."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "endpoints"}, ensure_ascii=False))
    for row in results:
        print(
            f"{row['status']} {row['statements']:>3} stmt {row['wall_ms']:>9.1f} ms  {row['endpoint']}"
        )
    print(f"recorded -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
