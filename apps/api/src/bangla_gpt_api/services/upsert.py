"""get-or-create and atomic-counter helpers for unique-keyed rows.

Seven sites in this codebase built their own get-or-create by hand: daily
activity, the SM-2 revision queue, concept mastery, adaptive ability, chapter
progress, the question bank, and the classroom roster import. Every one had
the same check-then-insert race hidden under a unique constraint: two
concurrent first-writers both read "absent", both INSERT, and the loser
answered 500 — in the quiz and chat paths *after* the business write had
already been committed, so the user saw a failure for work that had succeeded
and been billed (and daily counters silently lost increments even when no
error surfaced).

``get_or_create`` closes the race with a SAVEPOINT around only the INSERT:

* a unique violation rolls the savepoint back and leaves the caller's earlier
  work in the transaction untouched (the alternative — ``db.rollback()`` —
  would discard it), then the row is re-read and returned;
* on every other path the behavior is identical to the hand-rolled version.

``increment`` then makes counter bumps ``col = col + :delta``, computed by the
database, so concurrent bumps add up instead of overwriting each other.
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

Model = TypeVar("Model")

__all__ = ["get_or_create", "increment"]


def get_or_create(
    db: Session,
    *,
    model: type[Model],
    lookup: Select,
    defaults: dict[str, Any],
) -> tuple[Model, bool]:
    """The row ``lookup`` selects, or a newly inserted one from ``defaults``.

    Returns ``(row, created)``. Does NOT commit — callers keep their own
    transaction boundary; the created row is flushed and visible to the
    session before returning.
    """
    row = db.execute(lookup).scalar_one_or_none()
    if row is not None:
        return row, False
    pending = model(**defaults)
    try:
        with db.begin_nested():
            db.add(pending)
            db.flush()
    except IntegrityError:
        # A concurrent writer won the unique constraint. The savepoint
        # already rolled back — the caller's pending work is intact — and the
        # winner's commit is visible, so the lookup now finds the row.
        found = db.execute(lookup).scalar_one_or_none()
        if found is None:  # pragma: no cover - would mean a different constraint failed
            raise
        return found, False
    return pending, True


def increment(
    db: Session,
    *,
    model: type[Model],
    where: tuple[Any, ...],
    deltas: dict[str, int],
) -> None:
    """``UPDATE model SET col = col + delta`` for each non-zero delta.

    The right-hand side is computed by the database, so N concurrent bumps
    produce N additions — the lost-update failure mode of
    ``row.questions += 1`` on an ORM object.
    """
    effective = {col: delta for col, delta in deltas.items() if delta}
    if not effective:
        return
    values = {col: getattr(model, col) + delta for col, delta in effective.items()}
    db.execute(
        update(model).where(*where).values(**values).execution_options(synchronize_session=False)
    )
