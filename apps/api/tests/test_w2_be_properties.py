"""W2/TEST-09 (F-155): property-based tests for the input-facing helpers.

The example-based suites pin the cases someone thought of; these tests state
the invariants the callers rely on and let hypothesis search for a
counter-example: normalisation is stable and total, the stemmer never invents
text, the k-anonymity floor cannot be argued below its minimum, CSV import
never answers 5xx for arbitrary text, and quiz scoring stays in [0, 100] and
matches the answers it was given.

``hypothesis`` is in the local dev environment but not yet in
``apps/api/constraints.txt``; the module therefore skips (loudly, with the
reason) in an environment without it. Handoff: add ``hypothesis>=6`` to the
dev extra and regenerate the lock, then delete the importorskip.
"""

import math

import pytest
from fastapi.testclient import TestClient

hypothesis = pytest.importorskip(
    "hypothesis",
    reason="property tests need hypothesis; handoff: add it to the dev extra and constraints.txt",
)
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.main import create_app  # noqa: E402
from bangla_gpt_api.nctb.normalize import (  # noqa: E402
    bangla_char_ratio,
    looks_like_garbage,
    normalize_bangla,
)
from bangla_gpt_api.retrieval.hybrid import _MIN_STEM_LEN, light_stem  # noqa: E402
from bangla_gpt_api.services.govt_report import (  # noqa: E402
    DEFAULT_MIN_CELL,
    MIN_CELL_FLOOR,
    effective_min_cell,
)
from conftest import engine_url  # noqa: E402

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

#: Arbitrary Unicode including the scripts this product handles, control-ish
#: characters and the replacement char the corruption detector looks for.
TEXT = st.text(max_size=200)
BANGLA = st.text(alphabet=st.characters(min_codepoint=0x0980, max_codepoint=0x09FF), max_size=40)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(TEXT)
def test_normalize_bangla_is_idempotent_and_total(text: str) -> None:
    once = normalize_bangla(text)
    assert isinstance(once, str)
    # Stability is the invariant callers depend on: indexing a normalised
    # chunk and a freshly normalised query must agree. (Length is not one:
    # NFKC legitimately expands e.g. the single character U+00BC to three.)
    assert normalize_bangla(once) == once
    assert once == once.strip()
    assert "  " not in once
    assert "\n\n" not in once


@settings(max_examples=50, deadline=None)
@given(TEXT)
def test_bangla_char_ratio_and_garbage_detector_stay_total(text: str) -> None:
    ratio = bangla_char_ratio(text)
    assert 0.0 <= ratio <= 1.0
    assert isinstance(looks_like_garbage(text), bool)


@settings(max_examples=100, deadline=None)
@given(BANGLA)
def test_light_stem_only_strips_a_suffix(term: str) -> None:
    stemmed = light_stem(term)
    assert isinstance(stemmed, str)
    if stemmed != term:
        assert term.startswith(stemmed), (term, stemmed)
        assert len(stemmed) >= _MIN_STEM_LEN
        # Deterministic: the same term always stems the same way.
        assert light_stem(term) == stemmed


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=-10_000, max_value=10_000) | st.none())
def test_k_anonymity_floor_cannot_be_argued_below_the_minimum(requested: int | None) -> None:
    effective = effective_min_cell(requested)
    assert effective >= MIN_CELL_FLOOR
    if requested is None:
        assert effective == DEFAULT_MIN_CELL
    else:
        assert effective == max(MIN_CELL_FLOOR, requested)
        if requested >= MIN_CELL_FLOOR:
            assert effective == requested


@pytest.fixture(scope="module")
def prepared(tmp_path_factory) -> dict:
    """One app, one teacher and one pupil, registered once.

    The property examples below drive the import and the quiz, so the setup
    must not re-register per example: the register rate limit (10/min) turns
    additional examples into 429s, which would test the limiter instead.
    """
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path_factory.mktemp("props"), "props"),
        jwt_secret=SECRET,
    )
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/auth/register",
                json={
                    "email": "props@example.com",
                    "password": PASSWORD,
                    "name": "Tutor",
                    "role": "teacher",
                },
            ).status_code
            == 201
        )
        teacher = {
            "Authorization": "Bearer "
            + client.post(
                "/auth/login", json={"email": "props@example.com", "password": PASSWORD}
            ).json()["access_token"]
        }
        room = client.post(
            "/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=teacher
        ).json()
        assert (
            client.post(
                "/auth/register",
                json={
                    "email": "proppupil@example.com",
                    "password": PASSWORD,
                    "name": "শিক্ষার্থী",
                    "role": "student",
                    "guardian_consent": True,
                    "class_level": 6,
                },
            ).status_code
            == 201
        )
        pupil = {
            "Authorization": "Bearer "
            + client.post(
                "/auth/login", json={"email": "proppupil@example.com", "password": PASSWORD}
            ).json()["access_token"]
        }
        student_id = client.get("/users/me", headers=pupil).json()["profile_id"]
        yield {
            "client": client,
            "teacher": teacher,
            "pupil": pupil,
            "room_id": room["id"],
            "student_id": student_id,
        }


@settings(
    max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(csv_text=st.text(max_size=300))
def test_csv_import_never_answers_5xx_for_arbitrary_text(prepared: dict, csv_text: str) -> None:
    """Any pasted spreadsheet text is a 201 (possibly with invalid rows) or a
    coded 4xx; a 500 would mean the parser crashed on real-world input."""
    res = prepared["client"].post(
        f"/teacher/classrooms/{prepared['room_id']}/import",
        json={"csv_text": csv_text},
        headers=prepared["teacher"],
    )
    assert res.status_code < 500, (res.status_code, res.text[:200])
    if res.status_code == 201:
        # Every reported row is accounted for: created or explicitly invalid.
        rows = res.json()["rows"]
        assert all(row["status"] in ("created", "existing", "invalid") for row in rows)


@settings(
    max_examples=8, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(n=st.integers(min_value=1, max_value=10), mask=st.integers(min_value=0, max_value=1023))
def test_quiz_score_matches_the_answers_submitted(prepared: dict, n: int, mask: int) -> None:
    """score_pct is exactly round(100 * correct / total, 2) and always in
    [0, 100], with the review list agreeing with the stored score."""
    client, headers = prepared["client"], prepared["pupil"]
    quiz = client.post(
        "/quizzes",
        json={
            "student_id": prepared["student_id"],
            "class_level": 6,
            "subject": "science",
            "num_questions": n,
        },
        headers=headers,
    ).json()
    total = len(quiz["questions"])
    assert total == n
    answers = [((mask >> (i % 10)) & 1) for i in range(total)]
    res = client.post(
        f"/quizzes/{quiz['attempt_id']}/submit", json={"answers": answers}, headers=headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    correct = sum(1 for item in body["review"] if item["is_correct"])
    assert body["correct"] == correct
    assert body["total"] == total
    expected = round(100.0 * correct / total, 2)
    assert math.isclose(body["score_pct"], expected, abs_tol=0.01), (body["score_pct"], expected)
    assert 0.0 <= body["score_pct"] <= 100.0
