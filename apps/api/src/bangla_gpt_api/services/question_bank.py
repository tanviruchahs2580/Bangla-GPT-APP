"""S2.9 question bank: normalize -> dedupe key -> store reviewed questions -> reuse.

The bank is a pure content store: the dedupe key is a sha256 over the
NFKC-normalized, case-folded, whitespace-collapsed question text, so trivial
reformatting of the same question collapses onto one row. Generation paths
(``/teacher/qpapers`` drafts and the per-question replace) consult the bank
before/after AI generation and record how much of the result was already a
reviewed question (the reuse metric, logged by the API layer).
"""

import hashlib
import unicodedata
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import QuestionBankEntry


def normalize_text(text: str) -> str:
    """Canonical form used for duplicate detection.

    NFKC folds compatibility variants (important for Bengali composites),
    casefold() makes Latin reuse insensitive to case, and splitting/joining
    collapses every whitespace run.
    """
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def dedupe_key(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def is_duplicate(db: Session, text: str) -> bool:
    return (
        db.execute(
            select(QuestionBankEntry.id).where(QuestionBankEntry.dedupe_key == dedupe_key(text))
        ).first()
        is not None
    )


def store_reviewed(
    db: Session,
    *,
    teacher_id: int,
    text: str,
    options: Sequence[str],
    answer_index: int | None,
    subject: str,
    chapter: str,
    class_level: int,
    source: str = "qp_review",
) -> tuple[QuestionBankEntry, bool]:
    """Insert the reviewed question, or return the existing row.

    Returns ``(row, created)``. Flushes but does not commit -- callers keep
    their own transaction boundary.
    """
    key = dedupe_key(text)
    existing = db.execute(
        select(QuestionBankEntry).where(QuestionBankEntry.dedupe_key == key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    row = QuestionBankEntry(
        teacher_id=teacher_id,
        dedupe_key=key,
        question_text=text,
        options=[str(o) for o in options],
        answer_index=answer_index,
        subject=subject,
        chapter=chapter,
        class_level=class_level,
        source=source,
    )
    db.add(row)
    db.flush()
    return row, True


def find_reusable(
    db: Session,
    *,
    class_level: int,
    subject: str | None = None,
    chapter: str | None = None,
    exclude_texts: Iterable[str] = (),
    limit: int = 1,
) -> list[QuestionBankEntry]:
    """Reviewed questions reusable for a generation request.

    Filters to the same class level (and subject/chapter when given), newest
    first, skipping anything already used on the paper being edited.
    """
    excluded = {normalize_text(text) for text in exclude_texts}
    stmt = (
        select(QuestionBankEntry)
        .where(QuestionBankEntry.class_level == class_level)
        .order_by(QuestionBankEntry.created_at.desc(), QuestionBankEntry.id.desc())
    )
    if subject is not None:
        stmt = stmt.where(QuestionBankEntry.subject == subject)
    if chapter is not None:
        stmt = stmt.where(QuestionBankEntry.chapter == chapter)
    out: list[QuestionBankEntry] = []
    for row in db.execute(stmt).scalars().all():
        if normalize_text(row.question_text) in excluded:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def bank_keys(db: Session, *, class_level: int) -> set[str]:
    """All dedupe keys banked for a class level (for reuse-metric math)."""
    rows = db.execute(
        select(QuestionBankEntry.dedupe_key).where(QuestionBankEntry.class_level == class_level)
    ).all()
    return {str(r[0]) for r in rows}
