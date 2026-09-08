"""GATE G3 code-local: seed 1 school + 2 classes + 80 students; verify school admin."""

import sqlite3
from datetime import UTC, datetime, timedelta

import httpx

from bangla_gpt_api.config import Settings

PW = "G3Live2026x"
BASE = "http://127.0.0.1:8000"


def db_write(sql, params=(), fetch=False):
    conn = sqlite3.connect("dev.db", timeout=60)
    cur = conn.execute(sql, params)
    conn.commit()
    rows = cur.fetchall() if fetch else []
    conn.close()
    return rows


def cleanup():
    school = db_write("SELECT id FROM schools WHERE name='G3 Model School'", fetch=True)
    for (scid,) in school:
        for (rid,) in db_write("SELECT id FROM classrooms WHERE school_id=?", (scid,), fetch=True):
            db_write("DELETE FROM class_students WHERE classroom_id=?", (rid,))
            db_write("DELETE FROM class_teachers WHERE classroom_id=?", (rid,))
        db_write("DELETE FROM classrooms WHERE school_id=?", (scid,))
        db_write("DELETE FROM school_invites WHERE school_id=?", (scid,))
        db_write("DELETE FROM schools WHERE id=?", (scid,))
    for (uid,) in db_write("SELECT id FROM users WHERE email LIKE '%@g3.test'", fetch=True):
        db_write("DELETE FROM teachers WHERE user_id=?", (uid,))
        db_write("DELETE FROM parents WHERE user_id=?", (uid,))
        for (sid,) in db_write("SELECT id FROM students WHERE user_id=?", (uid,), fetch=True):
            db_write(
                "DELETE FROM answer_log WHERE attempt_id IN"
                " (SELECT id FROM quiz_attempts WHERE student_id=?)",
                (sid,),
            )
            db_write(
                "DELETE FROM quiz_attempts WHERE student_id=?",
                (sid,),
            )
            db_write("DELETE FROM parent_student_links WHERE student_id=?", (sid,))
            db_write("DELETE FROM students WHERE id=?", (sid,))
        db_write("DELETE FROM users WHERE id=?", (uid,))


def login(c, email, pw):
    r = c.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def join(c, code, email):
    r = c.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": PW, "name": email.split("@")[0]},
    )
    assert r.status_code == 201, r.text


def main():
    settings = Settings()
    assert settings.admin_email and settings.admin_password
    cleanup()
    c = httpx.Client(base_url=BASE, timeout=60)
    root = login(c, settings.admin_email, settings.admin_password)
    school = c.post("/admin/schools", json={"name": "G3 Model School"}, headers=root).json()
    inv_head = c.post(
        f"/schools/{school['id']}/invites", json={"role": "school_admin"}, headers=root
    ).json()
    inv_teach = c.post(
        f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root
    ).json()
    join(c, inv_head["code"], "g3head@g3.test")
    join(c, inv_teach["code"], "g3teach@g3.test")
    teach = login(c, "g3teach@g3.test", PW)

    r1 = c.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "GEN"}, headers=teach
    ).json()
    r2 = c.post(
        "/teacher/classrooms", json={"class_level": 7, "section": "GREEN"}, headers=teach
    ).json()
    assert r1["section"] == "GEN" and r2["section"] == "GREEN"
    owned = db_write(
        "SELECT COUNT(*) FROM classrooms WHERE school_id=? AND id IN (?,?)",
        (school["id"], r1["id"], r2["id"]),
        fetch=True,
    )[0][0]
    assert owned == 2
    for room_id, lo, hi in ((r1["id"], 1, 40), (r2["id"], 41, 80)):
        csv_text = "\n".join(f"G3 S{i:02d},g3s{i:02d}@g3.test" for i in range(lo, hi + 1))
        res = c.post(
            f"/teacher/classrooms/{room_id}/import", json={"csv_text": csv_text}, headers=teach
        )
        assert res.status_code == 200 and res.json()["created"] == 40, res.text
    print("ok - school + 2 rooms + 80 students seeded")

    # graded attempt plans by roster slot (see module analysis for thresholds)
    now = datetime.now(UTC).replace(tzinfo=None)

    def sid(n: int) -> int:
        rows = db_write(
            "SELECT s.id FROM students s JOIN users u ON s.user_id=u.id WHERE u.email=?",
            (f"g3s{n:02d}@g3.test",),
            fetch=True,
        )
        return int(rows[0][0])

    def add_attempt(n: int, days_ago: int, pct: float, level: int) -> None:
        created = str(now - timedelta(days=days_ago))
        db_write(
            "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
            " correct, score_pct, quiz_json, created_at) VALUES (?, 'science', ?, 'graded', 10,"
            " ?, ?, '[]', ?)",
            (sid(n), level, int(pct / 10), pct, created),
        )

    for n in range(1, 13):  # low avg -> at-risk (35 < 40)
        for d, p in ((3, 30.0), (2, 45.0), (1, 30.0)):
            add_attempt(n, d, p, 6)
    for n in range(13, 17):  # down trend (80,80 -> 40,40) -> at-risk
        for d, p in ((4, 80.0), (3, 80.0), (2, 40.0), (1, 40.0)):
            add_attempt(n, d, p, 6)
    for n in range(17, 47):  # strong (avg 85 >= 70)
        for d, p in ((2, 80.0), (1, 90.0)):
            add_attempt(n, d, p, 6 if n <= 40 else 7)
    for n in range(47, 67):  # support band (avg 60)
        for d, p in ((2, 55.0), (1, 65.0)):
            add_attempt(n, d, p, 6 if n <= 40 else 7)
    # students 67-80 stay ungraded (no attempts)
    print("ok - attempts seeded")

    head = login(c, "g3head@g3.test", PW)
    ov = c.get("/school/overview", headers=head).json()
    print(
        "overview:",
        {
            k: ov[k]
            for k in (
                "school_id",
                "name",
                "students",
                "teachers",
                "classrooms",
                "sessions_7d",
                "strong",
                "support",
                "risk",
                "ungraded",
                "strong_pct",
                "risk_pct",
            )
        },
    )
    assert ov["name"] == "G3 Model School"
    assert ov["students"] == 80 and ov["classrooms"] == 2 and ov["teachers"] == 2
    assert ov["risk"] == 16 and ov["strong"] == 30 and ov["support"] == 20
    assert ov["ungraded"] == 14
    risk_names = [r["name"] for r in ov["at_risk"]]
    assert len(risk_names) == 16
    assert "G3 S01" in risk_names and "G3 S16" in risk_names
    assert ov["at_risk"][0]["avg_score_pct"] == 35.0  # weakest first
    down = [r for r in ov["at_risk"] if r["name"] == "G3 S13"][0]
    assert down["trend"] == "down" and down["attempts_graded"] == 4
    # school admin sees their own school only (no school_id param needed)
    assert ov["school_id"] == school["id"]
    # cross-school request stays forbidden for school_admin
    r = c.get(f"/school/overview?school_id={ov['school_id']}", headers=head)
    assert r.status_code == 200
    other = db_write("SELECT id FROM schools WHERE name<>'G3 Model School' LIMIT 1", fetch=True)
    if other:
        r = c.get(f"/school/overview?school_id={other[0][0]}", headers=head)
        assert r.status_code == 403
    c.close()
    print("G3 CODE-LOCAL PASSED (school admin sees correct health + 16 at-risk)")


main()
