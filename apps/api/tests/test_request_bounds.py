"""Request-contract regressions from the 2026-10-17 audit.

Each of these was a real, reachable defect, and each fix is one bound or one
branch, so the tests are deliberately narrow: they assert the property that was
violated, not the surrounding feature.

* `AssignmentIn.num_questions` allowed 25 while `QuizSubmitRequest.answers`
  allowed 20, so a teacher could create an assignment no student could submit --
  FastAPI rejected the body with 422 before the handler ran and the attempt
  stayed open forever. The two bounds now come from one constant.
* `FeedbackRequest.rating` used `ge=-1, le=1`, which also admits 0, while the
  column is documented "-1 or +1" and every consumer counts only those two.
* `subject` / `chapter` were unbounded on the ask, chat and quiz routes but are
  written to VARCHAR(60) / VARCHAR(200) columns and interpolated into the model
  prompt.
* `learning_prefs.subject_focus` could be set but never cleared: the route
  merges the dict, so omitting the key kept the old value and the screen
  reported a save that had not happened.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import (
    MAX_QUIZ_QUESTIONS,
    AskRequest,
    AssignmentIn,
    ChatSendRequest,
    FeedbackRequest,
    QuizStartRequest,
    QuizSubmitRequest,
)

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "bounds.db"


@pytest.fixture
def client(db_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {
        "email": email,
        "password": PASSWORD,
        "name": "Person",
        "role": role,
    }
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# --- the assignment ceiling and the submit ceiling must be the same number ---


def test_submit_ceiling_covers_every_question_an_assignment_can_generate() -> None:
    """The defect: 21..25 questions were generated but never submittable."""
    assignment = AssignmentIn(
        student_ids=[1],
        subject="science",
        chapter="কোষ",
        num_questions=MAX_QUIZ_QUESTIONS,
        due_at="2026-12-01T00:00:00Z",
    )
    assert assignment.num_questions == MAX_QUIZ_QUESTIONS

    # The largest answer list an assignment can require must validate.
    submitted = QuizSubmitRequest(answers=[0] * assignment.num_questions)
    assert len(submitted.answers) == MAX_QUIZ_QUESTIONS


def test_both_ceilings_are_the_same_constant_not_two_literals() -> None:
    """Ties the two schemas together so they cannot drift apart again.

    Asserted through behaviour rather than by reading the pydantic metadata:
    every question count AssignmentIn accepts must produce an answer list
    QuizSubmitRequest accepts.
    """
    for n in range(1, MAX_QUIZ_QUESTIONS + 1):
        assignment = AssignmentIn(
            student_ids=[1],
            subject="science",
            chapter="কোষ",
            num_questions=n,
            due_at="2026-12-01T00:00:00Z",
        )
        assert len(QuizSubmitRequest(answers=[0] * assignment.num_questions).answers) == n

    # and the generator cannot exceed what the submit route accepts.
    with pytest.raises(ValidationError):
        AssignmentIn(
            student_ids=[1],
            subject="science",
            chapter="কোষ",
            num_questions=MAX_QUIZ_QUESTIONS + 1,
            due_at="2026-12-01T00:00:00Z",
        )


def test_submit_still_rejects_more_than_it_can_grade() -> None:
    with pytest.raises(ValidationError):
        QuizSubmitRequest(answers=[0] * (MAX_QUIZ_QUESTIONS + 1))


# --- feedback rating: a two-valued verdict plus an explicit "no verdict" ----


@pytest.mark.parametrize("rating", [-1, 1])
def test_feedback_rating_accepts_a_real_verdict(rating: int) -> None:
    assert FeedbackRequest(rating=rating).rating == rating


def test_feedback_rating_keeps_zero_as_no_verdict() -> None:
    """0 stays valid on purpose.

    It was proposed as a data-quality defect (rows no aggregate counts). It is
    not: `rating` is a required field, so 0 is the only way to send a comment
    with no thumbs answer, and the aggregates counting only -1/+1 is then
    correct. `test_feedback_without_target_is_400_not_422` depends on this too.
    """
    assert FeedbackRequest(rating=0).rating == 0


def test_feedback_rating_still_rejects_out_of_range() -> None:
    for rating in (2, -2, 99):
        with pytest.raises(ValidationError):
            FeedbackRequest(rating=rating)


# --- subject / chapter are bounded by the columns they land in -------------


@pytest.mark.parametrize(
    "model, extra",
    [
        (AskRequest, {"question": "কোষ কী?", "class_level": 6}),
        (ChatSendRequest, {"message": "কোষ কী?"}),
        (QuizStartRequest, {"student_id": 1}),
    ],
)
def test_subject_and_chapter_match_their_column_widths(model, extra: dict) -> None:
    # 60 / 200 are the widths of quiz_attempts.subject and .chapter; an over-long
    # value was a 500 on PostgreSQL, not a 422.
    assert model(**extra, subject="s" * 60).subject
    assert model(**extra, chapter="c" * 200).chapter
    with pytest.raises(ValidationError):
        model(**extra, subject="s" * 61)
    with pytest.raises(ValidationError):
        model(**extra, chapter="c" * 201)


def test_over_long_subject_is_rejected_by_the_api_not_stored(client: TestClient) -> None:
    _register(client, "kid@example.com")
    kid = _login(client, "kid@example.com")
    res = client.post(
        "/quizzes",
        json={"student_id": 1, "subject": "x" * 500, "num_questions": 3},
        headers=kid,
    )
    assert res.status_code == 422, res.text
    assert res.status_code != 500


# --- subject_focus can be cleared -----------------------------------------


def test_subject_focus_can_be_set_and_cleared(client: TestClient) -> None:
    """Setting worked; clearing silently kept the old value and the UI said it
    had saved, because the route merges the dict and the key was omitted."""
    _register(client, "kid2@example.com")
    kid = _login(client, "kid2@example.com")

    res = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"subject_focus": "জ্যামিতি"}},
        headers=kid,
    )
    assert res.status_code == 200, res.text
    assert res.json()["learning_prefs"]["subject_focus"] == "জ্যামিতি"

    # null clears the key rather than being ignored or rejected.
    res = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"subject_focus": None}},
        headers=kid,
    )
    assert res.status_code == 200, res.text
    assert "subject_focus" not in res.json()["learning_prefs"]

    # and it stays cleared on a re-read (the value the UI refetches).
    assert (
        "subject_focus"
        not in client.get("/students/me/prefs", headers=kid).json()["learning_prefs"]
    )


def test_an_empty_subject_focus_string_is_still_rejected(client: TestClient) -> None:
    """Clearing is an explicit null; "" stays invalid so the whitelist contract
    does not quietly gain a second meaning."""
    _register(client, "kid3@example.com")
    kid = _login(client, "kid3@example.com")
    res = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"subject_focus": "   "}},
        headers=kid,
    )
    assert res.status_code == 422, res.text
