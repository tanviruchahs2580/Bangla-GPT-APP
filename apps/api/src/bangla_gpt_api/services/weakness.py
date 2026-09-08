"""S4.6: weakness rollup -- the single source of truth for "what is this
student weak at".

Spec (S4.6): nightly job -> per-concept mastery -> feeds Home recommendation
+ Teacher at-risk + Parent digest. PASS-WHEN is a consistency test: the same
value must come out of all three endpoints. That is only true when NO consumer
keeps its own copy of the weakness rule, so every consumer calls
:func:`weak_concepts` / :func:`weak_names` and nothing else.

* Input: per-concept mastery cells computed from graded attempts only
  (lifetime; aggregate counts only -- message content is never read here, R11).
* Rule: a concept is weak with ``total >= knowledge.MIN_ATTEMPTS`` and
  ``pct < knowledge.WEAK_THRESHOLD_PCT`` -- the exact constants the S4.4
  knowledge-graph gap resolver uses, so quiz history, KG gaps and every
  consumer agree by construction. Chapter roots are canonicalized
  (:func:`knowledge.canonical`) so a colloquial alias merges into its concept.
* Order: ascending accuracy, ties by name -- consumers slice the same list,
  so "weakest first" means the same thing everywhere.
* :func:`refresh_mastery` is the nightly reconciliation: it recomputes the
  chapter-root rows of ConceptMastery straight from the graded answer log,
  creating any missing root concept, so the persisted per-concept mastery
  table can never drift from the history the rollup reads.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AnswerLog,
    Concept,
    ConceptMastery,
    QuizAttempt,
    _utcnow,
)
from bangla_gpt_api.services import knowledge

#: nightly slot: 21:00 UTC = 03:00 Dhaka, runs at most once per calendar day
NIGHTLY_HOUR_UTC = 21


@dataclass(frozen=True)
class WeakConcept:
    """One weak concept with the counts behind the verdict."""

    concept: str  # canonical concept name (== chapter root label in the UI)
    asked: int
    correct: int
    accuracy_pct: float


def raw_cells(db: Session, student_ids: Sequence[int]) -> dict[int, dict[str, list[int]]]:
    """(asked, correct) per student x raw chapter from graded attempts."""
    cells: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    ids = list(student_ids)
    if not ids:
        return cells
    rows = db.execute(
        select(QuizAttempt.student_id, AnswerLog.chapter, AnswerLog.is_correct)
        .join(AnswerLog, AnswerLog.attempt_id == QuizAttempt.id)
        .where(QuizAttempt.student_id.in_(ids), QuizAttempt.status == "graded")
    ).all()
    for sid, chapter, ok in rows:
        cell = cells[sid][chapter]
        cell[0] += 1
        cell[1] += int(ok)
    return cells


def merged_cells(raw: dict[str, list[int]]) -> dict[str, list[int]]:
    """Canonicalize chapter names and merge alias counts."""
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for chapter, (asked, correct) in raw.items():
        cell = out[knowledge.canonical(chapter)]
        cell[0] += asked
        cell[1] += correct
    return out


def _rank(cells: dict[str, list[int]]) -> list[WeakConcept]:
    weak: list[WeakConcept] = []
    for name, (asked, correct) in cells.items():
        if asked < knowledge.MIN_ATTEMPTS:
            continue
        acc = round(100.0 * correct / asked, 2)
        if acc >= knowledge.WEAK_THRESHOLD_PCT:
            continue
        weak.append(WeakConcept(concept=name, asked=asked, correct=correct, accuracy_pct=acc))
    return sorted(weak, key=lambda w: (w.accuracy_pct, w.concept))


def weak_concepts(db: Session, student_id: int) -> list[WeakConcept]:
    """THE weakness verdict for one student: weakest first, single rule."""
    return _rank(merged_cells(raw_cells(db, [student_id]).get(student_id, {})))


def weak_names(db: Session, student_id: int) -> list[str]:
    return [w.concept for w in weak_concepts(db, student_id)]


def weak_names_for(db: Session, student_ids: Iterable[int]) -> dict[int, list[str]]:
    """Batched :func:`weak_names` (one query for a whole class roster)."""
    all_raw = raw_cells(db, list(student_ids))
    return {sid: [w.concept for w in _rank(merged_cells(cells))] for sid, cells in all_raw.items()}


def nightly_due(now: datetime, last_day: str) -> tuple[bool, str]:
    """Pure scheduler rule: fire once per calendar day at/after the slot.

    Mirrors :func:`parent_digest.digest_due`: ``(False, "")`` when the slot
    has not arrived at all, ``(False, day)`` when today already ran.
    """
    if now.hour < NIGHTLY_HOUR_UTC:
        return False, ""
    day = now.strftime("%Y-%m-%d")
    return day != last_day, day


def refresh_mastery(db: Session) -> tuple[int, int]:
    """Nightly reconciliation of ConceptMastery chapter roots vs graded logs.

    Idempotent: recomputes root-level correct/total straight from the answer
    log and creates any chapter-root concept seen in the log but missing from
    the registry. Returns ``(students_synced, rows_synced)`` -- counts only,
    nothing student-identifying is logged (R11).
    """
    rows = db.execute(
        select(
            QuizAttempt.student_id,
            AnswerLog.chapter,
            QuizAttempt.class_level,
            QuizAttempt.subject,
            AnswerLog.is_correct,
        )
        .join(AnswerLog, AnswerLog.attempt_id == QuizAttempt.id)
        .where(QuizAttempt.status == "graded")
    ).all()
    cells: dict[tuple[int, str], list[int]] = defaultdict(lambda: [0, 0])
    meta: dict[str, tuple[int, str]] = {}
    for sid, chapter, class_level, subject, ok in rows:
        cell = cells[(sid, chapter)]
        cell[0] += 1
        cell[1] += int(ok)
        meta.setdefault(chapter, (class_level, subject))
    roots = {
        concept.chapter: concept
        for concept in db.execute(select(Concept).where(Concept.source == "chapter")).scalars()
    }
    for chapter, (class_level, subject) in meta.items():
        if chapter in roots:
            continue
        root = Concept(
            name=knowledge.canonical(chapter),
            class_level=class_level,
            subject=subject,
            chapter=chapter,
            source="chapter",
            aliases=[],
        )
        db.add(root)
        roots[chapter] = root
    db.flush()
    students: set[int] = set()
    synced = 0
    stamp = _utcnow()
    for (sid, chapter), (asked, correct) in cells.items():
        row = db.get(ConceptMastery, (sid, roots[chapter].id))
        if row is None:
            row = ConceptMastery(student_id=sid, concept_id=roots[chapter].id, correct=0, total=0)
            db.add(row)
        row.correct = correct
        row.total = asked
        row.updated_at = stamp
        students.add(sid)
        synced += 1
    db.commit()
    return len(students), synced
