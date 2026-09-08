"""S3.3: curriculum coverage status derivation (class x subject grid).

Pure functions so the PASS-WHEN "status derivation unit tests" hold
without a DB. For one class-subject cell:

* taught     -- the subject is assigned for that class: chapter content
                exists for (class_level, subject) OR a teacher is assigned
                (per-subject or all-subjects ClassTeacher row).
* practiced   -- at least one quiz attempt exists for the cell.
* mastered   -- practiced AND the mean graded score >= MASTERED_MIN_PCT.
* uncovered  -- neither taught nor practiced.

Precedence is mastered > practiced > taught > uncovered: practicing with
a low average is still "practiced" (needs work), not downgraded to the
merely-taught badge.
"""

MASTERED_MIN_PCT = 70.0

# Ordered most-complete first; the UI renders the first matching badge.
STATUS_MASTERED = "mastered"
STATUS_PRACTICED = "practiced"
STATUS_TAUGHT = "taught"
STATUS_UNCOVERED = "uncovered"


def avg_of(percents: list[float]) -> float | None:
    """Mean of graded percentages; None when there is nothing graded."""
    if not percents:
        return None
    return round(sum(percents) / len(percents), 2)


def derive_status(
    taught: bool,
    practiced: bool,
    avg_pct: float | None,
    mastered_min: float = MASTERED_MIN_PCT,
) -> str:
    """Single source of truth for one coverage cell's badge."""
    if practiced and avg_pct is not None and avg_pct >= mastered_min:
        return STATUS_MASTERED
    if practiced:
        return STATUS_PRACTICED
    if taught:
        return STATUS_TAUGHT
    return STATUS_UNCOVERED


def is_taught(
    has_content: bool,
    assigned_subjects: set[str],
    subject: str,
    all_subjects_marker: str = "",
) -> bool:
    """Assigned means content exists or a ClassTeacher row covers the subject.

    ``all_subjects_marker`` ('' in the DB) means the teacher covers every
    subject for the class.
    """
    return has_content or subject in assigned_subjects or all_subjects_marker in assigned_subjects
