"""S1.9 — daily activity: Dhaka day boundary, streak math, heatmap, endpoint."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.activity import dhaka_date, heatmap_days, streak_days


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/activity.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def _register_login(client: TestClient, email: str) -> dict[str, object]:
    reg = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "supersecret1",
            "name": "Test Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post("/auth/login", json={"email": email, "password": "supersecret1"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "profile_id": reg.json()["profile_id"]}


# ---------------------------------------------------------------- unit: timezone


def test_dhaka_date_rolls_over_at_utc_1800() -> None:
    # 2026-01-01 18:30Z is 2026-01-02 00:30 in Asia/Dhaka (UTC+6, no DST).
    assert dhaka_date(datetime(2026, 1, 1, 18, 30, tzinfo=UTC)) == "2026-01-02"
    assert dhaka_date(datetime(2026, 1, 1, 17, 59, 59, tzinfo=UTC)) == "2026-01-01"
    # naive datetimes are assumed UTC
    assert dhaka_date(datetime(2026, 1, 1, 18, 30)) == "2026-01-02"


# ------------------------------------------------------------------- unit: streak


def test_streak_counts_consecutive_days_including_today() -> None:
    days = {"2026-01-01", "2026-01-02", "2026-01-03"}
    assert streak_days(days, "2026-01-03") == 3


def test_streak_not_broken_before_today_activity() -> None:
    # No activity yet today: yesterday active still keeps the streak alive.
    days = {"2026-01-01", "2026-01-02"}
    assert streak_days(days, "2026-01-03") == 2


def test_streak_breaks_after_a_full_missed_day() -> None:
    days = {"2026-01-01", "2026-01-02"}
    assert streak_days(days, "2026-01-04") == 0


def test_streak_gap_inside_chain() -> None:
    days = {"2025-12-30", "2026-01-01", "2026-01-02"}
    assert streak_days(days, "2026-01-02") == 2


def test_streak_empty() -> None:
    assert streak_days(set(), "2026-01-02") == 0


# ------------------------------------------------------------------ unit: heatmap


class _Row:
    def __init__(self, date: str, questions: int = 0, quizzes: int = 0, minutes: int = 0):
        self.date = date
        self.questions = questions
        self.quizzes = quizzes
        self.minutes = minutes


def test_heatmap_zero_fills_oldest_first() -> None:
    rows = [_Row("2026-01-02", questions=3, minutes=3)]
    out = heatmap_days(rows, "2026-01-03", 4)
    assert len(out) == 4
    assert out[0] == {"questions": 0, "quizzes": 0, "minutes": 0}
    assert out[2] == {"questions": 3, "quizzes": 0, "minutes": 3}
    assert out[3]["questions"] == 0


# -------------------------------------------------------------------- endpoint


def test_activity_endpoint_records_chat_and_quiz(client: TestClient) -> None:
    auth = _register_login(client, "act1@example.com")
    headers = {"Authorization": str(auth["Authorization"])}
    student_id = int(auth["profile_id"])

    empty = client.get(f"/students/{student_id}/activity", headers=headers)
    assert empty.status_code == 200
    body = empty.json()
    assert body["streak"] == 0
    assert len(body["days"]) == 91
    assert body["days"][-1]["questions"] == 0

    # A chat turn bumps today's question counter.
    cid = client.post("/tutor/conversations", headers=headers, json={}).json()["id"]
    msg = client.post(
        f"/tutor/conversations/{cid}/messages",
        headers=headers,
        json={"message": "What is a cell? Explain briefly."},
    )
    assert msg.status_code == 200, msg.text

    # A graded quiz bumps today's quiz counter.
    started = client.post(
        "/quizzes",
        json={"student_id": student_id, "num_questions": 2},
        headers=headers,
    ).json()
    sub = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=headers,
    )
    assert sub.status_code == 200, sub.text

    after = client.get(f"/students/{student_id}/activity", headers=headers).json()
    today_cell = after["days"][-1]
    assert today_cell["date"] == after["today"]
    assert today_cell["questions"] == 1
    assert today_cell["quizzes"] == 1
    assert today_cell["minutes"] == 2
    assert after["streak"] == 1


def test_activity_window_and_authz(client: TestClient) -> None:
    auth = _register_login(client, "act2@example.com")
    headers = {"Authorization": str(auth["Authorization"])}
    student_id = int(auth["profile_id"])

    assert (
        len(client.get(f"/students/{student_id}/activity?days=7", headers=headers).json()["days"])
        == 7
    )
    # Out-of-range window rejected.
    assert client.get(f"/students/{student_id}/activity?days=3", headers=headers).status_code == 422

    # A second student cannot read the first one's activity.
    other = _register_login(client, "act3@example.com")
    other_headers = {"Authorization": str(other["Authorization"])}
    assert client.get(f"/students/{student_id}/activity", headers=other_headers).status_code == 403
