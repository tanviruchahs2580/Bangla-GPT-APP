"""S4.5 Adaptive practice engine.

Elo-style ratings on two axes:
- practice_items.elo  -- per-item difficulty (cloze fingerprint = sha256 of
  chunk id + blanked term, stable across regenerations)
- student_abilities.ability -- per-concept student ability

Selection rule (spec): next question difficulty targets
``ability + 0.5 * SIGMA`` -- slightly above the student's current level so a
correct streak keeps pushing and misses pull back (K-factor updates make
"correct -> harder, wrong -> easier" fall out of the math, unit-tested).

Wrong answers run a knowledge-graph gap check (S4.4 is the single source of
gap truth): every surfaced gap becomes a re-teach card carrying a grounded
excerpt from the prerequisite chapter itself -- no AI call, no invented text.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import PracticeItem, StudentAbility
from bangla_gpt_api.services import knowledge

if TYPE_CHECKING:  # pragma: no cover
    from bangla_gpt_api.curriculum.models import Chunk
    from bangla_gpt_api.services.quiz import GeneratedQuestion

# --- Elo constants -------------------------------------------------------------

DEFAULT_ELO = 1200.0
K_FACTOR = 24.0
# Practical sigma of the Elo scale: 0.5 sigma = 100 points above ability,
# i.e. roughly a 64% expected success rate -- "reachable stretch".
SIGMA = 200.0
POOL_MULTIPLIER = 3
POOL_CAP = 30
RETEACH_LIMIT = 3
RETEACH_EXCERPT_CHARS = 280


# --- pure layer (unit-tested, no DB) ---------------------------------------------


def expected_score(ability: float, elo: float) -> float:
    """Standard Elo expectation for the ability side."""
    return 1.0 / (1.0 + 10.0 ** ((elo - ability) / 400.0))


def update_pair(ability: float, elo: float, correct: bool) -> tuple[float, float]:
    """Zero-sum Elo update; returns (new_ability, new_item_elo)."""
    exp = expected_score(ability, elo)
    score = 1.0 if correct else 0.0
    return (
        round(ability + K_FACTOR * (score - exp), 1),
        round(elo + K_FACTOR * (exp - score), 1),
    )


def next_target(ability: float, sigma: float = SIGMA) -> float:
    """Spec selection target: ability + 0.5 sigma."""
    return ability + 0.5 * sigma


def select_item_ids(
    items: Sequence[tuple[str, str]],
    *,
    elo_by_id: Mapping[str, float],
    ability_by_chapter: Mapping[str, float],
    num: int,
    sigma: float = SIGMA,
) -> list[str]:
    """Pick `num` item ids nearest to each item's chapter-target difficulty.

    items: (item_id, chapter) pairs. Ties break on item id -> deterministic.
    """
    scored = sorted(
        items,
        key=lambda pair: (
            abs(
                elo_by_id.get(pair[0], DEFAULT_ELO)
                - next_target(ability_by_chapter.get(pair[1], DEFAULT_ELO), sigma)
            ),
            pair[0],
        ),
    )
    return [item_id for item_id, _chapter in scored[:num]]


def build_excerpt(text: str, limit: int = RETEACH_EXCERPT_CHARS) -> str:
    """First whole sentences of the prerequisite chapter, capped at `limit`."""
    cleaned = " ".join(part.strip() for part in text.split("\n") if part.strip())
    out: list[str] = []
    used = 0
    for sentence in cleaned.replace("।", "।\n").split("\n"):
        sentence = sentence.strip()
        if not sentence:
            continue
        if used and used + len(sentence) > limit:
            break
        out.append(sentence)
        used += len(sentence)
    excerpt = " ".join(out)
    return excerpt if len(excerpt) <= limit else excerpt[: limit - 1].rstrip() + "…"


# --- DB layer ---------------------------------------------------------------------


def ensure_items(
    db: Session,
    questions: Sequence[GeneratedQuestion],
    *,
    subject: str | None,
    class_level: int,
) -> None:
    """Create PracticeItem rows for unseen fingerprints (explicit defaults)."""
    ids = [q.id for q in questions]
    if not ids:
        return
    existing = {
        row
        for (row,) in db.execute(
            select(PracticeItem.fingerprint).where(PracticeItem.fingerprint.in_(ids))
        )
    }
    seen: set[str] = set()
    for q in questions:
        if q.id in existing or q.id in seen:
            continue
        seen.add(q.id)
        db.add(
            PracticeItem(
                fingerprint=q.id,
                chapter=q.chapter,
                subject=subject or "any",
                class_level=class_level,
                elo=DEFAULT_ELO,
                attempts=0,
                correct=0,
            )
        )
    db.commit()


def ability_map(db: Session, student_id: int) -> dict[str, float]:
    return {
        row.concept: row.ability
        for row in db.execute(
            select(StudentAbility).where(StudentAbility.student_id == student_id)
        ).scalars()
    }


def pick_questions(
    db: Session,
    pool: Sequence[GeneratedQuestion],
    *,
    student_id: int,
    subject: str | None,
    class_level: int,
    num: int,
) -> list[GeneratedQuestion]:
    """Order the generated pool by |item elo - (ability + 0.5 sigma)| and
    take the first `num` (nearest-to-target first)."""
    ensure_items(db, pool, subject=subject, class_level=class_level)
    abilities = ability_map(db, student_id)  # keys are canonical concept names
    chosen = select_item_ids(
        [(q.id, knowledge.canonical(q.chapter)) for q in pool],
        elo_by_id={
            row.fingerprint: row.elo
            for row in db.execute(
                select(PracticeItem).where(PracticeItem.fingerprint.in_([q.id for q in pool]))
            ).scalars()
        },
        ability_by_chapter=abilities,
        num=num,
    )
    by_id = {q.id: q for q in pool}
    return [by_id[item_id] for item_id in chosen]


def apply_review(
    db: Session,
    *,
    student_id: int,
    class_level: int,
    graded: Sequence[tuple[str, str, bool]],  # (item fingerprint, chapter, correct)
) -> None:
    """Elo-update ability (per concept) and item difficulty after grading."""
    # db.get cannot see PENDING rows (their PK is unset until flush), so a
    # chapter appearing twice in one review would create duplicate rows.
    fresh: dict[str, StudentAbility] = {}
    for fingerprint, chapter, correct in graded:
        concept = knowledge.canonical(chapter)
        ability_row = fresh.get(concept) or db.get(StudentAbility, (student_id, concept))
        if ability_row is None:
            ability_row = StudentAbility(
                student_id=student_id,
                concept=concept,
                class_level=class_level,
                ability=DEFAULT_ELO,
                attempts=0,
            )
            db.add(ability_row)
            fresh[concept] = ability_row
        item = db.get(PracticeItem, fingerprint)
        item_elo = item.elo if item is not None else DEFAULT_ELO
        new_ability, new_elo = update_pair(ability_row.ability, item_elo, correct)
        ability_row.ability = new_ability
        ability_row.attempts += 1
        if item is not None:
            item.elo = new_elo
            item.attempts += 1
            item.correct += 1 if correct else 0
    db.commit()


def _cards_for_gaps(chunks: Sequence[Chunk], gaps: Iterable[knowledge.Gap]) -> list[dict]:
    """Gap -> grounded re-teach card (excerpt from the prereq chapter itself)."""
    first_chunk: dict[str, str] = {}
    for chunk in sorted(
        (c for c in chunks if c.meta.chapter), key=lambda c: (c.meta.class_level, c.id)
    ):
        first_chunk.setdefault(chunk.meta.chapter, chunk.text)
    cards: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for gap in gaps:
        key = (gap.concept, gap.prereq)
        if key in seen or gap.prereq not in first_chunk:
            continue
        seen.add(key)
        cards.append(
            {
                "concept": gap.concept,
                "prereq": gap.prereq,
                "depth": gap.depth,
                "excerpt": build_excerpt(first_chunk[gap.prereq]),
            }
        )
    return cards[:RETEACH_LIMIT]


def open_reteach_cards(db: Session, chunks: Sequence[Chunk], student_id: int) -> list[dict]:
    """Cards for every currently open gap -- served BEFORE the next question."""
    return _cards_for_gaps(chunks, knowledge.student_gaps(db, student_id))


def wrong_answer_reteach_cards(
    db: Session, chunks: Sequence[Chunk], student_id: int, wrong_chapters: Iterable[str]
) -> list[dict]:
    """Spec rule: a wrong answer triggers a KG gap check for that concept;
    any surfaced gap becomes a re-teach card."""
    wanted = {knowledge.canonical(chapter) for chapter in wrong_chapters}
    if not wanted:
        return []
    gaps = [gap for gap in knowledge.student_gaps(db, student_id) if gap.concept in wanted]
    return _cards_for_gaps(chunks, gaps)
