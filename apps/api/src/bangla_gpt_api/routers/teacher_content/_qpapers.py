"""Teacher content routes, split by resource (C-03): chapter content,
question papers, and the generated documents.

_qpapers — C-03 split of ``routers/teacher_content.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    QuestionPaper,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    QPDraftIn,
    QPOut,
    QPQuestion,
)
from bangla_gpt_api.services.context import (
    RequestContext,
)
from bangla_gpt_api.services.costs import check_ai_budget, record_ai_usage
from bangla_gpt_api.services.generators import (
    generate_question_paper,
)
from bangla_gpt_api.services.question_bank import (
    bank_keys,
    dedupe_key,
)

from ..common import (
    _request_context,
)
from ..deps import (
    AIGenerationUser,
    Ctx,
    DbSession,
    TeacherOrAdminUser,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


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
        raise HTTPException(status_code=503, detail="provider not configured")
    check_ai_budget(db, user_id=actor.id, settings=app_ctx.settings)
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
        raise HTTPException(status_code=502, detail="question paper generation failed") from exc
    # Adds only; the caller's commit persists the ledger row with the paper.
    record_ai_usage(
        db,
        user_id=actor.id,
        route="teacher/question_paper",
        model=getattr(app_ctx.provider, "name", None),
        prompt_text=f"{subject} {','.join(chapters)} class {class_level} {marks} marks",
        answer_text=json.dumps(questions, ensure_ascii=False, default=str),
    )
    return questions, meta


@router.post("/teacher/qpapers", response_model=QPOut, status_code=201)
async def teacher_qp_create(
    app_ctx: Ctx, payload: QPDraftIn, db: DbSession, teacher: AIGenerationUser
) -> QPOut:
    """Draft = one retrieval + one AI call behind three validation gates."""
    difficulty = payload.difficulty.model_dump()
    started = time.perf_counter()
    questions, meta = await _qp_fresh_draft(
        app_ctx,
        db,
        teacher,
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
    return _qp_out(qp)


@router.get("/teacher/qpapers", response_model=list[QPOut])
def teacher_qp_list(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
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
        raise HTTPException(status_code=409, detail="paper is already finalised")


@router.post("/teacher/qpapers/{qp_id}/regenerate", response_model=QPOut)
async def teacher_qp_regenerate(
    app_ctx: Ctx, qp_id: int, db: DbSession, teacher: AIGenerationUser
) -> QPOut:
    """New AI draft under the same spec; review flags reset."""
    qp = _qp_or_404(db, qp_id, teacher)
    _qp_editable(qp)
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
