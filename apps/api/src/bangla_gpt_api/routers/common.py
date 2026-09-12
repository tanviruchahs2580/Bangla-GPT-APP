"""Shared route helpers — split from the main.py god-module (ARCH-001)."""

import base64
import hashlib
import logging
import re
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    AnalyticsEventRow,
    AnswerLog,
    ClassRoom,
    ClassStudent,
    Notification,
    QuestionPaper,
    QuizAttempt,
    School,
    Student,
    TeacherDocument,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.retrieval.bm25 import tokenize
from bangla_gpt_api.schemas import (
    EXPLANATION_STYLES,
    AnswerKeyIn,
    ChatImageIn,
    HomeworkIn,
    LessonPlanIn,
    RubricIn,
    SourceRef,
    StudentBrief,
    WorksheetIn,
)
from bangla_gpt_api.services import (
    atrisk,
)
from bangla_gpt_api.services.context import (
    RequestContext,
    history_summary,
    snapshot_mastery,
)
from bangla_gpt_api.services.generators import (
    generate_answer_key,
    generate_homework,
    generate_lesson_plan,
    generate_rubric,
    generate_worksheet,
)

from .deps import Ctx

logger = logging.getLogger(__name__)

# Canonical subject keys used by the corpus; aliases accepted from clients
# are normalized so 'math' and 'mathematics' both resolve (frontend bug fix).
_SUBJECT_ALIASES = {"math": "mathematics", "গণিত": "mathematics"}


def canonical_subject(subject: str | None) -> str | None:
    if subject is None:
        return None
    return _SUBJECT_ALIASES.get(subject.strip().lower(), subject.strip().lower())


# S1.11: interrogative Bangla words (written as escapes so the source stays
# ASCII-safe). Used both for question-like queries (ask-in-Tutor action) and
# for question-style textbook sections (trailing interrogative word).
_INTERROGATIVE_TOKENS = frozenset(
    {
        "\u0995\u09bf",  # ki
        "\u0995\u09c0",  # kii
        "\u0995\u09c7\u09a8",  # keno
        "\u0995\u0996\u09a8",  # kokhon
        "\u0995\u09a4",  # kot
        "\u0995\u09be\u09b0",  # kar
        "\u0995\u09cb\u09a5\u09be\u09df",  # kothay
        "\u0995\u09c7\u09ae\u09a8",  # kemon
        "\u0995\u09cb\u09a8",  # kon
        "\u0995\u09bf\u09ad\u09be\u09ac\u09c8",  # kibhabe
        "\u0995\u09bf\u09ad\u09be\u09ac\u09c7",  # ki vabe
    }
)


def _is_question_like(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith("?"):
        return True
    return any(token in _INTERROGATIVE_TOKENS for token in tokenize(stripped))


# --- Wave 1: analytics event hygiene ------------------------------------------
# POST /events props are persisted; anything that could smuggle PII (keys
# whose NAME hints at free text or identifiers) is dropped before it can ever
# reach the database, values are primitive-only and strings are truncated.
_EVENT_DROP_KEY_RE = re.compile(
    r"email|name|phone|address|token|code|password|question|message|content|answer",
    re.IGNORECASE,
)

_EVENT_PROP_MAX_LEN = 40


def _sanitize_event_props(props: dict[str, Any]) -> dict[str, Any]:
    """Primitives only, keys matching the drop-list removed, strings <= 40."""
    clean: dict[str, Any] = {}
    for key, value in props.items():
        if _EVENT_DROP_KEY_RE.search(str(key)):
            continue
        if isinstance(value, bool) or isinstance(value, int):
            clean[str(key)[:_EVENT_PROP_MAX_LEN]] = value
        elif isinstance(value, float):
            clean[str(key)[:_EVENT_PROP_MAX_LEN]] = value
        elif isinstance(value, str):
            clean[str(key)[:_EVENT_PROP_MAX_LEN]] = value[:_EVENT_PROP_MAX_LEN]
        # anything non-primitive is dropped entirely
    return clean


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


# --- Wave 2: server-side product analytics -------------------------------------


def _record_analytics(
    db: Session,
    actor_id: int | None,
    actor_role: str | None,
    name: str,
    props: dict[str, Any] | None = None,
) -> None:
    """Queue one sanitized AnalyticsEventRow (same drop-list as POST /events).

    Adds only -- the caller's commit persists it. Props must be code/count
    flavoured; anything PII-shaped is stripped by ``_sanitize_event_props``.
    """
    db.add(
        AnalyticsEventRow(
            user_id=actor_id,
            name=name[:64],
            role=actor_role[:40] if actor_role else None,
            props=_sanitize_event_props(dict(props or {})),
        )
    )


# --- Wave 2: answer confidence ---------------------------------------------------
# Documented formula (0..1, computed at answer finalization, stored nowhere but
# in the payload/schema field):
#
#   refused answer                      -> 0.0
#   no grounding info at all            -> None (unknown, honest)
#   otherwise: clamp01(
#       0.5 * min(1.0, len(source_scores) / 2)        # retrieval breadth
#       + 0.5 * mean(min(1.0, s) for s in scores)     # retrieval depth
#   )
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


# --- Wave 2: chat image (vision) contract ---------------------------------------
_IMAGE_MIME_ALLOWED = frozenset({"image/png", "image/jpeg", "image/webp"})

# Decoded size ceiling (base64 inflates ~4/3, so ~2 MB of JSON on the wire).
_IMAGE_MAX_BYTES = 1_500_000


def _validate_chat_image(image: ChatImageIn | None) -> dict[str, Any] | None:
    """Decode + validate an inline image, returning the provider payload dict
    ``{"mime_type": ..., "data": <raw bytes>}`` or None for text-only turns.

    Every failure -- disallowed mime, undecodable base64, oversize payload --
    is a 422 with detail code ``image_invalid`` (never a partial accept).
    """
    if image is None:
        return None
    mime = image.mime_type.strip().lower()
    if mime not in _IMAGE_MIME_ALLOWED:
        raise HTTPException(
            status_code=422,
            detail={"code": "image_invalid", "message": "Unsupported image mime type"},
        )
    try:
        raw = base64.b64decode(image.data_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "image_invalid", "message": "Image data is not valid base64"},
        ) from exc
    if not raw or len(raw) > _IMAGE_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail={"code": "image_invalid", "message": "Image is empty or exceeds size limit"},
        )
    return {"mime_type": mime, "data": raw}


# --- Wave 2: minimal honest personalization --------------------------------------
# The ONLY personalized blocks the tutor is allowed to receive: which chapters
# the student is demonstrably weak in (from graded attempts) and the requested
# explanation style. Both are gated on the per-student memory opt-out: when
# memory_enabled is False the builder returns "" and the prompt stays exactly
# as impersonal as it was before Wave 2.
EXPLANATION_STYLE_DIRECTIVES: dict[str, str] = {
    "simple": "সবচাইতে সহজ শব্দে ছোট করে বল।",
    "standard": "স্বাভাবিক ধারাবাহিক বিবরণ দাও।",
    "detailed": "প্রয়োজনীয় সব ধাপ ও উদাহরণসহ বিস্তারিত বল।",
}


def build_personalization_block(
    *,
    memory_enabled: bool,
    weak_chapters: list[str],
    explanation_style: str | None,
) -> str:
    """Compose the ``memory:`` line for RequestContext ("" = no personalization)."""
    if not memory_enabled:
        return ""
    parts: list[str] = []
    if weak_chapters:
        parts.append("weak_chapters=" + ",".join(weak_chapters[:3]))
    directive = EXPLANATION_STYLE_DIRECTIVES.get(explanation_style or "")
    if directive:
        parts.append(f"explanation_style={explanation_style}: {directive}")
    return " ".join(parts)


DEFAULT_SCHOOL_CODE = "BGPT-DEFAULT"

SCHOOL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O/0, I/1

_DOC_IN_MODELS: dict[str, Any] = {
    "worksheet": WorksheetIn,
    "answer_key": AnswerKeyIn,
    "homework": HomeworkIn,
    "rubric": RubricIn,
    "lesson_plan": LessonPlanIn,
}

_DOC_LABELS: dict[str, str] = {
    "worksheet": "Worksheet",
    "answer_key": "Answer key",
    "homework": "Homework",
    "rubric": "Rubric",
    "lesson_plan": "Lesson plan",
}


def _student_profile(db: Session, user: User) -> Student:
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "no_student_profile", "message": "Student profile not found"},
        )
    return student


def _request_context(
    db: Session,
    user: User,
    *,
    class_level: int,
    subject: str | None = None,
    chapter: str | None = None,
    goal: str = "question",
    history: list | None = None,
    strategy: str | None = None,
) -> RequestContext:
    """S4.1: the ONE construction point of the education context that
    accompanies every AI call (tutor ask/stream + the three generators).

    Also logs it (event ``ai_request_context``) for eval/cost attribution:
    log_fields carries counts and ids only -- never message content (R11).

    Wave 2 memory opt-out: with ``Student.memory_enabled`` false NEITHER
    the mastery snapshot nor the personalization line is computed, so the
    prompt carries nothing learned about this student (honest, not
    cosmetic -- the derivation itself is skipped).
    """
    mastery: dict[str, float] = {}
    memory_block = ""
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    memory_enabled = student is None or bool(student.memory_enabled)
    if student is not None and memory_enabled:
        # F-PERF-01: DB-side GROUP BY instead of full scan + Python aggregation
        # Intermediate step (O(1) rows instead of O(N)); snapshot projection DEFERRED per docs
        from sqlalchemy import Integer
        from sqlalchemy import cast as _cast

        rows = db.execute(
            select(
                AnswerLog.chapter,
                func.count().label("asked"),
                func.sum(_cast(AnswerLog.is_correct, Integer)).label("correct"),
            )
            .join(QuizAttempt, AnswerLog.attempt_id == QuizAttempt.id)
            .where(QuizAttempt.student_id == student.id)
            .group_by(AnswerLog.chapter)
        ).all()
        stats: dict[str, tuple[int, int]] = {
            chapter: (asked, int(correct or 0)) for chapter, asked, correct in rows
        }
        mastery = snapshot_mastery(
            {c: atrisk.cell_accuracy(asked, correct) for c, (asked, correct) in stats.items()}
        )
        prefs = student.learning_prefs if isinstance(student.learning_prefs, dict) else {}
        style = prefs.get("explanation_style")
        memory_block = build_personalization_block(
            memory_enabled=True,
            weak_chapters=[c for c, acc in mastery.items() if acc < 60.0],
            explanation_style=style if style in EXPLANATION_STYLES else None,
        )
    ctx = RequestContext(
        role=user.role,
        class_level=class_level,
        subject=subject,
        chapter_id=chapter,
        goal=goal,
        history_summary=history_summary(len(history or []), strategy),
        mastery_snapshot=mastery,
        memory_block=memory_block,
    )
    json_log(logger, logging.INFO, "ai_request_context", **ctx.log_fields())
    return ctx


def _load_class_students(
    db: Session,
    class_level: int | None,
    limit: int | None = None,
    school_id: int | None = None,
) -> list[Student]:
    # Wave 2 tenancy: when the caller is bound to a school, only students
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
    # S5.5: one grouped aggregate for the whole roster (was 1 query per
    # student, each pulling every attempt row as a full ORM object).
    # avg() ignores NULL score_pct, matching the previous Python average.
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
        raise HTTPException(status_code=404, detail="classroom not found")
    return room


def _doc_in_for(kind: str, body: dict) -> Any:
    """Validate a raw body against the per-kind input model.

    Unknown kinds raise LookupError and malformed bodies raise
    pydantic.ValidationError; callers map them to HTTP codes (sync) or
    to the failed job state (background)."""
    model = _DOC_IN_MODELS.get(kind)
    if model is None:
        raise LookupError(f"unsupported generator kind: {kind!r}")
    return model.model_validate(body)


async def _generate_document(
    app_ctx: Ctx, db: Session, actor: User, kind: str, gen: Any
) -> tuple[dict, list[SourceRef], str | None]:
    """THE single execution path of the document generators: the sync
    endpoints and the AiJob runner below share it, so a background job
    behaves exactly like the synchronous call."""
    if app_ctx.tutor is None:
        raise ProviderError("provider not configured")
    class_level = int(gen.class_level)
    subject = str(gen.subject)
    chapter: str | None = getattr(gen, "chapter", None)
    questions: list[str] = []
    if kind == "answer_key":
        questions = [q.strip() for q in (gen.questions or []) if q.strip()]
        if gen.paper_id is not None:
            qp = db.get(QuestionPaper, gen.paper_id)
            if qp is None or (qp.teacher_id != actor.id and actor.role != "admin"):
                raise LookupError("question paper not found")
            questions = [
                str(q.get("text", "")).strip()
                for q in qp.questions
                if str(q.get("text", "")).strip()
            ]
            chapter = chapter or (str(qp.chapters[0]) if qp.chapters else None)
        if not questions:
            raise ValueError("answer key needs at least one question")
    ctx = _request_context(
        db,
        actor,
        class_level=class_level,
        subject=subject,
        chapter=chapter,
        # lesson_plan keeps its S2 goal string; the new kinds are prefixed
        goal="lesson_plan" if kind == "lesson_plan" else f"generate_{kind}",
    )
    doc_payload: dict
    sources: list[SourceRef]
    if kind == "worksheet":
        doc_payload, sources = await generate_worksheet(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=class_level,
            subject=subject,
            chapter=str(chapter),
            context=ctx,
        )
    elif kind == "homework":
        doc_payload, sources = await generate_homework(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=class_level,
            subject=subject,
            chapter=str(chapter),
            context=ctx,
        )
    elif kind == "rubric":
        doc_payload, sources = await generate_rubric(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=class_level,
            subject=subject,
            chapter=str(chapter),
            context=ctx,
        )
    elif kind == "answer_key":
        doc_payload, sources = await generate_answer_key(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=class_level,
            subject=subject,
            chapter=chapter,
            questions=questions,
            context=ctx,
        )
        chapter = doc_payload.get("chapter") or chapter
    elif kind == "lesson_plan":
        sections, sources = await generate_lesson_plan(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=class_level,
            subject=subject,
            chapter=str(chapter),
            minutes=int(gen.minutes),
            level=str(gen.level),
            context=ctx,
        )
        doc_payload = {
            "sections": dict(sections),
            "minutes": int(gen.minutes),
            "level": str(gen.level),
        }
    else:
        raise ValueError(f"unsupported generator kind: {kind!r}")
    return doc_payload, sources, chapter


def _document_title(kind: str, subject: str, chapter: str | None, class_level: int) -> str:
    label = _DOC_LABELS.get(kind, kind)
    tail = f" - {chapter}" if chapter else ""
    return f"{label} - {subject} (class {class_level}){tail}"[:200]


def _persist_document(
    db: Session,
    *,
    user_id: int,
    kind: str,
    class_level: int,
    subject: str,
    chapter: str | None,
    payload: dict,
    commit: bool = True,
) -> TeacherDocument:
    # F-DATA-01: caller controls commit boundary; commit once at route/service boundary
    doc = TeacherDocument(
        teacher_id=user_id,
        kind=kind[:20],
        class_level=class_level,
        subject=subject[:60],
        chapter=(chapter or "")[:200] or None,
        title=_document_title(kind, subject, chapter, class_level),
        payload=payload,
    )
    db.add(doc)
    if commit:
        db.commit()
        db.refresh(doc)
    else:
        db.flush()
        db.refresh(doc)
    return doc


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
