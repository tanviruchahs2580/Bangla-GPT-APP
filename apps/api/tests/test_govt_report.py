"""S6.5: anonymized aggregate reporting -- k-anonymity suppression,
formula-safe CSV, and the automated zero-PII gate.

The PASS-WHEN tests seed canary PII (distinctive emails/names) into the
database and assert none of it reaches any export format.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import Base, Conversation, QuizAttempt, Student, User
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.govt_report import (
    aggregate,
    pii_violations,
    to_csv,
    to_json_dict,
    to_pdf,
)

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/govt.db")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _student(session: Session, idx: int, *, class_level: int = 6) -> Student:
    user = User(email=f"s{idx}@x.example", password_hash="x", role="student")
    session.add(user)
    session.flush()
    student = Student(user_id=user.id, name=f"Student {idx}", class_level=class_level)
    session.add(student)
    session.flush()
    return student


def _attempt(
    session: Session,
    student: Student,
    *,
    subject: str | None = "math",
    class_level: int = 6,
    score_pct: float = 80.0,
    status: str = "graded",
) -> QuizAttempt:
    attempt = QuizAttempt(
        student_id=student.id,
        subject=subject,
        class_level=class_level,
        status=status,
        total=5,
        correct=4,
        score_pct=score_pct,
        quiz_json=[],
    )
    session.add(attempt)
    session.flush()
    return attempt


def test_cells_below_k_anonymity_are_suppressed(session: Session) -> None:
    for i in range(4):  # 4 students < default min_cell=5
        _attempt(session, _student(session, i))
    export = aggregate(session)
    assert export.rows == []
    assert export.meta.suppressed_cells == 1
    assert export.meta.total_students_included == 0


def test_cell_at_threshold_included_with_counts(session: Session) -> None:
    students = [_student(session, i) for i in range(5)]
    for s in students:
        _attempt(session, s, score_pct=70.0)
    _attempt(session, students[0], score_pct=90.0)  # second attempt, same student
    session.add(Conversation(student_id=students[1].id, title="t"))
    session.add(Conversation(student_id=students[3].id, title="t"))
    session.commit()

    export = aggregate(session)
    assert export.meta.suppressed_cells == 0
    assert len(export.rows) == 1
    row = export.rows[0]
    assert row == {
        "class_level": 6,
        "subject": "math",
        "students": 5,  # distinct students, not attempts
        "quiz_attempts": 6,
        "avg_score_pct": 73.33,
        "active_tutor_students": 2,
    }
    assert export.meta.total_students_included == 5


def test_since_days_window_excludes_old_attempts(session: Session) -> None:
    from datetime import UTC, datetime, timedelta

    s = _student(session, 1)
    old = _attempt(session, s)
    old.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=100)
    _attempt(session, s)
    session.commit()

    assert aggregate(session, min_cell=1).rows[0]["quiz_attempts"] == 2
    assert aggregate(session, since_days=30, min_cell=1).rows[0]["quiz_attempts"] == 1


def test_csv_escapes_formula_injection(session: Session) -> None:
    import csv as csv_mod
    import io

    _attempt(session, _student(session, 1))
    export = aggregate(session, district="=HYPERLINK(\"http://evil\")", min_cell=1)
    rows = list(csv_mod.reader(io.StringIO(to_csv(export))))
    assert rows[0][0] == "district"
    assert rows[1][0].startswith("'=")  # leading apostrophe neutralizes the formula


def test_pii_scanner_flags_emails_and_phones_but_not_report_numbers() -> None:
    assert pii_violations("contact rashida@example.net now")
    assert pii_violations("phone: 01712345678")
    clean_session_text = (
        "district,class_level,subject,students,quiz_attempts,avg_score_pct\n"
        "Dhaka,6,math,12,30,73.33,4\n"
    )
    assert pii_violations(clean_session_text) == []


def test_export_serializers_carry_no_identity_fields(session: Session) -> None:
    for i in range(6):
        s = _student(session, i)
        s.name = "Canary Faceperson"
        _attempt(session, s)
    session.commit()
    export = aggregate(session, district="Dhaka")
    json_text = str(to_json_dict(export))
    csv_text = to_csv(export)
    assert "Canary Faceperson" not in json_text and "Canary Faceperson" not in csv_text
    assert "@" not in csv_text
    assert pii_violations(json_text) == [] and pii_violations(csv_text) == []
    assert to_pdf(export)[:4] == b"%PDF"


# -- endpoint level ---------------------------------------------------------

ADMIN = "root@example.com"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/govt_api.db",
        admin_email=ADMIN,
        admin_password=PASSWORD,
        force_admin_password_change=False,
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _register_student(client: TestClient, email: str, name: str) -> int:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": name,
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    return int(res.json()["profile_id"])


def _seed_cohort(client: TestClient) -> None:
    for i in range(6):
        email = f"canary-student-{i}x9@example.net"
        profile_id = _register_student(client, email, "Canary Faceperson")
        headers = _login(client, email)
        started = client.post(
            "/quizzes",
            json={"student_id": profile_id, "num_questions": 2},
            headers=headers,
        ).json()
        client.post(
            f"/quizzes/{started['attempt_id']}/submit",
            json={"answers": [0] * len(started["questions"])},
            headers=headers,
        )


def test_aggregate_report_requires_admin(client: TestClient) -> None:
    assert client.get("/admin/reports/aggregate").status_code == 401
    student_email = "plain-student@example.net"
    _register_student(client, student_email, "Plain Student")
    headers = _login(client, student_email)
    assert client.get("/admin/reports/aggregate", headers=headers).status_code == 403


def test_aggregate_export_formats_and_zero_pii(client: TestClient) -> None:
    _seed_cohort(client)
    admin = _login(client, ADMIN)

    js = client.get("/admin/reports/aggregate?district=Dhaka", headers=admin)
    assert js.status_code == 200
    body = js.json()
    assert body["meta"]["district_tag"] == "Dhaka"
    math_rows = [r for r in body["rows"] if r["students"] >= 5]
    assert math_rows, f"expected an anonymized cohort row: {body}"
    js_text = js.text
    for i in range(6):
        assert f"canary-student-{i}x9@example.net" not in js_text
    assert "Canary Faceperson" not in js_text
    assert "@" not in js_text

    csv_res = client.get("/admin/reports/aggregate?format=csv&district=Dhaka", headers=admin)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert "bangla-gpt-aggregate" in csv_res.headers["content-disposition"]
    for i in range(6):
        assert f"canary-student-{i}x9@example.net".encode() not in csv_res.content
    assert "@" not in csv_res.content.decode("utf-8-sig")

    pdf = client.get("/admin/reports/aggregate?format=pdf", headers=admin)
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"
    for i in range(6):
        assert f"canary-student-{i}x9@example.net".encode() not in pdf.content


def test_aggregate_rejects_bad_format(client: TestClient) -> None:
    admin = _login(client, ADMIN)
    assert client.get("/admin/reports/aggregate?format=xlsx", headers=admin).status_code == 422
