"""AUD-B-11 (B register): k-anonymity export -- threshold, suppression, linkage.

Verifies the enforcement the register asked to see, end to end and at the
service seam:

* the floor cannot be lowered by a requester (HTTP 422) and a direct service
  caller is clamped (`effective_min_cell`);
* cells below the threshold are dropped AND counted (`suppressed_cells`), and
  `active_tutor_students` is suppressed by its own cohort check;
* the serialized payload carries aggregate-only keys -- no identity fields;
* every successful export writes exactly one `govt_export` audit row.

The differencing/linkage review notes live in
`docs/security/aggregate-export-anonymity.md`; this file pins the mechanics
the notes rely on.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import Conversation, QuizAttempt, Student, User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.govt_report import MIN_CELL_FLOOR, effective_min_cell

SECRET = "test-secret-0123456789abcdef0123456789"
ADMIN_PASSWORD = "Adm1n-Str0ng-Passphrase!"


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/kanon.db",
        jwt_secret=SECRET,
        admin_email="root@example.test",
        admin_password=ADMIN_PASSWORD,
        force_admin_password_change=False,
    )


@pytest.fixture()
def client(tmp_path):
    app = create_app(_settings(tmp_path))
    client = TestClient(app)
    _seed(client.app.state.settings)
    login = client.post(
        "/auth/login", json={"email": "root@example.test", "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200, login.text
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    return client


def _seed(settings: Settings) -> None:
    """class 6/math: 6 students (2 tutor users); class 7/science: 5 students
    (5 tutor users). One 4-student cell sits below the threshold on purpose."""
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        counter = 0

        def student_row(class_level: int) -> Student:
            nonlocal counter
            counter += 1
            user = User(email=f"s{counter}@example.test", password_hash="x", role="student")
            db.add(user)
            db.flush()
            row = Student(user_id=user.id, name=f"Student {counter}", class_level=class_level)
            db.add(row)
            db.flush()
            return row

        def attempt(row: Student, class_level: int, subject: str) -> None:
            db.add(
                QuizAttempt(
                    student_id=row.id,
                    subject=subject,
                    class_level=class_level,
                    status="graded",
                    total=5,
                    correct=4,
                    score_pct=80.0,
                    quiz_json=[],
                )
            )

        for idx in range(6):
            row = student_row(6)
            attempt(row, 6, "math")
            if idx < 2:  # 2 tutor users < 5: this class's activity is suppressed
                db.add(Conversation(student_id=row.id, title="tutor"))
        for idx in range(6):
            row = student_row(7)
            if idx < 5:
                attempt(row, 7, "science")
            if idx < 5:  # 5 tutor users >= 5: the true count is shown
                db.add(Conversation(student_id=row.id, title="tutor"))
        # 4-student cell: below the default threshold of 5.
        for _ in range(4):
            row = student_row(8)
            attempt(row, 8, "english")
        db.commit()


def _export(client: TestClient, **params) -> dict:
    res = client.get("/admin/reports/aggregate", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_floor_cannot_be_lowered_by_the_requester(client: TestClient) -> None:
    refused = client.get("/admin/reports/aggregate", params={"min_cell": 2})
    assert refused.status_code == 422, refused.text
    # The service seam clamps even if a second caller reaches it directly.
    assert effective_min_cell(2) == MIN_CELL_FLOOR
    assert effective_min_cell(None) == MIN_CELL_FLOOR
    assert effective_min_cell(10) == 10


def test_small_cells_are_suppressed_and_counted(client: TestClient) -> None:
    payload = _export(client)
    meta = payload["meta"]
    assert meta["min_cell"] == MIN_CELL_FLOOR
    assert meta["suppressed_cells"] >= 1  # the 4-student english cell + tutor cell
    cells = {(row["class_level"], row["subject"]): row for row in payload["rows"]}
    # 6 >= 5: included; 5 >= 5: included; 4 < 5: gone entirely.
    assert (6, "math") in cells
    assert (7, "science") in cells
    assert all(row["students"] >= MIN_CELL_FLOOR for row in payload["rows"])
    assert (8, "english") not in cells


def test_tutor_activity_is_suppressed_on_its_own_cohort(client: TestClient) -> None:
    payload = _export(client)
    cells = {(row["class_level"], row["subject"]): row for row in payload["rows"]}
    # class 6 has only 2 tutor users (< 5): blank, not the raw count.
    assert cells[(6, "math")]["active_tutor_students"] == ""
    # class 7 has 5: the true count is shown.
    assert cells[(7, "science")]["active_tutor_students"] == 5


def test_rows_carry_aggregate_keys_only(client: TestClient) -> None:
    payload = _export(client)
    allowed = {
        "class_level",
        "subject",
        "students",
        "quiz_attempts",
        "avg_score_pct",
        "active_tutor_students",
    }
    for row in payload["rows"]:
        assert set(row) == allowed, row
    text = json.dumps(payload, ensure_ascii=False)
    assert "Student " not in text and "example.test" not in text and "@" not in text


def test_raising_the_threshold_suppresses_more(client: TestClient) -> None:
    strict = _export(client, min_cell=10)
    assert strict["meta"]["min_cell"] == 10
    assert strict["rows"] == []
    assert strict["meta"]["suppressed_cells"] >= 3


def test_every_successful_export_is_audited_once(client: TestClient) -> None:
    _export(client, district="Dhaka")
    audit = client.get("/admin/audit", params={"action": "govt_export"})
    assert audit.status_code == 200, audit.text
    rows = audit.json()["rows"]
    assert len(rows) == 1, rows
    detail = rows[0]["detail"]
    assert detail["district"] == "Dhaka"
    assert detail["min_cell"] == MIN_CELL_FLOOR
    # Counts only: no row-level payload, no per-student values.
    assert "rows" in detail and "students_included" in detail
    assert all(not isinstance(value, list) for value in detail.values())
