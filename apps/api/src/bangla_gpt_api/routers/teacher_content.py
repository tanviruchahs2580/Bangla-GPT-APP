"""Teacher Content Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import logging
import random
import time
from datetime import UTC, datetime
from typing import Annotated

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
from bangla_gpt_api.schemas import (
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
    _doc_in_for,
    _generate_document,
    _persist_document,
    _record_analytics,
    _request_context,
)
from .deps import (
    Ctx,
    DbSession,
    TeacherOrAdminUser,
)

router = APIRouter()

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
        .order_by(ChapterContent.version.desc())
        .limit(1)
    ).scalar_one_or_none()


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


@router.post("/teacher/content/generate", response_model=TeacherContentOut)
async def teacher_content_generate(
    app_ctx: Ctx, payload: ChapterContentKey, db: DbSession, teacher: TeacherOrAdminUser
) -> TeacherContentOut:
    """S2.3: one retrieval + one AI call fills all seven sections."""
    if app_ctx.tutor is None:
        raise HTTPException(status_code=503, detail="provider not configured")
    try:
        sections, sources = await generate_chapter_content(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=payload.class_level,
            subject=payload.subject,
            chapter=payload.chapter,
            context=_request_context(
                db,
                teacher,
                class_level=payload.class_level,
                subject=payload.subject,
                chapter=payload.chapter,
                goal="chapter_content",
            ),
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail="content generation failed") from exc
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
            .order_by(ChapterContent.version.desc())
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
        raise HTTPException(status_code=404, detail="content not found")
    return _content_out(row)


@router.put("/teacher/content", response_model=TeacherContentOut)
def teacher_content_edit(
    payload: ChapterContentEditIn, db: DbSession, teacher: TeacherOrAdminUser
) -> TeacherContentOut:
    """S2.3: teacher edits append a new version (append-only chain)."""
    if _content_current(db, payload.subject, payload.class_level, payload.chapter) is None:
        raise HTTPException(status_code=404, detail="content not found")
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


# --- S2.4: question papers (AI draft -> teacher review -> FINAL) --------


def _qp_or_404(db: Session, qp_id: int, teacher: User) -> QuestionPaper:
    qp = db.get(QuestionPaper, qp_id)
    if qp is None or (qp.teacher_id != teacher.id and teacher.role != "admin"):
        raise HTTPException(status_code=404, detail="question paper not found")
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
    class_level: int,
    subject: str,
    chapters: list[str],
    marks: int,
    difficulty: dict[str, int],
    context: RequestContext | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if app_ctx.tutor is None:
        raise HTTPException(status_code=503, detail="provider not configured")
    try:
        return await generate_question_paper(
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
        raise HTTPException(status_code=502, detail="question paper generation failed") from exc


@router.post("/teacher/qpapers", response_model=QPOut, status_code=201)
async def teacher_qp_create(
    app_ctx: Ctx, payload: QPDraftIn, db: DbSession, teacher: TeacherOrAdminUser
) -> QPOut:
    """Draft = one retrieval + one AI call behind three validation gates."""
    difficulty = payload.difficulty.model_dump()
    started = time.perf_counter()
    questions, meta = await _qp_fresh_draft(
        app_ctx,
        payload.class_level,
        payload.subject,
        payload.chapters,
        payload.marks,
        difficulty,
        context=_request_context(
            db,
            teacher,
            class_level=payload.class_level,
            subject=payload.subject,
            chapter=",".join(payload.chapters),
            goal="question_paper",
        ),
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # S2.9 reuse metric: how much of the fresh draft is already banked?
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
        # S2.9 reuse metric: drafted questions already reviewed & banked.
        bank_size=len(keys),
        bank_matches=bank_matches,
        reuse_pct=round(100 * bank_matches / len(questions)) if questions else 0,
    )
    return _qp_out(qp)


@router.get("/teacher/qpapers", response_model=list[QPOut])
def teacher_qp_list(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[QPOut]:
    # S5.5: newest-first page; QPOut carries the full questions JSON, so
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
        raise HTTPException(status_code=409, detail="paper is already finalised")


@router.post("/teacher/qpapers/{qp_id}/regenerate", response_model=QPOut)
async def teacher_qp_regenerate(
    app_ctx: Ctx, qp_id: int, db: DbSession, teacher: TeacherOrAdminUser
) -> QPOut:
    """New AI draft under the same spec; review flags reset."""
    qp = _qp_or_404(db, qp_id, teacher)
    _qp_editable(qp)
    started = time.perf_counter()
    questions, meta = await _qp_fresh_draft(
        app_ctx,
        qp.class_level,
        qp.subject,
        list(qp.chapters),
        qp.marks,
        dict(qp.difficulty),
        context=_request_context(
            db,
            teacher,
            class_level=qp.class_level,
            subject=qp.subject,
            chapter=",".join(str(c) for c in qp.chapters),
            goal="question_paper",
        ),
    )
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
            raise HTTPException(status_code=400, detail=f"unknown question ref: {decision.ref}")
        if decision.action == "edit":
            question["text"] = decision.text
            if decision.options is not None:
                question["options"] = list(decision.options)
            if decision.answer_index is not None:
                question["answer_index"] = decision.answer_index
        question["reviewed"] = True
    # S2.9: every reviewed question enters the bank (deduped by content).
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


@router.post("/teacher/qpapers/{qp_id}/replace", response_model=QPOut)
async def teacher_qp_replace(
    app_ctx: Ctx, qp_id: int, payload: QPReplaceIn, db: DbSession, teacher: TeacherOrAdminUser
) -> QPOut:
    """Swap ONE question for a freshly generated one; still needs review."""
    qp = _qp_or_404(db, qp_id, teacher)
    _qp_editable(qp)
    questions = [dict(q) for q in qp.questions]
    target = next((q for q in questions if str(q["ref"]) == payload.ref), None)
    if target is None:
        raise HTTPException(status_code=400, detail=f"unknown question ref: {payload.ref}")
    label = payload.difficulty or str(target["difficulty"])
    chapter = payload.chapter or str(target["chapter"])
    started = time.perf_counter()
    reuse_source = "ai"
    # S2.9: reuse a reviewed bank question when one fits (MCQ-complete,
    # not already on the paper); the AI draft path stays the fallback.
    replacement: dict[str, object] | None = None
    for row in find_reusable(
        db,
        class_level=qp.class_level,
        subject=qp.subject,
        chapter=chapter,
        exclude_texts=[str(q["text"]) for q in questions],
        limit=8,
    ):
        idx = row.answer_index
        if len(row.options) != 4 or not isinstance(idx, int) or isinstance(idx, bool):
            continue
        if not 0 <= idx <= 3:
            continue
        row.times_reused += 1
        replacement = {
            "ref": str(target["ref"]),
            "text": row.question_text,
            "options": [str(o) for o in row.options],
            "answer_index": idx,
            "marks": int(target["marks"]),
            "difficulty": label,
            "chapter": chapter,
            "reviewed": False,
        }
        reuse_source = "bank"
        break
    if replacement is None:
        fresh, _meta = await _qp_fresh_draft(
            app_ctx,
            qp.class_level,
            qp.subject,
            list(qp.chapters),
            qp.marks,
            dict(qp.difficulty),
            context=_request_context(
                db,
                teacher,
                class_level=qp.class_level,
                subject=qp.subject,
                chapter=chapter,
                goal="question_paper_replace",
            ),
        )
        used = {str(q["text"]) for q in questions}
        candidates = (
            [
                q
                for q in fresh
                if str(q["text"]) not in used
                and str(q["difficulty"]) == label
                and str(q["chapter"]) == chapter
            ]
            or [q for q in fresh if str(q["text"]) not in used and str(q["chapter"]) == chapter]
            or [q for q in fresh if str(q["text"]) not in used]
        )
        replacement = candidates[0] if candidates else None
    if replacement is None:
        raise HTTPException(status_code=502, detail="no distinct replacement question")
    if reuse_source == "ai":
        replacement["ref"] = str(target["ref"])
        replacement["difficulty"] = label
        replacement["chapter"] = chapter
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
        ref=payload.ref,
        reuse_source=reuse_source,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    return _qp_out(qp)


@router.post("/teacher/qpapers/{qp_id}/finalize", response_model=QPOut)
def teacher_qp_finalize(qp_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> QPOut:
    """FINAL is an explicit teacher action, blocked until every question reviewed."""
    qp = _qp_or_404(db, qp_id, teacher)
    if qp.status == "final":
        raise HTTPException(status_code=409, detail="already finalised")
    unreviewed = [str(q["ref"]) for q in qp.questions if not q.get("reviewed")]
    if unreviewed:
        raise HTTPException(
            status_code=409,
            detail={"code": "review_required", "unreviewed": unreviewed},
        )
    qp.status = "final"
    qp.finalized_at = datetime.now(UTC).replace(tzinfo=None)
    # S5.6 audit event 4/5: qp_finalize (exam-paper finalisation is
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
        raise HTTPException(status_code=400, detail="kind must be paper or answer")
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


# --- S2.6: lesson plan copilot (8 sections, editable + printable) ---------


@router.post("/teacher/lesson-plans", response_model=LessonPlanOut)
async def teacher_lesson_plan(
    app_ctx: Ctx, payload: LessonPlanIn, db: DbSession, teacher: TeacherOrAdminUser
) -> LessonPlanOut:
    """S2.6: one retrieval + one AI call drafts an eight-section plan.

    Wave 1: the plan is now ALSO persisted as a TeacherDocument
    (kind=lesson_plan) through the shared generator runner, and the
    response gains the additive ``document_id`` only -- every previously
    existing field keeps its exact shape.
    """
    if app_ctx.tutor is None:
        raise HTTPException(status_code=503, detail="provider not configured")
    started = time.perf_counter()
    try:
        doc_payload, sources, _chapter = await _generate_document(
            app_ctx, db, teacher, "lesson_plan", payload
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail="lesson plan generation failed") from exc
    doc = _persist_document(
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


# --- Wave 1: generic document generators + document library ---------------


def _document_or_404(db: Session, document_id: int, actor: User) -> TeacherDocument:
    doc = db.get(TeacherDocument, document_id)
    if doc is None or (doc.teacher_id != actor.id and actor.role != "admin"):
        raise HTTPException(status_code=404, detail="document not found")
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
    app_ctx: Ctx, kind: str, body: dict, db: DbSession, teacher: TeacherOrAdminUser
) -> GenerateDocumentOut:
    """One endpoint, four generators: worksheet | answer_key | homework |
    rubric. The persisted TeacherDocument is returned with the cited
    sources (answer_key takes {paper_id} OR {questions})."""
    if kind not in TEACHER_DOCUMENT_KINDS:
        raise HTTPException(status_code=404, detail="unknown generator kind")
    if app_ctx.tutor is None:
        raise HTTPException(status_code=503, detail="provider not configured")
    try:
        gen_in = _doc_in_for(kind, body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": [str(p) for p in e["loc"]], "msg": str(e["msg"])} for e in exc.errors()[:5]
            ],
        ) from exc
    started = time.perf_counter()
    try:
        doc_payload, sources, chapter = await _generate_document(app_ctx, db, teacher, kind, gen_in)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"{kind} generation failed") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    # Wave 2: server-side product analytics (kind + id only, no PII).
    _record_analytics(
        db,
        teacher.id,
        teacher.role,
        "teacher_document_generated",
        {"kind": kind, "document_id": doc.id},
    )
    db.commit()
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
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[TeacherDocumentOut]:
    """Own library, newest first; optional kind filter (includes the
    lesson_plan kind persisted by POST /teacher/lesson-plans)."""
    allowed = (*TEACHER_DOCUMENT_KINDS, "lesson_plan")
    if kind is not None and kind not in allowed:
        raise HTTPException(status_code=422, detail="unknown document kind")
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
        raise HTTPException(status_code=404, detail="document not found")
    db.delete(doc)
    db.commit()
    return Response(status_code=204)


@router.get("/teacher/documents/{document_id}/pdf")
def teacher_document_pdf(document_id: int, db: DbSession, teacher: TeacherOrAdminUser) -> Response:
    doc = _document_or_404(db, document_id, teacher)
    if doc.kind not in TEACHER_DOCUMENT_PDF_KINDS:
        raise HTTPException(status_code=400, detail="no PDF export for this document kind")
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


# --- Wave 1: saved notes ----------------------------------------------------
