"""S1.9 — daily activity, streaks and heatmap (Asia/Dhaka day boundaries)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from typing import Protocol

try:  # preferred: real IANA zone when tzdata is available
    from zoneinfo import ZoneInfo

    DHAKA: tzinfo = ZoneInfo("Asia/Dhaka")
except Exception:  # pragma: no cover - Windows without tzdata package
    # Asia/Dhaka has no DST: the +06:00 fixed offset is always exact.
    DHAKA = timezone(timedelta(hours=6))


def dhaka_date(now: datetime) -> str:
    """ISO date string for the given instant in Asia/Dhaka."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(DHAKA).date().isoformat()


def now_dhaka() -> datetime:
    return datetime.now(UTC).astimezone(DHAKA)


class _ActivityRow(Protocol):
    date: str


def streak_days(active_dates: set[str], today_iso: str) -> int:
    """Consecutive days with activity, ending today or (if today has no
    activity yet) yesterday — so a streak is not shown as broken before the
    student has had a chance to study today."""
    if not active_dates:
        return 0
    today = date.fromisoformat(today_iso)
    cursor = today if today_iso in active_dates else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in active_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def heatmap_days(rows: list[_ActivityRow], today_iso: str, days: int) -> list[dict[str, int]]:
    """Daily counts for the last `days` days (oldest first), zero-filled."""
    counts: dict[str, dict[str, int]] = {}
    for r in rows:
        entry = counts.setdefault(r.date, {"questions": 0, "quizzes": 0, "minutes": 0})
        entry["questions"] += int(getattr(r, "questions", 0) or 0)
        entry["quizzes"] += int(getattr(r, "quizzes", 0) or 0)
        entry["minutes"] += int(getattr(r, "minutes", 0) or 0)
    today = date.fromisoformat(today_iso)
    out: list[dict[str, int]] = []
    for i in range(days - 1, -1, -1):
        iso = (today - timedelta(days=i)).isoformat()
        out.append(counts.get(iso, {"questions": 0, "quizzes": 0, "minutes": 0}))
    return out


def record_activity(
    db: object,
    student_id: int,
    *,
    questions: int = 0,
    quizzes: int = 0,
    minutes: int = 0,
    when: datetime | None = None,
) -> None:
    """Upsert today's (Asia/Dhaka) activity counters for a student."""
    from sqlalchemy import select

    from bangla_gpt_api.db.models import DailyActivity

    iso = dhaka_date(when or datetime.now(UTC))
    row = (
        db.execute(  # type: ignore[attr-defined]
            select(DailyActivity).where(
                DailyActivity.student_id == student_id, DailyActivity.date == iso
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        row = DailyActivity(student_id=student_id, date=iso, questions=0, quizzes=0, minutes=0)
        db.add(row)  # type: ignore[attr-defined]
    row.questions += questions
    row.quizzes += quizzes
    row.minutes += minutes
    db.commit()  # type: ignore[attr-defined]
