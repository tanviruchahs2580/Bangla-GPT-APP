"""S4.4 Knowledge Graph v1: concepts, curated prerequisite edges, per-concept
mastery, and the gap resolver that implements the spec PASS rule:

    weak "বীজগণিত" surfaces the missing "ভগ্নাংশ" prerequisite.

The canonical chapter-root spellings use the corpus's quirky NCTB-style
orthography (য় sequences, প্র, সংখ্যা) and MUST stay byte-identical; the
literal guard test below pins every Bengali constant against the live
loader corpus and the shipped edge data, so a re-typed literal that
drifts by even one codepoint fails loudly before behavior tests could
skip trivially.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import Concept
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import ReviewItem
from bangla_gpt_api.services.knowledge import (
    CONCEPT_ALIASES,
    PREREQUISITE_EDGES,
    build_concept_seeds,
    build_edge_pairs,
    canonical,
    edges_by_name,
    ensure_concepts,
    mastery_map,
    parse_concept_names,
    prereq_closure,
    record_quiz_result,
    resolve_gaps,
    student_gaps,
)

PASSWORD = "supersecret1"

# --- corpus-canonical literals (verified against loader + edge data below) --
FRACTION = "ভগ্নাংশ"
NATURAL = "স্বাভাবিক সংখ্যা"
ALGEBRA = "বীজগণিতীয় রাশি"
ALGEBRA_ALIAS = "বীজগণিত"  # the literal spelling used in the spec sentence
EXPONENT = "সূচক ও সূচকীয় রাশি"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/kg.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _register(
    client: TestClient, email: str, role: str = "student", class_level: int | None = 6
) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "নাম", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = class_level
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _make_student(client: TestClient, email: str, class_level: int = 6):
    profile = _register(client, email, class_level=class_level)
    return profile["profile_id"], _login(client, email)


def _run_quiz(client: TestClient, student_id: int, headers: dict, answers: int) -> None:
    started = client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 5}, headers=headers
    ).json()
    res = client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [answers] * len(started["questions"])},
        headers=headers,
    )
    assert res.status_code == 200


# --- literal integrity --------------------------------------------------------


def test_bengali_literals_match_corpus_and_edge_data() -> None:
    chapters = {chunk.meta.chapter for chunk in load_sample_corpus() if chunk.meta.chapter}
    assert {FRACTION, NATURAL, ALGEBRA, EXPONENT} <= chapters
    assert FRACTION in PREREQUISITE_EDGES
    assert NATURAL in PREREQUISITE_EDGES[FRACTION]
    assert FRACTION in PREREQUISITE_EDGES[ALGEBRA]
    assert ALGEBRA_ALIAS in CONCEPT_ALIASES[ALGEBRA]


# --- pure layer ---------------------------------------------------------------


def test_alias_canonicalization() -> None:
    assert canonical(ALGEBRA_ALIAS) == ALGEBRA
    assert canonical("সূচক") == EXPONENT
    assert canonical("unknown-name-x") == "unknown-name-x"


def test_spec_gap_weak_algebra_surfaces_fraction() -> None:
    """Spec PASS rule, literally: weak "বীজগণিত" surfaces "ভগ্নাংশ"."""
    gaps = resolve_gaps({ALGEBRA_ALIAS: (1, 5)}, PREREQUISITE_EDGES)
    assert gaps, "weak algebra must surface gaps"
    assert all(g.concept == ALGEBRA for g in gaps)  # alias normalized
    frac = next(g for g in gaps if g.prereq == FRACTION)
    assert frac.depth == 1
    assert frac.prereq_pct is None and frac.prereq_total == 0  # never practiced
    assert any(g.prereq == NATURAL and g.depth == 1 for g in gaps)


def test_resolve_gaps_rules() -> None:
    edges = {"C": ("B",), "B": ("A",), "A": ()}
    # Strong prerequisite suppresses the gap entirely.
    assert resolve_gaps({"B": (1, 4), "A": (4, 4)}, edges) == []
    # Too few graded answers -> not weak yet (no noise-driven remediation).
    assert resolve_gaps({"B": (1, 2)}, edges) == []
    # Missing transitive prerequisites surface nearest-first.
    gaps = resolve_gaps({"C": (0, 3)}, edges)
    assert [(g.prereq, g.depth) for g in gaps] == [("B", 1), ("A", 2)]
    # A weak (not merely missing) prerequisite surfaces with its own stats.
    gaps = resolve_gaps({"C": (0, 3), "B": (1, 4)}, edges)
    c_b = next(g for g in gaps if g.concept == "C" and g.prereq == "B")
    assert c_b.prereq_pct == 25.0 and c_b.prereq_total == 4


def test_prereq_closure_transitive_depth() -> None:
    edges = {"C": ("B",), "B": ("A",), "A": ()}
    assert prereq_closure("C", edges) == {"B": 1, "A": 2}
    assert prereq_closure("A", edges) == {}


def _chunk(idx: int, chapter: str, class_level: int, subject: str = "mathematics") -> Chunk:
    return Chunk(
        id=f"c{idx}",
        text="পাঠ্য প্ৰস্তাবনা",
        meta=CurriculumMeta(
            curriculum_year=2023,
            class_level=class_level,
            subject=subject,
            book="গণিত",
            source="test",
            chapter=chapter,
        ),
    )


def test_build_seeds_and_edges_pin_lowest_class_and_skip_unknown() -> None:
    chunks = [
        _chunk(1, FRACTION, 7),
        _chunk(2, NATURAL, 6),
        _chunk(3, ALGEBRA, 8),
        _chunk(4, FRACTION, 9),  # same chapter, higher class -> not the target
        _chunk(5, "Zeta unknown chapter", 9, "science"),
        _chunk(6, FRACTION, 7),  # duplicate -> deduped
    ]
    seeds = build_concept_seeds(chunks)
    # sorted by (class_level, subject, name); the class-7/class-9 fraction
    # chapters are distinct seeds, only same-key duplicates are deduped.
    assert [s.name for s in seeds] == [NATURAL, FRACTION, ALGEBRA, FRACTION, "Zeta unknown chapter"]
    assert ALGEBRA_ALIAS in seeds[2].aliases  # alias carried onto the algebra root

    pairs = build_edge_pairs(seeds)  # 0=natural, 1=fraction(7), 2=algebra, 3=fraction(9)
    assert (1, 0) in pairs  # fraction -> natural
    assert (2, 1) in pairs and (2, 0) in pairs  # algebra -> both
    assert (2, 3) not in pairs  # pinned to the LOWEST class occurrence
    # Unknown names (e.g. শতকরা here) are skipped, never invented.
    assert len(pairs) == 3


def test_parse_concept_names_verbatim_guard() -> None:
    text = f"{FRACTION} এবং শতকরার মৌলিক ধারণা"
    raw = f'["{FRACTION}", "শতকরা", "কাল্পনিক বস্তু", "পাঠ্য", 42, "a"]'
    names = parse_concept_names(raw, chapter="পাঠ্য", text=text)
    # Kept: verbatim-in-text names. Dropped: hallucination, the chapter name
    # itself, a non-string, and a too-short string.
    assert names == [FRACTION, "শতকরা"]
    assert parse_concept_names("no json here at all", chapter="পাঠ্য", text=text) == []
    assert parse_concept_names(f'answer: ["{FRACTION}"] thanks', chapter="পাঠ্য", text=text) == [
        FRACTION
    ]
    assert parse_concept_names(raw, chapter="পাঠ্য", text=text, limit=1) == [FRACTION]


# --- DB layer (real sample corpus, deterministic) ------------------------------


def test_db_layer_mastery_and_gaps(session) -> None:
    corpus = load_sample_corpus()
    seeded = ensure_concepts(session, corpus)
    assert seeded >= 30
    assert FRACTION in edges_by_name(session)

    review = [
        ReviewItem(
            question_text=f"{FRACTION} প্রশ্ন {i}",
            options=["a", "b", "c", "d"],
            chosen=0,
            correct_index=0 if i == 0 else 1,
            is_correct=i == 0,
            chapter=FRACTION,
        )
        for i in range(5)
    ]
    record_quiz_result(session, 1, review, class_level=7)
    m = mastery_map(session, 1)[FRACTION]
    # ভগ্নাংশ exists as chapter root in BOTH class 6 and 7; mastery_map merges
    # same-name roots, so counts double but the accuracy stays exactly 20%.
    assert m[1] > 0 and m[0] * 5 == m[1]

    gaps = student_gaps(session, 1)
    frac_gap = next(g for g in gaps if g.concept == FRACTION and g.prereq == NATURAL)
    assert frac_gap.depth == 1 and frac_gap.prereq_pct is None

    # ensure_concepts is idempotent: a second call never re-seeds.
    before = int(session.execute(select(func.count(Concept.id))).scalar_one())
    assert ensure_concepts(session, corpus) == before


# --- API layer ------------------------------------------------------------------


def test_kg_gaps_requires_auth_and_returns_shape(client: TestClient) -> None:
    assert client.get("/kg/gaps").status_code in (401, 403)

    student_id, headers = _make_student(client, "kgshape@example.com")
    # A teacher has no student profile: honest 404, not a fabricated empty list.
    _register(client, "kgteacher@example.com", role="teacher")
    teacher_headers = _login(client, "kgteacher@example.com")
    assert client.get("/kg/gaps", headers=teacher_headers).status_code == 404

    _run_quiz(client, student_id, headers, answers=1)
    res = client.get("/kg/gaps", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"weak_threshold_pct", "min_attempts", "gaps"}
    assert body["weak_threshold_pct"] == 50.0
    assert body["min_attempts"] == 3
    for gap in body["gaps"]:
        assert set(gap) == {"concept", "prereq", "prereq_pct", "prereq_total", "depth"}
        assert gap["depth"] >= 1


def test_kg_gaps_surfaces_gap_after_all_wrong_quizzes(client: TestClient) -> None:
    student_id, headers = _make_student(client, "kgweak@example.com", class_level=7)
    for _ in range(3):
        _run_quiz(client, student_id, headers, answers=1)
    gaps = client.get("/kg/gaps", headers=headers).json()["gaps"]
    # 15 graded answers, ~1/4 lucky hits: at least one chapter root must be
    # weak with a curated prerequisite (pigeonhole over 7th-grade chapters).
    assert gaps, "repeatedly wrong quiz answers must surface a KG gap"
    assert all(isinstance(g["concept"], str) and g["concept"] for g in gaps)


def test_kg_rebuild_is_admin_only_and_counts_graph(client: TestClient) -> None:
    student_id, headers = _make_student(client, "kgrb@example.com")
    assert client.post("/kg/rebuild", headers=headers).status_code == 403

    admin = _login(client, "root@example.com")
    res = client.post("/kg/rebuild", headers=admin)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"concepts", "llm_concepts", "edges"}
    assert body["concepts"] >= 30 and body["edges"] >= 17 and body["llm_concepts"] == 0

    # Mock provider cannot produce corpus-verified names -> still roots only.
    res_llm = client.post("/kg/rebuild?llm=true", headers=admin)
    assert res_llm.status_code == 200
    assert res_llm.json()["llm_concepts"] == 0

    # Rebuild wiped mastery (fresh graph) but gaps endpoint stays healthy.
    assert client.get("/kg/gaps", headers=headers).status_code == 200
