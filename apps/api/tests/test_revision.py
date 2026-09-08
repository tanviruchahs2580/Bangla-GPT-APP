"""S1.10 — SM-2-lite revision queue: interval math + due-count endpoint flow."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.revision import MIN_EASE, next_schedule


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/revision.db",
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


# ------------------------------------------------------------- unit: interval math


def test_success_progression_one_three_seven() -> None:
    reps, interval, ease = next_schedule(0, 0, 2.5, quality=5)
    assert (reps, interval) == (1, 1)
    assert ease == pytest.approx(2.6)

    reps, interval, ease = next_schedule(reps, interval, ease, quality=5)
    assert (reps, interval) == (2, 3)

    reps, interval, ease = next_schedule(reps, interval, ease, quality=5)
    assert (reps, interval) == (3, 7)

    # Beyond three recalls the interval grows by interval * ease.
    reps, interval, ease = next_schedule(reps, interval, ease, quality=5)
    assert reps == 4
    assert interval == round(7 * ease)
    assert interval > 7


def test_failure_resets_reps_and_interval() -> None:
    reps, interval, ease = next_schedule(3, 7, 2.5, quality=1)
    assert (reps, interval) == (0, 0)  # due again today
    assert ease == pytest.approx(2.3)


def test_ease_never_drops_below_floor() -> None:
    _, _, ease = next_schedule(0, 0, MIN_EASE + 0.1, quality=0)
    assert ease == MIN_EASE


def test_quality_is_clamped_to_range() -> None:
    reps, interval, _ = next_schedule(0, 0, 2.5, quality=99)
    assert (reps, interval) == (1, 1)


# ------------------------------------------------------------------ endpoint flow


def _run_quiz(client: TestClient, auth: dict, n: int = 3) -> dict:
    headers = {"Authorization": str(auth["Authorization"])}
    started = client.post(
        "/quizzes",
        json={"student_id": auth["profile_id"], "num_questions": n},
        headers=headers,
    ).json()
    return client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * n},
        headers=headers,
    ).json()


def test_quiz_seeds_due_count_and_review_reschedules(client: TestClient) -> None:
    auth = _register_login(client, "rev1@example.com")
    headers = {"Authorization": str(auth["Authorization"])}

    empty = client.get("/revision/due", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["due_count"] == 0

    result = _run_quiz(client, auth, n=3)
    wrong = [r for r in result["review"] if not r["is_correct"]]
    assert wrong, "test assumes at least one wrong answer with constant picks"

    due = client.get("/revision/due", headers=headers).json()
    # Only wrong items are due today; correct ones sit at +1 day.
    assert due["due_count"] == len(wrong)
    assert len(due["items"]) == len(wrong)
    assert all(it["due_date"] <= due["today"] for it in due["items"])

    item = due["items"][0]
    reviewed = client.post(
        f"/revision/{item['id']}/review",
        headers=headers,
        json={"chosen": item["correct_index"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    out = reviewed.json()
    assert out["reps"] == 1
    assert out["interval_days"] == 1
    assert out["due_date"] == (date.fromisoformat(due["today"]) + timedelta(days=1)).isoformat()

    # Now it leaves the due list.
    assert client.get("/revision/due", headers=headers).json()["due_count"] == len(wrong) - 1

    # Answering wrong again brings it back due today with reps reset.
    back = client.post(
        f"/revision/{item['id']}/review", headers=headers, json={"chosen": -1}
    ).json()
    assert back["reps"] == 0
    assert back["interval_days"] == 0
    assert back["due_date"] <= due["today"]
    assert client.get("/revision/due", headers=headers).json()["due_count"] == len(wrong)


def test_review_is_private_and_validated(client: TestClient) -> None:
    auth = _register_login(client, "rev2@example.com")
    headers = {"Authorization": str(auth["Authorization"])}
    _run_quiz(client, auth, n=3)
    due = client.get("/revision/due", headers=headers).json()
    if not due["items"]:  # all-correct quiz corner: force one wrong via a fresh student
        pytest.fail("constant answers expected to produce a wrong item")
    item_id = due["items"][0]["id"]

    other = _register_login(client, "rev3@example.com")
    other_headers = {"Authorization": str(other["Authorization"])}
    assert client.get("/revision/due", headers=other_headers).json()["due_count"] == 0
    assert (
        client.post(
            f"/revision/{item_id}/review", headers=other_headers, json={"chosen": 0}
        ).status_code
        == 404
    )
    assert (
        client.post(f"/revision/{item_id}/review", headers=headers, json={"chosen": -2}).status_code
        == 422
    )
