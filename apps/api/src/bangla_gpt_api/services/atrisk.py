"""S2.7: at-risk detection + 3-week support plan rules.

Pure functions so the PASS-WHEN "rule unit tests" hold without a DB:
* at-risk = average score < 40% OR a downward trend across graded attempts.
* trend compares accuracy of the oldest half vs the newest half of a
  student's graded attempts (chronological); needs >= 4 attempts, else flat.
* support plan = deterministic 3-week structure over the weakest concepts:
  Week 1 concept (re-read + tutor), Week 2 practice, Week 3 assessment.
"""

from typing import Any

AT_RISK_AVG = 40.0  # percent
TREND_DROP = 10.0  # percentage points between halves to count as downward
MIN_ATTEMPTS_FOR_TREND = 4

WEEK_ACTIONS: tuple[tuple[str, str], ...] = (
    ("week1", "concept"),
    ("week2", "practice"),
    ("week3", "assessment"),
)


def avg_pct(percents: list[float]) -> float | None:
    """Mean of the given percentages; None when there is nothing graded."""
    if not percents:
        return None
    return round(sum(percents) / len(percents), 2)


def score_trend(attempt_percents: list[float]) -> str:
    """'down' | 'up' | 'flat' -- halves compare over chronological attempts."""
    if len(attempt_percents) < MIN_ATTEMPTS_FOR_TREND:
        return "flat"
    mid = len(attempt_percents) // 2
    first = avg_pct(attempt_percents[:mid]) or 0.0
    second = avg_pct(attempt_percents[mid:]) or 0.0
    if second < first - TREND_DROP:
        return "down"
    if second > first + TREND_DROP:
        return "up"
    return "flat"


def is_at_risk(avg: float | None, trend: str) -> bool:
    """Spec rule: avg < 40% OR downward trend. Ungraded students are not flagged."""
    if avg is not None and avg < AT_RISK_AVG:
        return True
    return trend == "down"


def cell_accuracy(asked: int, correct: int) -> float | None:
    if asked <= 0:
        return None
    return round(100.0 * correct / asked, 2)


def build_plan(weak_concepts: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic 3-week plan from weakest concepts (name+accuracy dicts)."""
    if not weak_concepts:
        raise ValueError("support plan needs at least one weak concept")
    focus = weak_concepts[:3]
    names = [c["name"] for c in focus]
    return {
        "weeks": [
            {
                "week": 1,
                "stage": "concept",
                "concepts": names,
                "action": "read",
                "detail": ", ".join(names),
            },
            {
                "week": 2,
                "stage": "practice",
                "concepts": names,
                "action": "quiz",
                "detail": ", ".join(names),
            },
            {
                "week": 3,
                "stage": "assessment",
                "concepts": names,
                "action": "test",
                "detail": ", ".join(names),
            },
        ],
        "focus_concepts": names,
    }
