"""S5.5 PASS-WHEN: pagination/N+1 audit fixes -- batched reads, capped lists.

Every test here pins behaviour that the scale audit changed:
* roster briefs come from ONE grouped query (statement-counted), not 1+N,
  with identical values to the old per-student loop (incl. NULL-score rows);
* conversation message_count via one GROUP BY (incl. empty conversations);
* message list capped, newest-N returned chronological;
* /assignments/mine windowed + attempt batch fetch, correct done flags;
* teacher qpaper/shorttest/assignment lists page via limit/offset.
"""

import json
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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/scale.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )


@pytest.fixture
def env(tmp_path):
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/scale.db")
    yield client, conn, settings
    conn.close()


def _register(client: TestClient, role: str, email: str, **kw) -> dict:
    payload = {"email": email, "password": PASSWORD, "role": role, "name": "Tester"}
    payload.update(kw)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ts(dt: datetime) -> str:
    return str(dt)


def _seed_student(conn: sqlite3.Connection, email: str, class_level: int = 6) -> int:
    now = _ts(datetime.now(UTC).replace(tzinfo=None))
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, 'x', 'student', ?)",
        (email, now),
    )
    uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    conn.execute(
        "INSERT INTO students (user_id, name, class_level, consent_version, consent_at, created_at)"
        " VALUES (?, ?, ?, 'T-1', ?, ?)",
        (uid, f"S{class_level}-{uid}", class_level, now, now),
    )
    sid = conn.execute("SELECT id FROM students WHERE user_id=?", (uid,)).fetchone()[0]
    return int(sid)


def _seed_attempt(
    conn: sqlite3.Connection,
    student_id: int,
    score: float | None,
    when: datetime,
    status: str = "graded",
) -> int:
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
        " score_pct, quiz_json, created_at) VALUES (?, 'math', 6, ?, 2, 1, ?, '[]', ?)",
        (student_id, status, score, _ts(when)),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


# --------------------------------------------------------------------------
# roster: batched aggregate, identical values, one quiz_attempts statement
# --------------------------------------------------------------------------


def test_roster_briefs_batched_and_identical(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    statements: list[str] = []
    real = bgpt_main.make_engine

    def wrapping_make_engine(cfg: Settings):
        eng = real(cfg)
        event.listen(
            eng,
            "before_cursor_execute",
            lambda c, cur, st, p, ctx, em: statements.append(st),
        )
        return eng

    monkeypatch.setattr(bgpt_main, "make_engine", wrapping_make_engine)
    client = TestClient(create_app(settings))
    teacher = _register(client, "teacher", "t@scale.test")
    conn = sqlite3.connect(f"{tmp_path}/scale.db")
    now = datetime.now(UTC).replace(tzinfo=None)
    s1 = _seed_student(conn, "s1@scale.test")
    s2 = _seed_student(conn, "s2@scale.test")
    _seed_student(conn, "s3@scale.test")  # zero attempts
    s4 = _seed_student(conn, "s4@scale.test")
    _seed_attempt(conn, s1, 40.0, now - timedelta(hours=2))
    _seed_attempt(conn, s1, 80.0, now - timedelta(hours=1))
    _seed_attempt(conn, s2, 55.5, now)
    _seed_attempt(conn, s4, None, now)  # graded row without a score
    conn.commit()
    conn.close()

    mark = len(statements)
    res = client.get("/teacher/students", headers=teacher, params={"class_level": 6})
    assert res.status_code == 200, res.text
    window = [s.lower() for s in statements[mark:]]

    by_id = {b["student_id"]: b for b in res.json()}
    assert by_id[s1]["attempts_graded"] == 2 and by_id[s1]["avg_score_pct"] == 60.0
    assert by_id[s2]["attempts_graded"] == 1 and by_id[s2]["avg_score_pct"] == 55.5
    assert by_id[s2]["student_id"] == s2
    s3_row = next(b for b in res.json() if b["student_id"] not in (s1, s2, s4))
    assert s3_row["attempts_graded"] == 0 and s3_row["avg_score_pct"] is None
    s4_row = by_id[s4]
    assert s4_row["attempts_graded"] == 1 and s4_row["avg_score_pct"] is None

    # the N+1 proof: ONE quiz_attempts statement for 4 students (old: one each)
    attempt_stmts = [s for s in window if "quiz_attempts" in s and s.strip().startswith("select")]
    assert len(attempt_stmts) == 1, window


def test_teacher_students_limit(tmp_path) -> None:
    client, conn, _ = env_of(tmp_path)
    teacher = _register(client, "teacher", "t2@scale.test")
    ids = [_seed_student(conn, f"k{i}@scale.test") for i in range(5)]
    conn.commit()
    res = client.get("/teacher/students", headers=teacher, params={"limit": 3})
    assert res.status_code == 200
    assert [b["student_id"] for b in res.json()] == ids[:3]


def env_of(tmp_path):
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/scale.db")
    return client, conn, settings


# --------------------------------------------------------------------------
# chat: capped message page + batched counts
# --------------------------------------------------------------------------


def test_messages_capped_and_conversation_counts(env) -> None:
    client, conn, _ = env
    student = _register(client, "student", "kid@scale.test", guardian_consent=True, class_level=6)
    sid = conn.execute(
        "SELECT id FROM students WHERE user_id=( SELECT id FROM users WHERE email='kid@scale.test')"
    ).fetchone()[0]
    now = datetime.now(UTC).replace(tzinfo=None)
    counts = {}
    for title, n in (("full", 5), ("empty", 0)):
        conn.execute(
            "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
            " VALUES (?, ?, NULL, ?)",
            (sid, title, _ts(now)),
        )
        cid = conn.execute(
            "SELECT id FROM conversations WHERE student_id=? AND title=?", (sid, title)
        ).fetchone()[0]
        counts[title] = cid
        for i in range(n):
            conn.execute(
                "INSERT INTO chat_messages (conversation_id, role, content, grounded,"
                " refused_reason, sources_json, rating, created_at)"
                " VALUES (?, 'user', ?, 1, NULL, '[]', NULL, ?)",
                (cid, f"m{i}", _ts(now)),
            )
    conn.commit()

    listing = client.get("/tutor/conversations", headers=student)
    assert listing.status_code == 200
    by_title = {c["title"]: c["message_count"] for c in listing.json()}
    assert by_title == {"full": 5, "empty": 0}

    full = client.get(f"/tutor/conversations/{counts['full']}/messages", headers=student)
    assert [m["content"] for m in full.json()] == [f"m{i}" for i in range(5)]

    capped = client.get(
        f"/tutor/conversations/{counts['full']}/messages", headers=student, params={"limit": 3}
    )
    # newest 3, still chronological
    assert [m["content"] for m in capped.json()] == ["m2", "m3", "m4"]


# --------------------------------------------------------------------------
# /assignments/mine: windowed scan + batched attempts
# --------------------------------------------------------------------------


def test_assignments_mine_window_and_flags(tmp_path) -> None:
    client, conn, settings = env_of(tmp_path)
    teacher = _register(client, "teacher", "t3@scale.test")
    student = _register(client, "student", "kid3@scale.test", guardian_consent=True, class_level=6)
    tid = conn.execute("SELECT id FROM users WHERE email='t3@scale.test'").fetchone()[0]
    sid = conn.execute(
        "SELECT id FROM students WHERE user_id=("
        " SELECT id FROM users WHERE email='kid3@scale.test')"
    ).fetchone()[0]
    now = datetime.now(UTC).replace(tzinfo=None)
    q_json = json.dumps([{"id": "q1", "question_text": "2+2?", "options": ["3", "4"]}])
    made = []
    for i, hrs in enumerate((0, 1, 2)):  # newest first by created_at desc
        # i=0 graded with score, i=1 graded without one (still done), i=2 pending
        aid_attempt = _seed_attempt(
            conn, sid, 70.0 if i == 0 else None, now, status="graded" if i < 2 else "pending"
        )
        conn.execute(
            "INSERT INTO assignments (teacher_id, subject, chapter, num_questions, due_at,"
            " questions, attempts, created_at) VALUES (?, 'math', 'Algebra', 1, ?, ?, ?, ?)",
            (
                tid,
                _ts(now + timedelta(days=1)),
                q_json,
                json.dumps([{"student_id": sid, "attempt_id": aid_attempt}]),
                _ts(now - timedelta(hours=hrs)),
            ),
        )
        made.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
    # an assignment NOT addressed to this student must never appear
    conn.execute(
        "INSERT INTO assignments (teacher_id, subject, chapter, num_questions, due_at,"
        " questions, attempts, created_at) VALUES (?, 'math', 'Geometry', 1, ?, ?, '[]', ?)",
        (tid, _ts(now), q_json, _ts(now)),
    )
    conn.commit()

    res = client.get("/assignments/mine", headers=student)
    assert res.status_code == 200
    items = res.json()
    # made[0] was seeded with created_at = now, so newest-first == insertion order
    assert [a["id"] for a in items] == made
    assert items[0]["done"] is True  # graded attempt with a score
    assert items[1]["done"] is True  # graded attempt, NULL score: still done
    assert items[-1]["done"] is False  # pending attempt: not done

    win = client.get("/assignments/mine", headers=student, params={"limit": 2})
    assert win.status_code == 200
    # limit windows the SCAN of the newest N assignments, not a page of mine:
    # the Geometry row (same created_at, higher id -> newest, not addressed to
    # this student) consumes one slot, leaving only made[0]
    assert [a["id"] for a in win.json()] == [made[0]]

    # the teacher-side progress page batches too (1+2N -> 1+2)
    prog = client.get(f"/teacher/assignments/{made[0]}/progress", headers=teacher)
    assert prog.status_code == 200
    assert prog.json()[0]["student_id"] == sid and prog.json()[0]["done"] is True


# --------------------------------------------------------------------------
# teacher list pagination
# --------------------------------------------------------------------------


def test_qp_and_shorttest_pagination(env) -> None:
    client, conn, _ = env
    teacher = _register(client, "teacher", "t4@scale.test")
    tid = conn.execute("SELECT id FROM users WHERE email='t4@scale.test'").fetchone()[0]
    now = datetime.now(UTC).replace(tzinfo=None)
    qp_ids = []
    for hrs in (0, 1, 2):
        conn.execute(
            "INSERT INTO question_papers (teacher_id, class_level, subject, exam_type, marks,"
            " duration_min, difficulty, chapters, status, questions, meta, created_at)"
            " VALUES (?, 6, 'math', 'exam', 50, 60, '{}', '[]', 'draft', '[]', '{}', ?)",
            (tid, _ts(now - timedelta(hours=hrs))),
        )
        qp_ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
    st_ids = []
    for hrs in (0, 1, 2):
        conn.execute(
            "INSERT INTO short_tests (classroom_id, teacher_id, subject, chapter,"
            " num_questions, duration_min, questions, attempts, created_at)"
            " VALUES (1, ?, 'math', 'Algebra', 5, 10, '[]', '[]', ?)",
            (tid, _ts(now - timedelta(hours=hrs))),
        )
        st_ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
    conn.commit()

    qp1 = client.get("/teacher/qpapers", headers=teacher, params={"limit": 2})
    assert [q["id"] for q in qp1.json()] == qp_ids[:2]
    qp2 = client.get("/teacher/qpapers", headers=teacher, params={"limit": 2, "offset": 2})
    assert [q["id"] for q in qp2.json()] == [qp_ids[-1]]

    st1 = client.get("/teacher/shorttests", headers=teacher, params={"limit": 2})
    assert [s["id"] for s in st1.json()] == st_ids[:2]
    st2 = client.get("/teacher/shorttests", headers=teacher, params={"limit": 2, "offset": 2})
    assert [s["id"] for s in st2.json()] == [st_ids[-1]]

    # default (no params) still answers with all three rows: contract intact
    assert len(client.get("/teacher/qpapers", headers=teacher).json()) == 3
