"""Teacher content routes, split by resource (C-03): chapter content,
question papers, and the generated documents.

_documents — C-03 split of ``routers/teacher_content.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    TeacherDocument,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    TEACHER_DOCUMENT_KINDS,
    TEACHER_DOCUMENT_PDF_KINDS,
    GenerateDocumentOut,
    LessonPlanIn,
    LessonPlanOut,
    TeacherDocumentOut,
)
from bangla_gpt_api.services.qp_pdf import (
    render_document_html,
    render_document_pdf,
)

from .._pagination import TaskListPage
from ..common import (
    _doc_in_for,
    _generate_document,
    _persist_document,
    _record_analytics,
)
from ..deps import (
    AIGenerationUser,
    Ctx,
    DbSession,
    TeacherOrAdminUser,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


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
    app_ctx: Ctx, kind: str, body: dict, db: DbSession, teacher: AIGenerationUser
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
    # server-side product analytics (kind + id only, no PII).
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
    page: TaskListPage,
    kind: str | None = None,
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
            q.order_by(TeacherDocument.created_at.desc(), TeacherDocument.id.desc())
            .offset(page.offset)
            .limit(page.limit)
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
