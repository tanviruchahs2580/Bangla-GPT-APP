"""Teacher content routes, split by resource (C-03): chapter content,
question papers, and the generated documents.

_qpapers_review — C-03 split of ``routers/teacher_content.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse

from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    QPOut,
    QPReplaceIn,
    QPReviewIn,
)
from bangla_gpt_api.security import write_audit
from bangla_gpt_api.services.qp_pdf import (
    render_qp_html,
    render_qp_pdf,
)
from bangla_gpt_api.services.question_bank import (
    find_reusable,
    store_reviewed,
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
from ._qpapers import (  # noqa: F401
    _qp_editable as _qp_editable,
)
from ._qpapers import (
    _qp_fresh_draft as _qp_fresh_draft,
)
from ._qpapers import (
    _qp_or_404 as _qp_or_404,
)
from ._qpapers import (
    _qp_out as _qp_out,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


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


@router.post("/teacher/qpapers/{qp_id}/replace", response_model=QPOut)
async def teacher_qp_replace(
    app_ctx: Ctx, qp_id: int, payload: QPReplaceIn, db: DbSession, teacher: AIGenerationUser
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
    # reuse a reviewed bank question when one fits (MCQ-complete,
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
