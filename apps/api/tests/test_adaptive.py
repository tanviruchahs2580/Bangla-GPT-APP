"""S4.5 Adaptive practice engine tests.

Spec PASS: adaptation unit tests (correct -> harder, wrong -> easier + re-teach).
Re-teach cards must be KG-driven (S4.4 gaps) and grounded in corpus text.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import PracticeItem, StudentAbility
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import ReviewItem
from bangla_gpt_api.services import adaptive, knowledge
from bangla_gpt_api.services.quiz import ClozeQuizGenerator

PASSWORD = "supersecret1"

FRACTION = "ভগ্নাংশ"
NATURAL = "স্বাভাবিক সংখ্যা"
ALGEBRA_ALIAS = "বীজগণিত"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/adaptive.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


# --- pure Elo math ---------------------------------------------------------------


def test_expected_score_and_target_math() -> None:
    assert adaptive.expected_score(1200.0, 1200.0) == pytest.approx(0.5)
    assert adaptive.expected_score(1200.0, 1400.0) < 0.5  # harder item, lower odds
    assert adaptive.expected_score(1400.0, 1200.0) > 0.5
    # spec: next Q = ability + 0.5 sigma
    assert adaptive.next_target(1200.0) == 1200.0 + 0.5 * adaptive.SIGMA


def test_correct_raises_harder_wrong_lowers_easier() -> None:
    """The spec PASS-WHEN, on a static difficulty ladder.

    10 correct answers at the ladder rung nearest ability + 0.5 sigma must
    move the NEXT selection strictly harder; 10 wrong ones strictly easier.
    """
    ladder = {
        "a": 1000.0,
        "b": 1100.0,
        "c": 1200.0,
        "d": 1300.0,
        "e": 1400.0,
    }

    def pick(ability: float) -> str:
        return adaptive.select_item_ids(
            [(k, "x") for k in ladder],
            elo_by_id=ladder,
            ability_by_chapter={"x": ability},
            num=1,
        )[0]

    start = pick(1200.0)
    assert start == "d"  # ability 1200 -> target 1300 -> rung d

    # 10 correct answers
    ability = 1200.0
    for _ in range(10):
        ability, _item = adaptive.update_pair(ability, ladder[start], True)
        assert ability > 1200.0
    up = pick(ability)
    assert ladder[up] > ladder[start]  # CORRECT -> HARDER

    # 10 wrong answers
    ability = 1200.0
    for _ in range(10):
        ability, _item = adaptive.update_pair(ability, ladder[start], False)
        assert ability < 1200.0
    down = pick(ability)
    assert ladder[down] < ladder[start]  # WRONG -> EASIER


def test_selection_is_deterministic_under_ties() -> None:
    items = [("z", "x"), ("a", "x"), ("m", "x")]
    elo = {"z": 1300.0, "a": 1300.0, "m": 1300.0}
    first = adaptive.select_item_ids(items, elo_by_id=elo, ability_by_chapter={}, num=2)
    second = adaptive.select_item_ids(items, elo_by_id=elo, ability_by_chapter={}, num=2)
    assert first == second == ["a", "m"]  # ties break on id, always


def test_build_excerpt_sentence_bounded() -> None:
    text = "প্রথম বাক্য। দ্বিতীয় বাক্য আরও একটু লম্বা। তৃতীয় বাক্য একদম শেষ পর্যন্ত যাবে না।"
    excerpt = adaptive.build_excerpt(text, limit=20)
    assert "\n" not in excerpt
    assert len(excerpt) <= 20
    full = adaptive.build_excerpt("এক। দুই।", limit=280)
    assert full == "এক। দুই।"


# --- DB layer ----------------------------------------------------------------------


def _review(chapter: str, n: int, correct_first: int = 0) -> list[ReviewItem]:
    return [
        ReviewItem(
            question_text=f"Q{i}",
            options=["a", "b", "c", "d"],
            chosen=0,
            correct_index=0 if i < correct_first else 1,
            is_correct=i < correct_first,
            chapter=chapter,
        )
        for i in range(n)
    ]


def test_pick_questions_orders_by_target_and_persists_items(session) -> None:
    corpus = load_sample_corpus()
    gen = ClozeQuizGenerator(corpus)
    pool = gen.generate(class_level=7, subject="mathematics", num=10, seed=7)
    assert len(pool) >= 4
    picked = adaptive.pick_questions(
        session, pool, student_id=1, subject="mathematics", class_level=7, num=3
    )
    assert len(picked) == 3
    assert len({q.id for q in picked}) == 3
    # unseen items are registered at the neutral rating, explicit defaults
    rows = list(session.query(PracticeItem))
    assert rows and all(row.elo == adaptive.DEFAULT_ELO and row.attempts == 0 for row in rows)


def test_apply_review_moves_ratings_in_opposite_directions(session) -> None:
    corpus = load_sample_corpus()
    gen = ClozeQuizGenerator(corpus)
    pool = gen.generate(class_level=7, subject="mathematics", num=6, seed=11)
    adaptive.pick_questions(
        session, pool, student_id=1, subject="mathematics", class_level=7, num=6
    )
    graded = [(pool[0].id, pool[0].chapter, True) for _ in range(3)] + [
        (pool[1].id, pool[1].chapter, False) for _ in range(3)
    ]
    adaptive.apply_review(session, student_id=1, class_level=7, graded=graded)

    abilities = {row.concept: row.ability for row in session.query(StudentAbility)}
    good = abilities[knowledge.canonical(pool[0].chapter)]
    bad = abilities[knowledge.canonical(pool[1].chapter)]
    assert good > adaptive.DEFAULT_ELO  # correct answers raise ability
    assert bad < adaptive.DEFAULT_ELO  # wrong answers lower it
    item_good = session.get(PracticeItem, pool[0].id)
    item_bad = session.get(PracticeItem, pool[1].id)
    assert item_good is not None and item_good.correct == 3
    assert item_bad is not None and item_bad.correct == 0


def test_apply_review_repeated_concept_in_one_review(tmp_path) -> None:
    """Regression: one review covering the same chapter twice must not crash.

    The app's session has autoflush=False, so a pending StudentAbility row is
    invisible to db.get; without the explicit fresh-row cache the second
    question of the same chapter inserts a duplicate PK (IntegrityError -> 500).
    """
    engine = create_engine(f"sqlite:///{tmp_path}/dup.db")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        corpus = load_sample_corpus()
        gen = ClozeQuizGenerator(corpus)
        pool = gen.generate(class_level=7, subject="mathematics", num=6, seed=11)
        adaptive.pick_questions(
            db, pool, student_id=42, subject="mathematics", class_level=7, num=6
        )
        # same chapter + item three times in ONE review, all correct
        graded = [(pool[0].id, pool[0].chapter, True)] * 3
        adaptive.apply_review(db, student_id=42, class_level=7, graded=graded)
        rows = db.query(StudentAbility).filter_by(student_id=42).all()
        assert len(rows) == 1  # one row, not three duplicates
        assert rows[0].attempts == 3
        assert rows[0].ability > adaptive.DEFAULT_ELO  # Elo kept compounding


def test_wrong_answer_gap_check_yields_grounded_reteach_card(session) -> None:
    corpus = load_sample_corpus()
    knowledge.ensure_concepts(session, corpus)
    # make the student weak in fractions: 1/5 correct over 3+ attempts
    knowledge.record_quiz_result(session, 9, _review(FRACTION, 5, correct_first=1), 7)

    cards = adaptive.wrong_answer_reteach_cards(session, corpus, 9, [FRACTION])
    assert cards, "weak ভগ্নাংশ must surface a re-teach card"
    card = cards[0]
    assert set(card) == {"concept", "prereq", "depth", "excerpt"}
    assert card["concept"] == FRACTION
    assert card["prereq"] == NATURAL  # the never-practiced prerequisite
    assert card["excerpt"], "card must carry grounded text"
    # grounded: the excerpt is a verbatim substring of the prereq chapter's
    # text. The engine picks the prereq chapter's first chunk by (class, id);
    # the test searches every chunk of that chapter so it can't drift from
    # that ordering.
    frag = " ".join(card["excerpt"][:40].split())
    norms = [" ".join(c.text.split()) for c in corpus if c.meta.chapter == NATURAL]
    assert norms and any(frag in n for n in norms)

    # alias-keyed concepts reach the same card (canonicalization)
    alias_cards = adaptive.wrong_answer_reteach_cards(session, corpus, 9, [ALGEBRA_ALIAS])
    assert alias_cards == []  # alias has no mastery yet -> no gap -> no card

    open_cards = adaptive.open_reteach_cards(session, corpus, 9)
    assert {(c["concept"], c["prereq"]) for c in open_cards} == {(FRACTION, NATURAL)}

    # correct answers on a chapter with no open gap -> no card
    assert adaptive.wrong_answer_reteach_cards(session, corpus, 9, ["সেট"]) == []


# --- API layer ----------------------------------------------------------------------


def _make_student(client: TestClient, email: str, class_level: int) -> tuple[int, dict]:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "নাম",
            "role": "student",
            "guardian_consent": True,
            "class_level": class_level,
        },
    )
    assert res.status_code == 201, res.text
    sid = res.json()["profile_id"]
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return sid, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _play(client: TestClient, sid: int, headers: dict, subject: str | None = None) -> dict:
    payload: dict = {"student_id": sid, "num_questions": 5}
    if subject:
        payload["subject"] = subject
    started = client.post("/quizzes", json=payload, headers=headers).json()
    res = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [1] * len(started["questions"])},
        headers=headers,
    )
    return res.json()


def test_quiz_api_carries_adaptive_fields(client: TestClient) -> None:
    sid, headers = _make_student(client, "ad1@example.com", 7)
    started = client.post("/quizzes", json={"student_id": sid, "num_questions": 4}, headers=headers)
    body = started.json()
    assert body["reteach"] == []  # brand-new student: no mastery -> no gaps
    result = _play(client, sid, headers)
    assert isinstance(result["reteach"], list)
    for card in result["reteach"]:  # one attempt CAN already cross min-attempts
        assert set(card) == {"concept", "prereq", "depth", "excerpt"}


def test_wrong_answers_produce_reteach_then_reach_next_quiz(client: TestClient) -> None:
    sid, headers = _make_student(client, "ad2@example.com", 7)
    last: dict = {}
    for _ in range(3):
        last = _play(client, sid, headers, subject="mathematics")
    # 15 graded wrong-leaning answers over class-7 math (fraction + percent
    # chapters, both with curated prerequisites): a card MUST surface.
    assert last["reteach"], "repeated wrong math answers must yield a re-teach card"
    card = last["reteach"][0]
    assert set(card) == {"concept", "prereq", "depth", "excerpt"}
    assert card["excerpt"] and len(card["excerpt"]) <= adaptive.RETEACH_EXCERPT_CHARS

    # and the gap keeps following the student: next quiz start carries it too
    started = client.post(
        "/quizzes", json={"student_id": sid, "num_questions": 3}, headers=headers
    ).json()
    assert started["reteach"], "open gaps must be served BEFORE the next question"
    # submit-time cards are filtered to the wrong chapters of THAT attempt;
    # start-time cards are every open gap -- so submit cards ⊆ start cards.
    start_pairs = {(c["concept"], c["prereq"]) for c in started["reteach"]}
    for card in last["reteach"]:
        assert (card["concept"], card["prereq"]) in start_pairs
