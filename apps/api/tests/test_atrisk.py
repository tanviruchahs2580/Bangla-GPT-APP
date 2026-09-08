"""S2.7: at-risk rules (unit) + weak matrix + support plan endpoints."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.atrisk import (
    avg_pct,
    build_plan,
    cell_accuracy,
    is_at_risk,
    score_trend,
)

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


# --- pure rule tests (PASS-WHEN: rule unit tests) -----------------------------


def test_avg_pct() -> None:
    assert avg_pct([]) is None
    assert avg_pct([20.0, 60.0]) == 40.0


def test_score_trend_halves() -> None:
    assert score_trend([10.0, 90.0]) == "flat"  # not enough attempts
    assert score_trend([90.0, 90.0, 10.0, 10.0]) == "down"
    assert score_trend([10.0, 10.0, 90.0, 90.0]) == "up"
    assert score_trend([50.0, 50.0, 50.0, 50.0]) == "flat"
    assert score_trend([90.0, 90.0, 85.0, 85.0]) == "flat"  # drop < 10pp


def test_at_risk_rule_is_avg_below_40_or_downward() -> None:
    assert is_at_risk(39.9, "flat") is True
    assert is_at_risk(40.0, "flat") is False  # strictly below 40%
    assert is_at_risk(90.0, "down") is True  # downward trend alone flags
    assert is_at_risk(None, "down") is True
    assert is_at_risk(None, "flat") is False  # ungraded students are not flagged
    assert is_at_risk(50.0, "up") is False


def test_cell_accuracy() -> None:
    assert cell_accuracy(0, 0) is None
    assert cell_accuracy(4, 1) == 25.0


def test_build_plan_three_weeks_in_order() -> None:
    plan = build_plan(
        [{"name": "a", "accuracy": 10.0}, {"name": "b", "accuracy": 20.0}],
    )
    weeks = plan["weeks"]
    assert [w["stage"] for w in weeks] == ["concept", "practice", "assessment"]
    assert [w["week"] for w in weeks] == [1, 2, 3]
    assert all(w["concepts"] == ["a", "b"] for w in weeks)
    assert plan["focus_concepts"] == ["a", "b"]
    with pytest.raises(ValueError):
        build_plan([])


def test_build_plan_caps_focus_to_three_concepts() -> None:
    weak = [{"name": f"c{i}", "accuracy": float(i)} for i in range(5)]
    assert build_plan(weak)["focus_concepts"] == ["c0", "c1", "c2"]


# --- endpoint tests ------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "atrisk.db"


@pytest.fixture
def client(db_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _teacher_headers(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _seed_classroom(client: TestClient, headers: dict, n_students: int, section: str = "A") -> int:
    rid = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": section}, headers=headers
    ).json()["id"]
    rows = "\n".join(f"Student {i},stu{i}@school.edu" for i in range(n_students))
    res = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": f"name,email\n{rows}"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return rid


def _student_id(db_path, email: str) -> int:
    conn = sqlite3.connect(db_path)
    sid = conn.execute(
        "SELECT s.id FROM students s JOIN users u ON s.user_id = u.id WHERE u.email = ?",
        (email,),
    ).fetchone()[0]
    conn.close()
    return sid


def _seed_attempt(db_path, student_id: int, results: list[tuple[str, bool]], ts: str) -> None:
    """Insert one graded attempt + answer_log rows (chapter, is_correct) each."""
    correct = sum(1 for _, ok in results if ok)
    total = len(results)
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
        " correct, score_pct, quiz_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (student_id, "science", 6, "graded", total, correct, 100.0 * correct / total, "[]", ts),
    )
    for seq, (chapter, ok) in enumerate(results):
        conn.execute(
            "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
            " is_correct, chapter, book) VALUES (?,?,?,?,?,?,?,?)",
            (cur.lastrowid, seq, "q?", 0, 0, int(ok), chapter, "bk"),
        )
    conn.commit()
    conn.close()


def _seed_reading(db_path, student_id: int, chapter: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO chapter_progress (student_id, subject, chapter, class_level, read_pct,"
        " completed, bookmarked, updated_at) VALUES (?,?,?,?,100,0,0,"
        " '2026-01-01 00:00:00')",
        (student_id, "science", chapter, 6),
    )
    conn.commit()
    conn.close()


def _seed_two_students(db_path, client: TestClient) -> tuple[int, int, int]:
    """stu0: mixed results (not at risk); stu1: downward trend (at risk)."""
    headers = _teacher_headers(client, "teach@example.com")
    rid = _seed_classroom(client, headers, 2)
    s0, s1 = _student_id(db_path, "stu0@school.edu"), _student_id(db_path, "stu1@school.edu")
    # stu0: alpha 100% then beta 0% -> avg 50, too few attempts for a trend
    _seed_attempt(db_path, s0, [("alpha", True)] * 4, "2026-01-01 10:00:00")
    _seed_attempt(db_path, s0, [("beta", False)] * 4, "2026-01-02 10:00:00")
    _seed_reading(db_path, s0, "alpha")
    # stu1: 100,100,0,0 -> downward trend -> at risk even with avg 50
    for i, ok in enumerate((True, True, False, False)):
        _seed_attempt(db_path, s1, [("alpha", ok), ("alpha", ok)], f"2026-01-0{i + 1} 12:00:00")
    return rid, s0, s1


def test_weak_matrix_accuracy_order_read_flag_and_risk(client: TestClient, db_path) -> None:
    _seed_two_students(db_path, client)
    headers = _teacher_headers(client, "teach@example.com")
    body = client.get("/teacher/weak-matrix", params={"class_level": 6}, headers=headers).json()
    assert body["class_level"] == 6
    # class accuracy: beta 0% (4 asked, 0 right) < alpha 66.7% (12 asked, 8 right)
    assert body["concepts"] == ["beta", "alpha"]
    by_id = {s["student_id"]: s for s in body["students"]}
    assert len(by_id) == 2

    s0 = next(s for s in body["students"] if s["avg_score_pct"] == 50.0 and not s["at_risk"])
    assert s0["trend"] == "flat"
    assert s0["cells"]["alpha"] == {
        "asked": 4,
        "correct": 4,
        "accuracy": 100.0,
        "read": True,  # chapter_progress signal from the tutor reader
    }
    assert s0["cells"]["beta"]["accuracy"] == 0.0 and s0["cells"]["beta"]["read"] is False

    s1 = next(s for s in body["students"] if s["at_risk"])
    assert s1["trend"] == "down" and s1["avg_score_pct"] == 50.0
    assert s1["attempts_graded"] == 4


def test_support_plan_created_from_weakest_concepts(client: TestClient, db_path) -> None:
    _seed_two_students(db_path, client)
    headers = _teacher_headers(client, "teach@example.com")
    matrix = client.get("/teacher/weak-matrix", params={"class_level": 6}, headers=headers).json()
    s0_id = next(s["student_id"] for s in matrix["students"] if not s["at_risk"])

    res = client.post("/teacher/support-plans", json={"student_id": s0_id}, headers=headers)
    assert res.status_code == 201, res.text
    row = res.json()
    # stu0's weakest concepts, ascending accuracy: beta (0%) then alpha (100%)
    assert row["focus_concepts"] == ["beta", "alpha"]
    assert [w["stage"] for w in row["plan"]["weeks"]] == ["concept", "practice", "assessment"]

    listing = client.get("/teacher/support-plans", headers=headers).json()
    assert [p["id"] for p in listing] == [row["id"]]
    assert client.get(
        "/teacher/support-plans", params={"student_id": s0_id}, headers=headers
    ).json()
    other = _teacher_headers(client, "other@example.com")
    assert client.get("/teacher/support-plans", headers=other).json() == []


def test_support_plan_errors(client: TestClient, db_path) -> None:
    _seed_two_students(db_path, client)
    headers = _teacher_headers(client, "teach@example.com")
    assert (
        client.post("/teacher/support-plans", json={"student_id": 999}, headers=headers).status_code
        == 404
    )
    # s0 has data; a fresh roster-only student without graded attempts -> 422
    headers2 = _teacher_headers(client, "teach2@example.com")
    rid = _seed_classroom(client, headers2, 1, section="B")  # stu0 dup-row -> still 200
    # stu2 not imported above; import one more student in room 2 for the no-data case
    res = client.post(
        f"/teacher/classrooms/{rid}/import",
        json={"csv_text": "name,email\nLate,stu9@school.edu"},
        headers=headers2,
    )
    assert res.status_code == 200
    sid = _student_id(db_path, "stu9@school.edu")
    assert (
        client.post("/teacher/support-plans", json={"student_id": sid}, headers=headers).status_code
        == 422
    )


def test_student_role_forbidden(client: TestClient, db_path) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "kid@example.com",
            "password": PASSWORD,
            "name": "Kid",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    res = client.post("/auth/login", json={"email": "kid@example.com", "password": PASSWORD})
    hdr = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert (
        client.get("/teacher/weak-matrix", params={"class_level": 6}, headers=hdr).status_code
        == 403
    )
    assert (
        client.post("/teacher/support-plans", json={"student_id": 1}, headers=hdr).status_code
        == 403
    )
