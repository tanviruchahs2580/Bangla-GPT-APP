"""S4.6 PASS-WHEN: the weakness rollup is the SINGLE source of truth.

"Same value from all three endpoints" is the spec gate: Home
(/dashboard/summary), Teacher at-risk (/teacher/weak-matrix) and the Parent
digest (/parents/.../progress + the weekly email) must all agree because all
of them call services.weakness -- nothing here re-implements the rule.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services import knowledge, weakness
from bangla_gpt_api.services.parent_digest import run_weekly_digest

PASSWORD = "supersecret1"

# alpha 0/4 (0%, weak) | beta 1/4 (25%, weak) | gamma 2/4 (50%, NOT < 50)
# delta 0/2 (0% but < MIN_ATTEMPTS=3)  ->  expected rollup ["alpha", "beta"]
CELLS: dict[str, tuple[int, int]] = {
    "alpha": (0, 4),
    "beta": (1, 4),
    "gamma": (2, 4),
    "delta": (0, 2),
}
EXPECTED = ["alpha", "beta"]


def _ts(dt: datetime) -> str:
    return str(dt)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------- pure rules ----------


def test_nightly_due_rule() -> None:
    before = datetime(2026, 9, 7, 20, 59)
    at = datetime(2026, 9, 7, 21, 0)
    assert weakness.nightly_due(before, "") == (False, "")
    due, day = weakness.nightly_due(at, "")
    assert due and day == "2026-09-07"
    # already ran today -> deduped (keeps the day key)
    assert weakness.nightly_due(at, day) == (False, day)
    # a new day fires again
    due2, day2 = weakness.nightly_due(datetime(2026, 9, 8, 22, 0), day)
    assert due2 and day2 == "2026-09-08"


def test_merged_cells_canonicalizes_aliases() -> None:
    # use a real curated alias pair -- no hardcoded strings to drift
    canonical, aliases = next(iter(knowledge.CONCEPT_ALIASES.items()))
    alias = aliases[0]
    merged = weakness.merged_cells({canonical: [1, 2], alias: [0, 1]})
    assert merged[canonical] == [1, 3]
    assert alias not in merged


# ---------- shared environment ----------


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/rollup.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/rollup.db")
    yield client, conn, settings
    conn.close()


def _register(client: TestClient, email: str, *, role: str, class_level: int | None = None) -> int:
    body: dict = {"email": email, "password": PASSWORD, "role": role, "name": f"U {email}"}
    if role == "student":
        body["class_level"] = class_level or 6
        body["guardian_consent"] = True
    res = client.post("/auth/register", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["profile_id"])


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _seed_graded_answers(
    conn: sqlite3.Connection, student_id: int, cells: dict[str, tuple[int, int]]
) -> None:
    """One graded attempt whose answer log realises the given cells."""
    now = _now()
    total = sum(t for _, t in cells.values())
    correct = sum(c for c, _ in cells.values())
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
        " score_pct, quiz_json, created_at) VALUES (?, 'math', 6, 'graded', ?, ?, ?, '[]', ?)",
        (
            student_id,
            total,
            correct,
            round(100.0 * correct / total, 2),
            _ts(now - timedelta(hours=1)),
        ),
    )
    att = int(
        conn.execute(
            "SELECT id FROM quiz_attempts WHERE student_id=? ORDER BY id DESC", (student_id,)
        ).fetchone()[0]
    )
    seq = 0
    for chapter, (ok_count, asked) in cells.items():
        for i in range(asked):
            seq += 1
            conn.execute(
                "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
                " is_correct, chapter, book) VALUES (?, ?, 'q', 0, 0, ?, ?, 'b')",
                (att, seq, int(i < ok_count), chapter),
            )
    conn.commit()


def _seed_family(
    client: TestClient, conn: sqlite3.Connection, parent_email: str, student_id: int
) -> int:
    parent_id = _register(client, parent_email, role="parent")
    conn.execute(
        "INSERT INTO parent_student_links (parent_id, student_id, created_at) VALUES (?, ?, ?)",
        (parent_id, student_id, _ts(_now())),
    )
    conn.commit()
    return parent_id


# ---------- rollup rule (unit, via session) ----------


def test_rollup_rule_thresholds_and_order(env) -> None:
    client, conn, settings = env
    sid = _register(client, "rule@rollup.test", role="student")
    _seed_graded_answers(conn, sid, CELLS)
    session = make_session_factory(make_engine(settings))()
    try:
        weak = weakness.weak_concepts(session, sid)
    finally:
        session.close()
    assert [w.concept for w in weak] == EXPECTED
    assert weak[0].asked == 4 and weak[0].correct == 0 and weak[0].accuracy_pct == 0.0
    assert weak[1].accuracy_pct == 25.0
    assert knowledge.WEAK_THRESHOLD_PCT == 50.0 and knowledge.MIN_ATTEMPTS == 3


# ---------- the PASS-WHEN: same value, all three endpoints ----------


def test_same_value_from_all_three_surfaces(env) -> None:
    client, conn, settings = env
    sid = _register(client, "kid@rollup.test", role="student")
    _seed_graded_answers(conn, sid, CELLS)
    student_h = _login(client, "kid@rollup.test")
    _register(client, "teach@rollup.test", role="teacher")
    teacher_h = _login(client, "teach@rollup.test")
    _seed_family(client, conn, "par@rollup.test", sid)
    parent_h = _login(client, "par@rollup.test")

    # 1. Home recommendation
    home = client.get("/dashboard/summary", headers=student_h)
    assert home.status_code == 200
    home_json = home.json()
    home_weak = home_json["progress"]["weak_chapters"]
    assert home_weak == EXPECTED
    rec = home_json["recommendation"]
    assert rec is not None and rec["type"] == "weak_quiz"
    assert rec["chapter"] == EXPECTED[0]  # weakest first

    # 2. Teacher at-risk surface
    matrix = client.get("/teacher/weak-matrix", params={"class_level": 6}, headers=teacher_h)
    assert matrix.status_code == 200
    row = next(s for s in matrix.json()["students"] if s["student_id"] == sid)
    assert row["weak_concepts"] == EXPECTED

    # 3. Parent surface: dashboard endpoint AND the weekly digest email
    progress = client.get(f"/parents/me/children/{sid}/progress", headers=parent_h)
    assert progress.status_code == 200
    parent_weak = progress.json()["weak_chapters"]
    assert parent_weak == EXPECTED

    sent: list[str] = []

    def fake_sender(_settings: Settings, *, to: str, subject: str, body: str) -> bool:
        sent.append(body)
        return True

    session = make_session_factory(make_engine(settings))()
    try:
        stats = run_weekly_digest(settings, session, sender=fake_sender, now=_now())
    finally:
        session.close()
    assert stats.delivered == 1
    assert "Chapters to practise: alpha, beta" in sent[0]

    # THE consistency assertion: one value, every surface.
    assert home_weak == row["weak_concepts"] == parent_weak == EXPECTED


# ---------- nightly reconciliation ----------


def test_refresh_mastery_reconciles_and_is_idempotent(env) -> None:
    client, conn, settings = env
    sid = _register(client, "sync@rollup.test", role="student")
    _seed_graded_answers(conn, sid, CELLS)
    engine = make_engine(settings)
    session = make_session_factory(engine)()
    try:
        students, rows = weakness.refresh_mastery(session)
        assert (students, rows) == (1, 4)
        mastery = knowledge.mastery_map(session, sid)
        assert mastery == {
            "alpha": (0, 4),
            "beta": (1, 4),
            "gamma": (2, 4),
            "delta": (0, 2),
        }
        # idempotent: second pass changes nothing
        students2, rows2 = weakness.refresh_mastery(session)
        assert (students2, rows2) == (1, 4)
        assert knowledge.mastery_map(session, sid) == mastery
    finally:
        session.close()
