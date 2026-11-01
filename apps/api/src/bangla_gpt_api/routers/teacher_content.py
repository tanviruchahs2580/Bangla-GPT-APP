"""Teacher Content Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import asyncio
import json
import logging
import random
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    ChapterContent,
    QuestionPaper,
    TeacherDocument,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded
from bangla_gpt_api.schemas import (
    STANDARD_PAGE_DEFAULT_LIMIT,
    STANDARD_PAGE_MAX_LIMIT,
    TEACHER_DOCUMENT_KINDS,
    TEACHER_DOCUMENT_PDF_KINDS,
    ChapterContentEditIn,
    ChapterContentKey,
    ChapterContentVersionOut,
    ChapterSections,
    GenerateDocumentOut,
    LessonPlanIn,
    LessonPlanOut,
    QPDraftIn,
    QPOut,
    QPQuestion,
    QPReplaceIn,
    QPReviewIn,
    SourceRef,
    TeacherContentOut,
    TeacherDocumentOut,
)
from bangla_gpt_api.security import write_audit
from bangla_gpt_api.services.context import (
    RequestContext,
)
from bangla_gpt_api.services.costs import check_ai_budget, record_ai_usage
from bangla_gpt_api.services.generators import (
    generate_chapter_content,
    generate_question_paper,
)
from bangla_gpt_api.services.qp_pdf import (
    render_document_html,
    render_document_pdf,
    render_qp_html,
    render_qp_pdf,
)
from bangla_gpt_api.services.question_bank import (
    bank_keys,
    dedupe_key,
    find_reusable,
    store_reviewed,
)

from .common import (
    DocumentInputError,
    _doc_in_for,
    _generate_document,
    _persist_document,
    _record_analytics,
    _request_context,
)
from .deps import (
    AIGenerationUser,
    Ctx,
    DbSession,
    TeacherOrAdminUser,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


def _content_next_version(db: Session, subject: str, class_level: int, chapter: str) -> int:
    current = db.execute(
        select(func.max(ChapterContent.version)).where(
            ChapterContent.subject == subject,
            ChapterContent.class_level == class_level,
            ChapterContent.chapter == chapter,
        )
    ).scalar_one_or_none()
    return (current or 0) + 1


def _content_current(
    db: Session, subject: str, class_level: int, chapter: str
) -> ChapterContent | None:
    return db.execute(
        select(ChapterContent)
        .where(
            ChapterContent.subject == subject,
            ChapterContent.class_level == class_level,
            ChapterContent.chapter == chapter,
        )
        .order_by(ChapterContent.version.desc(), ChapterContent.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _assert_content_writable(db: Session, row: ChapterContent, actor: User) -> None:
    """S-007: shared library for READS, school-scoped for WRITES.

    The chapter-content library is deliberately global (every school reads the
    same current version) but the append-only write path had no ownership
    check at all: any teacher could append the new "current" version of
    material another school authored, and every school then read the
    overwrite (proved in the QA audit, ``probe_content_xschool``).

    A write is allowed only when the current version was authored inside the
    actor's own tenancy, matched on ``User.school_id``:

    * same school id -> writable (school-less legacy accounts match
      school-less authors, preserving pre-school-layer behaviour);
    * another school -> 403 ``content_read_only``;
    * author deleted or ``created_by`` NULL (platform/system seed) -> 403,
      because there is no tenancy to match;
    * admins keep platform-wide write access, like every other admin surface.
    """
    if actor.role == "admin":
        return
    if row.created_by is not None:
        author = db.get(User, row.created_by)
        if author is not None and author.school_id == actor.school_id:
            return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "content_read_only",
            "message": "This chapter content was authored by another school and is read-only",
        },
    )


def _content_out(row: ChapterContent, sources: list[SourceRef] | None = None) -> TeacherContentOut:
    return TeacherContentOut(
        class_level=row.class_level,
        subject=row.subject,
        chapter=row.chapter,
        version=row.version,
        source=row.source,
        sections=ChapterSections.model_validate(row.payload),
        sources=sources or [],
    )


def _content_generate_prepare(
    db: Session, payload: ChapterContentKey, teacher: User
) -> RequestContext:
    """DB prelude to content generation (tenancy check + context), run in a
    worker thread so the event loop stays free while the provider streams."""
    # S-007: generating when content already exists appends the new "current"
    # version, i.e. it is a write like PUT. Refuse it across the tenancy wall
    # BEFORE spending the provider call.
    current = _content_current(db, payload.subject, payload.class_level, payload.chapter)
    if current is not None:
        _assert_content_writable(db, current, teacher)
    return _request_context(
        db,
        teacher,
        class_level=payload.class_level,
        subject=payload.subject,
        chapter=payload.chapter,
        goal="chapter_content",
    )


def _content_generate_persist(
    db: Session, payload: ChapterContentKey, teacher: User, sections: dict
) -> ChapterContent:
    """DB postlude: versioned insert with the concurrent-slot retry."""
    version = _content_next_version(db, payload.subject, payload.class_level, payload.chapter)
    row = ChapterContent(
        subject=payload.subject,
        class_level=payload.class_level,
        chapter=payload.chapter,
        version=version,
        source="ai",
        payload=sections,
        created_by=teacher.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent generation for the same chapter: take the next slot.
        db.rollback()
        row.version = _content_next_version(
            db, payload.subject, payload.class_level, payload.chapter
        )
        db.add(row)
        db.commit()
    db.refresh(row)
    return row


@router.post(
    "/teacher/content/generate",
    response_model=TeacherContentOut,
    responses=coded(403),
)
async def teacher_content_generate(
    app_ctx: Ctx, payload: ChapterContentKey, db: DbSession, teacher: AIGenerationUser
) -> TeacherContentOut:
    """one retrieval + one AI call fills all seven sections."""
    if app_ctx.tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_unconfigured", "message": "provider not configured"},
        )
    ctx = await asyncio.to_thread(_content_generate_prepare, db, payload, teacher)
    try:
        sections, sources = await generate_chapter_content(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=payload.class_level,
            subject=payload.subject,
            chapter=payload.chapter,
            context=ctx,
        )
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_unavailable", "message": "content generation failed"},
        ) from exc
    row = await asyncio.to_thread(_content_generate_persist, db, payload, teacher, sections)
    return _content_out(row, sources)


@router.get("/teacher/content/history", response_model=list[ChapterContentVersionOut])
def teacher_content_history(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    class_level: int,
    subject: str,
    chapter: str,
) -> list[ChapterContentVersionOut]:
    rows = (
        db.execute(
            select(ChapterContent)
            .where(
                ChapterContent.subject == subject,
                ChapterContent.class_level == class_level,
                ChapterContent.chapter == chapter,
            )
            .order_by(ChapterContent.version.desc(), ChapterContent.id.desc())
        )
        .scalars()
        .all()
    )
    return [
        ChapterContentVersionOut(
            class_level=r.class_level,
            subject=r.subject,
            chapter=r.chapter,
            version=r.version,
            source=r.source,
            created_at=r.created_at,
            created_by=r.created_by,
        )
        for r in rows
    ]


@router.get("/teacher/content", response_model=TeacherContentOut)
def teacher_content_get(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    class_level: int,
    subject: str,
    chapter: str,
) -> TeacherContentOut:
    row = _content_current(db, subject, class_level, chapter)
    if row is None:
        raise HTTPException(
            status_code=404, detail={"code": "content_not_found", "message": "content not found"}
        )
    return _content_out(row)


@router.put("/teacher/content", response_model=TeacherContentOut, responses=coded(403))
def teacher_content_edit(
    payload: ChapterContentEditIn, db: DbSession, teacher: TeacherOrAdminUser
) -> TeacherContentOut:
    """teacher edits append a new version (append-only chain).

    S-007: the teacher must own the tenancy the current version was authored
    in; content authored by another school (or seeded by the platform) is
    read-only for them (403 ``content_read_only``) even though it stays
    readable for every school.
    """
    current = _content_current(db, payload.subject, payload.class_level, payload.chapter)
    if current is None:
        raise HTTPException(
            status_code=404, detail={"code": "content_not_found", "message": "content not found"}
        )
    _assert_content_writable(db, current, teacher)
    row = ChapterContent(
        subject=payload.subject,
        class_level=payload.class_level,
        chapter=payload.chapter,
        version=_content_next_version(db, payload.subject, payload.class_level, payload.chapter),
        source="teacher",
        payload=payload.sections.model_dump(),
        created_by=teacher.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _content_out(row)


# --- question papers (AI draft -> teacher review -> FINAL) --------


def _qp_or_404(db: Session, qp_id: int, teacher: User) -> QuestionPaper:
    qp = db.get(QuestionPaper, qp_id)
    if qp is None or (qp.teacher_id != teacher.id and teacher.role != "admin"):
        raise HTTPException(
            status_code=404,
            detail={"code": "qpaper_not_found", "message": "question paper not found"},
        )
    return qp


def _qp_out(qp: QuestionPaper) -> QPOut:
    return QPOut(
        id=qp.id,
        class_level=qp.class_level,
        subject=qp.subject,
        exam_type=qp.exam_type,
        marks=qp.marks,
        duration_min=qp.duration_min,
        difficulty=dict(qp.difficulty),
        chapters=list(qp.chapters),
        status=qp.status,
        questions=[QPQuestion.model_validate(q) for q in qp.questions],
        meta=dict(qp.meta or {}),
        reviewed_at=qp.reviewed_at,
        finalized_at=qp.finalized_at,
        created_at=qp.created_at,
    )


async def _qp_fresh_draft(
    app_ctx: Ctx,
    db: Session,
    actor: User,
    class_level: int,
    subject: str,
    chapters: list[str],
    marks: int,
    difficulty: dict[str, int],
    context: RequestContext | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """One question-paper generation, with the per-user AI budget enforced and
    the spend ledgered (SEC-002).

    Drafting, regenerating and replacing a single question all reach the
    provider through here, so this is the one place that has to know about the
    budget; keeping it in the handlers is how the setting came to be documented
    but never applied to teachers.
    """
    if app_ctx.tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_unconfigured", "message": "provider not configured"},
        )
    await asyncio.to_thread(check_ai_budget, db, user_id=actor.id, settings=app_ctx.settings)
    try:
        questions, meta = await generate_question_paper(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=class_level,
            subject=subject,
            chapters=chapters,
            marks=marks,
            difficulty_pct=difficulty,
            context=context,
        )
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_unavailable", "message": "question paper generation failed"},
        ) from exc
    # Adds only; the caller's commit persists the ledger row with the paper.
    await asyncio.to_thread(
        record_ai_usage,
        db,
        user_id=actor.id,
        route="teacher/question_paper",
        model=getattr(app_ctx.provider, "name", None),
        prompt_text=f"{subject} {','.join(chapters)} class {class_level} {marks} marks",
        answer_text=json.dumps(questions, ensure_ascii=False, default=str),
    )
    return questions, meta


def _qp_persist_draft(
    db: Session,
    teacher: User,
    payload: QPDraftIn,
    difficulty: dict[str, int],
    questions: list[dict[str, object]],
    meta: dict[str, object],
    elapsed_ms: int,
) -> QuestionPaper:
    """DB postlude of a fresh draft: reuse metric, insert, commit, log."""
    # reuse metric: how much of the fresh draft is already banked?
    keys = bank_keys(db, class_level=payload.class_level)
    bank_matches = sum(1 for q in questions if dedupe_key(str(q["text"])) in keys)
    qp = QuestionPaper(
        teacher_id=teacher.id,
        class_level=payload.class_level,
        subject=payload.subject,
        exam_type=payload.exam_type,
        marks=payload.marks,
        duration_min=payload.duration_min,
        difficulty=difficulty,
        chapters=payload.chapters,
        status="draft",
        questions=questions,
        meta=meta,
    )
    db.add(qp)
    db.commit()
    db.refresh(qp)
    json_log(
        logger,
        logging.INFO,
        "qp_draft",
        qp_id=qp.id,
        teacher_id=teacher.id,
        question_count=len(questions),
        elapsed_ms=elapsed_ms,
        # reuse metric: drafted questions already reviewed & banked.
        bank_size=len(keys),
        bank_matches=bank_matches,
        reuse_pct=round(100 * bank_matches / len(questions)) if questions else 0,
    )
    return qp


@router.post("/teacher/qpapers", response_model=QPOut, status_code=201)
async def teacher_qp_create(
    app_ctx: Ctx, payload: QPDraftIn, db: DbSession, teacher: AIGenerationUser
) -> QPOut:
    """Draft = one retrieval + one AI call behind three validation gates."""
    difficulty = payload.difficulty.model_dump()
    started = time.perf_counter()
    ctx = await asyncio.to_thread(
        _request_context,
        db,
        teacher,
        class_level=payload.class_level,
        subject=payload.subject,
        chapter=",".join(payload.chapters),
        goal="question_paper",
    )
    questions, meta = await _qp_fresh_draft(
        app_ctx,
        db,
        teacher,
        payload.class_level,
        payload.subject,
        payload.chapters,
        payload.marks,
        difficulty,
        context=ctx,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    qp = await asyncio.to_thread(
        _qp_persist_draft, db, teacher, payload, difficulty, questions, meta, elapsed_ms
    )
    return _qp_out(qp)


@router.get("/teacher/qpapers", response_model=list[QPOut])
def teacher_qp_list(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    limit: Annotated[int, Query(ge=1, le=STANDARD_PAGE_MAX_LIMIT)] = STANDARD_PAGE_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[QPOut]:
    # newest-first page; QPOut carries the full questions JSON, so
    # unbounded was the largest payload-per-request risk here.
    rows = (
        db.execute(
            select(QuestionPaper)
            .where(QuestionPaper.teacher_id == teacher.id)
            .order_by(QuestionPaper.created_at.desc(), QuestionPaper.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_qp_out(row) for row in rows]


@router.get("/teacher/qpapers/{qp_id}", response_model=QPOut)
def teacher_qp_get(qp_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> QPOut:
    return _qp_out(_qp_or_404(db, qp_id, teacher))


def _qp_editable(qp: QuestionPaper) -> None:
    if qp.status == "final":
        raise HTTPException(
            status_code=409,
            detail={"code": "paper_finalised", "message": "paper is already finalised"},
        )


@router.post("/teacher/qpapers/{qp_id}/regenerate", response_model=QPOut)
async def teacher_qp_regenerate(
    app_ctx: Ctx, qp_id: int, db: DbSession, teacher: AIGenerationUser
) -> QPOut:
    """New AI draft under the same spec; review flags reset."""

    def _load() -> tuple[QuestionPaper, RequestContext]:
        qp = _qp_or_404(db, qp_id, teacher)
        _qp_editable(qp)
        ctx = _request_context(
            db,
            teacher,
            class_level=qp.class_level,
            subject=qp.subject,
            chapter=",".join(str(c) for c in qp.chapters),
            goal="question_paper",
        )
        return qp, ctx

    def _persist(qp: QuestionPaper, questions: list[dict[str, object]], meta: dict[str, object]):
        qp.questions = questions
        qp.meta = meta
        qp.reviewed_at = None
        db.commit()
        db.refresh(qp)
        json_log(
            logger,
            logging.INFO,
            "qp_regenerate",
            qp_id=qp.id,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    qp, ctx = await asyncio.to_thread(_load)
    started = time.perf_counter()
    questions, meta = await _qp_fresh_draft(
        app_ctx,
        db,
        teacher,
        qp.class_level,
        qp.subject,
        list(qp.chapters),
        qp.marks,
        dict(qp.difficulty),
        context=ctx,
    )
    await asyncio.to_thread(_persist, qp, questions, meta)
    return _qp_out(qp)


@router.post("/teacher/qpapers/{qp_id}/shuffle", response_model=QPOut)
def teacher_qp_shuffle(qp_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> QPOut:
    """Reorder questions; review flags reset because positions changed."""
    qp = _qp_or_404(db, qp_id, teacher)
    _qp_editable(qp)
    questions = [dict(q) for q in qp.questions]
    if len(questions) > 1:
        identity = list(range(len(questions)))
        order = identity.copy()
        random.shuffle(order)
        while order == identity:
            random.shuffle(order)
        questions = [questions[i] for i in order]
    for q in questions:
        q["reviewed"] = False
    qp.questions = questions
    qp.reviewed_at = None
    db.commit()
    db.refresh(qp)
    return _qp_out(qp)


@router.post("/teacher/qpapers/{qp_id}/review", response_model=QPOut)
def teacher_qp_review(
    qp_id: int, payload: QPReviewIn, db: DbSession, teacher: TeacherOrAdminUser
) -> QPOut:
    """Accept/edit per question; reviewed_at lands once ALL are reviewed."""
    qp = _qp_or_404(db, qp_id, teacher)
    _qp_editable(qp)
    questions = [dict(q) for q in qp.questions]
    by_ref = {str(q["ref"]): q for q in questions}
    for decision in payload.decisions:
        question = by_ref.get(decision.ref)
        if question is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unknown_question_ref",
                    "message": f"unknown question ref: {decision.ref}",
                },
            )
        if decision.action == "edit":
            question["text"] = decision.text
            if decision.options is not None:
                question["options"] = list(decision.options)
            if decision.answer_index is not None:
                question["answer_index"] = decision.answer_index
        question["reviewed"] = True
    # every reviewed question enters the bank (deduped by content).
    bank_added = 0
    for question in questions:
        if not bool(question.get("reviewed")):
            continue
        answer_index_raw = question.get("answer_index")
        _row, created = store_reviewed(
            db,
            teacher_id=teacher.id,
            text=str(question["text"]),
            options=[str(o) for o in question.get("options", [])],
            answer_index=(int(answer_index_raw) if isinstance(answer_index_raw, int) else None),
            subject=qp.subject,
            chapter=str(question.get("chapter", "")),
            class_level=qp.class_level,
        )
        bank_added += 1 if created else 0
    qp.questions = questions
    if all(bool(q.get("reviewed")) for q in questions):
        qp.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(qp)
    json_log(
        logger,
        logging.INFO,
        "question_bank_reviewed",
        qp_id=qp.id,
        bank_added=bank_added,
        bank_total=sum(1 for q in questions if bool(q.get("reviewed"))),
    )
    return _qp_out(qp)


def _load_replace_target(
    db: Session, qp_id: int, teacher: User, ref: str
) -> tuple[QuestionPaper, list[dict[str, Any]], dict[str, Any], str, str]:
    """Load the editable paper and the question a swap targets."""
    qp = _qp_or_404(db, qp_id, teacher)
    _qp_editable(qp)
    questions = [dict(q) for q in qp.questions]
    target = next((q for q in questions if str(q["ref"]) == ref), None)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "unknown_question_ref", "message": f"unknown question ref: {ref}"},
        )
    return (qp, questions, target, str(target["difficulty"]), str(target["chapter"]))


def _bank_replacement(
    db: Session,
    qp: QuestionPaper,
    teacher: User,
    target: dict[str, Any],
    label: str,
    chapter: str,
) -> dict[str, Any] | None:
    """A reviewed bank question that fits, or None when only AI can serve.

    Reuse first: an MCQ-complete reviewed row not already on the paper.
    """
    for row in find_reusable(
        db,
        class_level=qp.class_level,
        school_id=teacher.school_id,
        include_all_schools=teacher.role == "admin",
        subject=qp.subject,
        chapter=chapter,
        exclude_texts=[str(q["text"]) for q in qp.questions],
        limit=8,
    ):
        idx = row.answer_index
        if len(row.options) != 4 or not isinstance(idx, int) or isinstance(idx, bool):
            continue
        if not 0 <= idx <= 3:
            continue
        row.times_reused += 1
        return {
            "ref": str(target["ref"]),
            "text": row.question_text,
            "options": [str(o) for o in row.options],
            "answer_index": idx,
            "marks": int(target["marks"]),
            "difficulty": label,
            "chapter": chapter,
            "reviewed": False,
        }
    return None


def _pick_fresh_candidate(
    fresh: list[dict[str, Any]], questions: list[dict[str, Any]], label: str, chapter: str
) -> dict[str, Any] | None:
    """First fresh draft not already on the paper, preferring label+chapter."""
    used = {str(q["text"]) for q in questions}
    usable = [q for q in fresh if str(q["text"]) not in used]
    candidates = (
        [q for q in usable if str(q["difficulty"]) == label and str(q["chapter"]) == chapter]
        or [q for q in usable if str(q["chapter"]) == chapter]
        or usable
    )
    return candidates[0] if candidates else None


def _persist_replacement(
    db: Session,
    qp: QuestionPaper,
    questions: list[dict[str, Any]],
    target: dict[str, Any],
    replacement: dict[str, Any],
    *,
    source: str,
    ref: str,
    started: float,
) -> None:
    if source == "ai":
        replacement["ref"] = str(target["ref"])
        replacement["difficulty"] = str(target["difficulty"])
        replacement["chapter"] = str(target["chapter"])
        replacement["reviewed"] = False
    questions[questions.index(target)] = replacement
    qp.questions = questions
    qp.reviewed_at = None
    db.commit()
    db.refresh(qp)
    json_log(
        logger,
        logging.INFO,
        "qp_replace",
        qp_id=qp.id,
        ref=ref,
        reuse_source=source,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


@router.post("/teacher/qpapers/{qp_id}/replace", response_model=QPOut)
async def teacher_qp_replace(
    app_ctx: Ctx, qp_id: int, payload: QPReplaceIn, db: DbSession, teacher: AIGenerationUser
) -> QPOut:
    """Swap ONE question for a freshly generated one; still needs review."""
    qp, questions, target, label, chapter = await asyncio.to_thread(
        _load_replace_target, db, qp_id, teacher, payload.ref
    )
    # An explicit payload override wins over the target's own label/chapter.
    label = payload.difficulty or label
    chapter = payload.chapter or chapter
    started = time.perf_counter()
    replacement = await asyncio.to_thread(
        _bank_replacement, db, qp, teacher, target, label, chapter
    )
    source = "bank" if replacement is not None else "ai"
    if replacement is None:
        ctx = await asyncio.to_thread(
            _request_context,
            db,
            teacher,
            class_level=qp.class_level,
            subject=qp.subject,
            chapter=chapter,
            goal="question_paper_replace",
        )
        fresh, _meta = await _qp_fresh_draft(
            app_ctx,
            db,
            teacher,
            qp.class_level,
            qp.subject,
            list(qp.chapters),
            qp.marks,
            dict(qp.difficulty),
            context=ctx,
        )
        replacement = _pick_fresh_candidate(fresh, questions, label, chapter)
    if replacement is None:
        raise HTTPException(
            status_code=502,
            detail={"code": "no_replacement", "message": "no distinct replacement question"},
        )
    await asyncio.to_thread(
        _persist_replacement,
        db,
        qp,
        questions,
        target,
        replacement,
        source=source,
        ref=payload.ref,
        started=started,
    )
    return _qp_out(qp)


@router.post("/teacher/qpapers/{qp_id}/finalize", response_model=QPOut)
def teacher_qp_finalize(qp_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> QPOut:
    """FINAL is an explicit teacher action, blocked until every question reviewed."""
    qp = _qp_or_404(db, qp_id, teacher)
    if qp.status == "final":
        raise HTTPException(
            status_code=409, detail={"code": "paper_finalised", "message": "already finalised"}
        )
    unreviewed = [str(q["ref"]) for q in qp.questions if not q.get("reviewed")]
    if unreviewed:
        raise HTTPException(
            status_code=409,
            detail={"code": "review_required", "unreviewed": unreviewed},
        )
    qp.status = "final"
    qp.finalized_at = datetime.now(UTC).replace(tzinfo=None)
    # audit event 4/5: qp_finalize (exam-paper finalisation is
    # irreversible for the teacher; ids only in the trail)
    write_audit(
        db,
        action="qp_finalize",
        actor_user_id=teacher.id,
        actor_role=teacher.role,
        target=f"qp:{qp.id}",
        detail={"class_level": qp.class_level, "subject": qp.subject},
    )
    db.commit()
    db.refresh(qp)
    return _qp_out(qp)


@router.get("/teacher/qpapers/{qp_id}/pdf")
def teacher_qp_pdf(
    qp_id: int, db: DbSession, teacher: TeacherOrAdminUser, kind: str = "paper"
) -> Response:
    if kind not in ("paper", "answer"):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_kind", "message": "kind must be paper or answer"},
        )
    qp = _qp_or_404(db, qp_id, teacher)
    paper = {
        "exam_type": qp.exam_type,
        "class_level": qp.class_level,
        "subject": qp.subject,
        "marks": qp.marks,
        "duration_min": qp.duration_min,
        "chapters": list(qp.chapters),
        "questions": [dict(q) for q in qp.questions],
    }
    try:
        data = render_qp_pdf(paper, kind)
    except Exception:  # shaping libs unavailable -> HTML print view fallback
        return HTMLResponse(render_qp_html(paper, kind))
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="qp-{qp.id}-{kind}.pdf"'},
    )


# --- lesson plan copilot (8 sections, editable + printable) ---------


@router.post("/teacher/lesson-plans", response_model=LessonPlanOut)
async def teacher_lesson_plan(
    app_ctx: Ctx, payload: LessonPlanIn, db: DbSession, teacher: AIGenerationUser
) -> LessonPlanOut:
    """one retrieval + one AI call drafts an eight-section plan.

    the plan is now ALSO persisted as a TeacherDocument
    (kind=lesson_plan) through the shared generator runner, and the
    response gains the additive ``document_id`` only -- every previously
    existing field keeps its exact shape.
    """
    if app_ctx.tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_unconfigured", "message": "provider not configured"},
        )
    started = time.perf_counter()
    try:
        doc_payload, sources, _chapter = await _generate_document(
            app_ctx, db, teacher, "lesson_plan", payload
        )
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_unavailable", "message": "lesson plan generation failed"},
        ) from exc
    doc = await asyncio.to_thread(
        _persist_document,
        db,
        user_id=teacher.id,
        kind="lesson_plan",
        class_level=payload.class_level,
        subject=payload.subject,
        chapter=payload.chapter,
        payload=doc_payload,
    )
    json_log(
        logger,
        logging.INFO,
        "lesson_plan",
        teacher_id=teacher.id,
        class_level=payload.class_level,
        subject=payload.subject,
        plan_level=payload.level,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    return LessonPlanOut(
        sections=dict(doc_payload["sections"]),
        sources=sources,
        class_level=payload.class_level,
        subject=payload.subject,
        chapter=payload.chapter,
        minutes=payload.minutes,
        level=payload.level,
        document_id=doc.id,
    )


# --- generic document generators + document library ---------------


def _document_or_404(db: Session, document_id: int, actor: User) -> TeacherDocument:
    doc = db.get(TeacherDocument, document_id)
    if doc is None or (doc.teacher_id != actor.id and actor.role != "admin"):
        raise HTTPException(
            status_code=404, detail={"code": "document_not_found", "message": "document not found"}
        )
    return doc


def _document_out(doc: TeacherDocument) -> TeacherDocumentOut:
    return TeacherDocumentOut(
        id=doc.id,
        kind=doc.kind,
        class_level=doc.class_level,
        subject=doc.subject,
        chapter=doc.chapter,
        title=doc.title,
        payload=dict(doc.payload or {}),
        created_at=doc.created_at,
    )


@router.post("/teacher/generate/{kind}", response_model=GenerateDocumentOut, status_code=201)
async def teacher_generate_document(
    app_ctx: Ctx, kind: str, body: dict, db: DbSession, teacher: AIGenerationUser
) -> GenerateDocumentOut:
    """One endpoint, four generators: worksheet | answer_key | homework |
    rubric. The persisted TeacherDocument is returned with the cited
    sources (answer_key takes {paper_id} OR {questions})."""
    if kind not in TEACHER_DOCUMENT_KINDS:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_kind", "message": "unknown generator kind"}
        )
    if app_ctx.tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_unconfigured", "message": "provider not configured"},
        )
    try:
        gen_in = _doc_in_for(kind, body)
    except ValidationError as exc:
        # Coded 422 like every other rejection (F-074): the pydantic error
        # list leaked the internal validation shape and was the last list-
        # shaped detail in routers/. Field locations are logged, not echoed.
        json_log(
            logger,
            logging.INFO,
            "teacher_document_payload_invalid",
            kind=kind,
            fields=[str(e["loc"][0]) if e["loc"] else "?" for e in exc.errors()[:5]],
        )
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_payload", "message": f"invalid {kind} payload"},
        ) from exc
    started = time.perf_counter()
    try:
        doc_payload, sources, chapter = await _generate_document(app_ctx, db, teacher, kind, gen_in)
    except DocumentInputError as exc:
        # status/code/message are authored for the client in common.py; no
        # str(exc) of an arbitrary exception reaches the body (F-074).
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_unavailable", "message": f"{kind} generation failed"},
        ) from exc

    def _finalize(doc_payload: dict, chapter: str | None) -> TeacherDocument:
        doc = _persist_document(
            db,
            user_id=teacher.id,
            kind=kind,
            class_level=gen_in.class_level,
            subject=gen_in.subject,
            chapter=chapter,
            payload=doc_payload,
        )
        json_log(
            logger,
            logging.INFO,
            "teacher_document_generated",
            teacher_id=teacher.id,
            document_id=doc.id,
            kind=kind,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        # server-side product analytics (kind + id only, no PII).
        _record_analytics(
            db,
            teacher.id,
            teacher.role,
            "teacher_document_generated",
            {"kind": kind, "document_id": doc.id},
        )
        db.commit()
        return doc

    doc = await asyncio.to_thread(_finalize, doc_payload, chapter)
    return GenerateDocumentOut(
        id=doc.id,
        kind=doc.kind,
        class_level=doc.class_level,
        subject=doc.subject,
        chapter=doc.chapter,
        title=doc.title,
        payload=dict(doc.payload or {}),
        created_at=doc.created_at,
        sources=sources,
    )


@router.get("/teacher/documents", response_model=list[TeacherDocumentOut])
def teacher_documents_list(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=STANDARD_PAGE_MAX_LIMIT)] = STANDARD_PAGE_DEFAULT_LIMIT,
) -> list[TeacherDocumentOut]:
    """Own library, newest first; optional kind filter (includes the
    lesson_plan kind persisted by POST /teacher/lesson-plans)."""
    allowed = (*TEACHER_DOCUMENT_KINDS, "lesson_plan")
    if kind is not None and kind not in allowed:
        raise HTTPException(
            status_code=422, detail={"code": "unknown_kind", "message": "unknown document kind"}
        )
    q = select(TeacherDocument).where(TeacherDocument.teacher_id == teacher.id)
    if kind is not None:
        q = q.where(TeacherDocument.kind == kind)
    rows = (
        db.execute(
            q.order_by(TeacherDocument.created_at.desc(), TeacherDocument.id.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [_document_out(r) for r in rows]


@router.get("/teacher/documents/{document_id}", response_model=TeacherDocumentOut)
def teacher_document_get(
    document_id: int, db: DbSession, teacher: TeacherOrAdminUser
) -> TeacherDocumentOut:
    return _document_out(_document_or_404(db, document_id, teacher))


@router.delete("/teacher/documents/{document_id}", status_code=204)
def teacher_document_delete(
    document_id: int, db: DbSession, teacher: TeacherOrAdminUser
) -> Response:
    # Deletion is strictly own-only (admins included).
    doc = db.get(TeacherDocument, document_id)
    if doc is None or doc.teacher_id != teacher.id:
        raise HTTPException(
            status_code=404, detail={"code": "document_not_found", "message": "document not found"}
        )
    db.delete(doc)
    db.commit()
    return Response(status_code=204)


@router.get("/teacher/documents/{document_id}/pdf")
def teacher_document_pdf(document_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> Response:
    doc = _document_or_404(db, document_id, teacher)
    if doc.kind not in TEACHER_DOCUMENT_PDF_KINDS:
        raise HTTPException(
            status_code=400,
            detail={"code": "pdf_unsupported", "message": "no PDF export for this document kind"},
        )
    doc_dict = {
        "kind": doc.kind,
        "title": doc.title,
        "class_level": doc.class_level,
        "subject": doc.subject,
        "chapter": doc.chapter,
        "payload": dict(doc.payload or {}),
    }
    try:
        data = render_document_pdf(doc_dict)
    except Exception:  # shaping libs/font unavailable -> HTML print view
        return HTMLResponse(render_document_html(doc_dict))
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="document-{doc.id}-{doc.kind}.pdf"'},
    )


# --- saved notes ----------------------------------------------------
