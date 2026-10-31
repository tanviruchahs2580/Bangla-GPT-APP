"""Shared route helpers — split from the main.py god-module.

F-077: the single 915-line grab-bag was itself split by concern. The image
boundary lives in ``routers/_images.py``, the document-generation pipeline in
``routers/_documents.py``, the education context in ``routers/_context.py``
and the analytics sanitizer/writer in ``services/analytics.py``. The names
below are re-exported so every import site that predates the split keeps
working; this module now holds only the student/school lookups and the small
shared predicates.
"""

import hashlib
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AnswerLog,
    ClassRoom,
    ClassStudent,
    Notification,
    QuizAttempt,
    School,
    Student,
    User,
)
from bangla_gpt_api.retrieval.bm25 import tokenize
from bangla_gpt_api.schemas import StudentBrief

# --- split modules, re-exported under their historical names (F-077) ------
# Listed in __all__ so both ruff and mypy treat them as intentional
# re-exports; every `from .common import name` site predates the split and
# stays unchanged.
from bangla_gpt_api.services.analytics import (
    _EVENT_DIGIT_RUN_RE,
    _EVENT_DROP_KEY_RE,
    _EVENT_PROP_MAX_LEN,
    _EVENT_SAFE_STRING_RE,
    _event_string_value_allowed,
    _record_analytics,
    _sanitize_event_props,
)

from ._context import (
    EXPLANATION_STYLE_DIRECTIVES,
    _request_context,
    build_personalization_block,
)
from ._documents import (
    _DOC_IN_MODELS,
    _DOC_LABELS,
    _QUESTION_TEXT_KEYS,
    DocumentInputError,
    _doc_in_for,
    _document_title,
    _generate_document,
    _generate_document_prepare,
    _iter_question_texts,
    _persist_document,
    _screen_free_text,
)
from ._images import (
    _IMAGE_MAX_BYTES,
    _IMAGE_MIME_ALLOWED,
    _sanitized_image_payload,
    _sniff_image_mime,
    _validate_chat_image,
)

__all__ = [
    "DEFAULT_SCHOOL_CODE",
    "EXPLANATION_STYLE_DIRECTIVES",
    "SCHOOL_CODE_ALPHABET",
    "_DOC_IN_MODELS",
    "_DOC_LABELS",
    "_EVENT_DIGIT_RUN_RE",
    "_EVENT_DROP_KEY_RE",
    "_EVENT_PROP_MAX_LEN",
    "_EVENT_SAFE_STRING_RE",
    "_IMAGE_MAX_BYTES",
    "_IMAGE_MIME_ALLOWED",
    "_QUESTION_TEXT_KEYS",
    "DocumentInputError",
    "_answer_cells",
    "_answer_confidence",
    "_attempt_percents",
    "_classroom_or_404",
    "_default_school",
    "_doc_in_for",
    "_document_title",
    "_event_string_value_allowed",
    "_generate_document",
    "_generate_document_prepare",
    "_hash_invite",
    "_is_question_like",
    "_iter_question_texts",
    "_load_class_students",
    "_persist_document",
    "_record_analytics",
    "_request_context",
    "_sanitize_event_props",
    "_sanitized_image_payload",
    "_screen_free_text",
    "_sniff_image_mime",
    "_student_briefs",
    "_student_profile",
    "_validate_chat_image",
    "build_personalization_block",
    "canonical_subject",
    "notify_user",
    "request_language",
    "source_scores",
]

# Canonical subject keys used by the corpus; aliases accepted from clients
# are normalized so 'math' and 'mathematics' both resolve (frontend bug fix).
_SUBJECT_ALIASES = {"math": "mathematics", "গণিত": "mathematics"}


def canonical_subject(subject: str | None) -> str | None:
    if subject is None:
        return None
    return _SUBJECT_ALIASES.get(subject.strip().lower(), subject.strip().lower())


def request_language(header: str | None) -> str | None:
    """The caller's language tag from an ``Accept-Language`` header (F-107).

    Returns the base subtag (``bn``/``en``) of the highest-quality supported
    entry, None when the header is absent or names neither -- None keeps the
    mailer's shipped bilingual copy, so an unresolved language is never
    worse than before this existed. A minimal RFC 9110 negotiation: the
    mail copy ships in exactly the product's two languages, so unsupported
    tags and the ``*`` wildcard are skipped rather than tracked.
    """
    best: tuple[float, str] | None = None
    for entry in (header or "").split(","):
        parts = entry.split(";")
        tag = parts[0].strip().lower()
        if not tag or tag == "*":
            continue
        quality = 1.0
        for parameter in parts[1:]:
            key, _, value = parameter.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality <= 0:
            continue
        base = tag.split("-")[0]
        if base not in ("bn", "en"):
            continue
        if best is None or quality > best[0]:
            best = (quality, base)
    return best[1] if best is not None else None


# Interrogative Bangla words. Used both for question-like queries
# (ask-in-Tutor action) and for question-style textbook sections (trailing
# interrogative word).
_INTERROGATIVE_TOKENS = frozenset(
    {
        "কি",
        "কী",
        "কেন",
        "কখন",
        "কত",
        "কার",
        "কোথায়",
        "কেমন",
        "কোন",
        "কিভাবে",
        "কীভাবে",
    }
)


def _is_question_like(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith("?"):
        return True
    return any(token in _INTERROGATIVE_TOKENS for token in tokenize(stripped))


def notify_user(
    db: Session,
    user_id: int | None,
    kind: str,
    code: str,
    params: dict[str, Any] | None = None,
    link: str | None = None,
) -> None:
    """Queue one in-app notification for ``user_id`` (skips NULL users, e.g.
    CSV-imported students without an account yet). Adds only -- the CALLER's
    commit persists it together with the business row that triggered it."""
    if user_id is None:
        return
    db.add(
        Notification(
            user_id=user_id,
            kind=kind[:40],
            code=code[:64],
            params=params or {},
            link=link[:200] if link else None,
        )
    )


# --- answer confidence ---------------------------------------------------
# Documented formula (0..1, computed at answer finalization, stored nowhere but
# in the payload/schema field):
#
# refused answer -> 0.0
# no grounding info at all -> None (unknown, honest)
# otherwise: clamp01(
# 0.5 * min(1.0, len(source_scores) / 2) # retrieval breadth
# + 0.5 * mean(min(1.0, s) for s in scores) # retrieval depth
# )
#
# SourceRef.score is an unbounded BM25 value, so every raw score is capped at
# 1.0 before averaging. When grounding is known but no sources survived, the
# depth term is 0 and only the (zero) breadth term counts.
def _answer_confidence(
    grounded: bool | None,
    refused_reason: str | None,
    scores: list[float],
) -> float | None:
    from bangla_gpt_api.services.safety import answer_confidence

    return answer_confidence(grounded, refused_reason, scores)


def source_scores(refs: Any) -> list[float]:
    """BM25 scores of a SourceRef list (unbounded values; capped by caller)."""
    return [float(getattr(r, "score", 0.0)) for r in refs]


DEFAULT_SCHOOL_CODE = "BGPT-DEFAULT"

SCHOOL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O/0, I/1


def _student_profile(db: Session, user: User) -> Student:
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "no_student_profile", "message": "Student profile not found"},
        )
    return student


def _load_class_students(
    db: Session,
    class_level: int | None,
    limit: int | None = None,
    school_id: int | None = None,
) -> list[Student]:
    # tenancy: when the caller is bound to a school, only students
    # enrolled in a classroom of THAT school are visible. school_id=None
    # keeps the legacy platform-wide view (school-less teachers, admins).
    statement = select(Student).order_by(Student.id)
    if class_level is not None:
        statement = statement.where(Student.class_level == class_level)
    if school_id is not None:
        statement = (
            statement.join(ClassStudent, ClassStudent.student_id == Student.id)
            .join(ClassRoom, ClassRoom.id == ClassStudent.classroom_id)
            .where(ClassRoom.school_id == school_id)
        )
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.execute(statement).scalars().all())


def _student_briefs(db: Session, students: list[Student]) -> list[StudentBrief]:
    # one grouped aggregate for the whole roster (was 1 query per
    # student, each pulling every attempt row as a full ORM object).
    # avg ignores NULL score_pct, matching the previous Python average.
    stats: dict[int, tuple[int, float | None]] = {}
    ids = [s.id for s in students]
    for i in range(0, len(ids), 500):  # chunked: safe under SQLITE_MAX_VARIABLES
        chunk = ids[i : i + 500]
        for sid, n, avg in db.execute(
            select(QuizAttempt.student_id, func.count(), func.avg(QuizAttempt.score_pct))
            .where(
                QuizAttempt.student_id.in_(chunk),
                QuizAttempt.status == "graded",
            )
            .group_by(QuizAttempt.student_id)
        ):
            stats[sid] = (n, float(avg) if avg is not None else None)
    briefs: list[StudentBrief] = []
    for student in students:
        n, avg = stats.get(student.id, (0, None))
        briefs.append(
            StudentBrief(
                student_id=student.id,
                name=student.name,
                class_level=student.class_level,
                attempts_graded=n,
                avg_score_pct=round(avg, 2) if avg is not None else None,
            )
        )
    return briefs


def _default_school(db: Session) -> School:
    school = db.execute(
        select(School).where(School.code == DEFAULT_SCHOOL_CODE)
    ).scalar_one_or_none()
    if school is None:
        school = School(name="Default School", code=DEFAULT_SCHOOL_CODE)
        db.add(school)
        try:
            db.flush()
        except IntegrityError:  # concurrent creation
            db.rollback()
            school = db.execute(
                select(School).where(School.code == DEFAULT_SCHOOL_CODE)
            ).scalar_one()
    return school


def _classroom_or_404(db: Session, room_id: int) -> ClassRoom:
    room = db.get(ClassRoom, room_id)
    if room is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "classroom_not_found", "message": "classroom not found"},
        )
    return room


def _attempt_percents(db: Session, student_ids: list[int]) -> dict[int, list[float]]:
    """Chronological graded score percentages per student (trend input)."""
    out: dict[int, list[float]] = defaultdict(list)
    if not student_ids:
        return out
    rows = db.execute(
        select(QuizAttempt.student_id, QuizAttempt.score_pct)
        .where(
            QuizAttempt.student_id.in_(student_ids),
            QuizAttempt.status == "graded",
            QuizAttempt.score_pct.is_not(None),
        )
        .order_by(QuizAttempt.student_id, QuizAttempt.created_at.asc())
    ).all()
    for sid, pct in rows:
        if pct is not None:
            out[sid].append(float(pct))
    return out


def _answer_cells(db: Session, student_ids: list[int]) -> dict[int, dict[str, list[int]]]:
    """(asked, correct) per student x concept from graded quiz answers."""
    cells: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    if not student_ids:
        return cells
    rows = db.execute(
        select(QuizAttempt.student_id, AnswerLog.chapter, AnswerLog.is_correct)
        .join(AnswerLog, AnswerLog.attempt_id == QuizAttempt.id)
        .where(QuizAttempt.student_id.in_(student_ids), QuizAttempt.status == "graded")
    ).all()
    for sid, chapter, ok in rows:
        cell = cells[sid][chapter]
        cell[0] += 1
        cell[1] += int(ok)
    return cells


def _hash_invite(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()
