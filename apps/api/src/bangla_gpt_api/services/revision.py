"""S1.10 — SM-2-lite spaced-revision queue (interval / ease / due_date).

Simplified SM-2: successful recalls progress 1 -> 3 -> 7 days, then grow by
interval * ease. A failed recall (quality < 3) resets the repetition count and
puts the item back due *today*. Day arithmetic follows the Asia/Dhaka calendar
like the activity heatmap.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from bangla_gpt_api.services.activity import dhaka_date

if TYPE_CHECKING:  # pragma: no cover
    from bangla_gpt_api.schemas import ReviewItem

MIN_EASE = 1.3
DEFAULT_EASE = 2.5


def next_schedule(
    reps: int, interval_days: int, ease: float, quality: int
) -> tuple[int, int, float]:
    """Return (reps, interval_days, ease) after one review of the given quality.

    quality 0..5; >= 3 counts as a successful recall.
    """
    q = max(0, min(5, quality))
    new_ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if new_ease < MIN_EASE:
        new_ease = MIN_EASE
    if q < 3:
        # Forgotten: start over, due again today, ease takes a small hit.
        return 0, 0, max(MIN_EASE, round(ease - 0.2, 4))
    reps += 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 3
    elif reps == 3:
        interval = 7
    else:
        interval = max(1, round(interval_days * new_ease))
    return reps, interval, round(new_ease, 4)


def add_days(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def record_quiz_result(
    db: object,
    student_id: int,
    review: list[ReviewItem],
    subject: str | None,
    class_level: int | None,
    when: datetime | None = None,
) -> None:
    """Seed/refresh the revision queue from a graded quiz's review items.

    Wrong items become due today (reps reset); correct items enter the schedule
    with a 1-day interval. Existing questions keep their history: a correct
    review bumps reps, a wrong one resets it and re-due-s today.
    """
    from sqlalchemy import select

    from bangla_gpt_api.db.models import RevisionItem

    today = dhaka_date(when or datetime.now(UTC))
    for item in review:
        quality = 5 if item.is_correct else 1
        row = (
            db.execute(  # type: ignore[attr-defined]
                select(RevisionItem).where(
                    RevisionItem.student_id == student_id,
                    RevisionItem.question == item.question_text,
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            row = RevisionItem(
                student_id=student_id,
                question=item.question_text,
                options_json=list(item.options),
                correct_index=item.correct_index,
                chapter=item.chapter,
                subject=subject,
                class_level=class_level,
                reps=0,
                interval_days=0,
                ease_factor=DEFAULT_EASE,
                due_date=today,
            )
            db.add(row)  # type: ignore[attr-defined]
        else:
            row.options_json = list(item.options)
            row.correct_index = item.correct_index
            row.chapter = item.chapter
        reps, interval, ease = next_schedule(row.reps, row.interval_days, row.ease_factor, quality)
        row.reps, row.interval_days, row.ease_factor = reps, interval, ease
        row.due_date = today if quality < 3 else add_days(today, interval)
    db.commit()  # type: ignore[attr-defined]


def due_items(db: object, student_id: int, today: str, limit: int = 20) -> list:
    """Due-today revision items, oldest due first."""
    from sqlalchemy import select

    from bangla_gpt_api.db.models import RevisionItem

    return list(
        db.execute(  # type: ignore[attr-defined]
            select(RevisionItem)
            .where(RevisionItem.student_id == student_id, RevisionItem.due_date <= today)
            .order_by(RevisionItem.due_date, RevisionItem.id)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def due_count(db: object, student_id: int, today: str) -> int:
    from sqlalchemy import func, select

    from bangla_gpt_api.db.models import RevisionItem

    return int(
        db.execute(  # type: ignore[attr-defined]
            select(func.count())
            .select_from(RevisionItem)
            .where(RevisionItem.student_id == student_id, RevisionItem.due_date <= today)
        ).scalar_one()
    )
