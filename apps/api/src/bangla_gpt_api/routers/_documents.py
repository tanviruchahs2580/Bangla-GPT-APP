"""The teacher-document generation pipeline (split from common.py, F-077).

One concern: validate a document request, screen its free text, run the
generator through its budget/ledger/context surround, and persist the result.
Both the synchronous routes and the AiJob runner reach the generator through
``_generate_document`` so a background job behaves exactly like the sync call.
``routers/common.py`` re-exports these names for the import sites that predate
the split.
"""

import asyncio
import json
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import QuestionPaper, TeacherDocument, User
from bangla_gpt_api.providers import ProviderError
from bangla_gpt_api.schemas import (
    AnswerKeyIn,
    HomeworkIn,
    LessonPlanIn,
    RubricIn,
    SourceRef,
    WorksheetIn,
)
from bangla_gpt_api.services.context import RequestContext
from bangla_gpt_api.services.costs import (
    check_ai_budget,
    finalize_ai_usage,
    reserve_ai_usage,
)
from bangla_gpt_api.services.generators import (
    generate_answer_key,
    generate_homework,
    generate_lesson_plan,
    generate_rubric,
    generate_worksheet,
)

from ._context import _request_context
from .deps import Ctx

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


class DocumentInputError(Exception):
    """A document request the caller can fix, with a caller-safe body.

    Raised instead of the bare ``LookupError``/``ValueError`` this path used
    to throw: the routes answer with the coded envelope, so the exception
    carries the status, the machine-readable code and a message that is
    written for the client -- arbitrary exception text never reaches the
    response body (F-074).
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _doc_in_for(kind: str, body: dict) -> Any:
    """Validate a raw body against the per-kind input model.

    Unknown kinds raise :class:`DocumentInputError` and malformed bodies raise
    pydantic.ValidationError; callers map them to HTTP codes (sync) or
    to the failed job state (background)."""
    model = _DOC_IN_MODELS.get(kind)
    if model is None:
        raise DocumentInputError(404, "unknown_kind", "unknown generator kind")
    return model.model_validate(body)


def _generate_document_prepare(
    app_ctx: Ctx,
    db: Session,
    actor: User,
    kind: str,
    gen: Any,
    *,
    class_level: int,
    subject: str,
    chapter: str | None,
) -> tuple[list[str], str | None, RequestContext]:
    """DB prelude of the document generators (budget, answer-key paper
    load, education context). Runs off the event loop via to_thread —
    the generators themselves are async and must not share the loop
    with blocking DB round-trips."""
    check_ai_budget(db, user_id=actor.id, settings=app_ctx.settings)
    questions: list[str] = []
    if kind == "answer_key":
        questions = [q.strip() for q in (gen.questions or []) if q.strip()]
        if gen.paper_id is not None:
            qp = db.get(QuestionPaper, gen.paper_id)
            if qp is None or (qp.teacher_id != actor.id and actor.role != "admin"):
                raise DocumentInputError(404, "not_found", "question paper not found")
            questions = [
                str(q.get("text", "")).strip()
                for q in qp.questions
                if str(q.get("text", "")).strip()
            ]
            chapter = chapter or (str(qp.chapters[0]) if qp.chapters else None)
        if not questions:
            raise DocumentInputError(422, "invalid_input", "answer key needs at least one question")
    ctx = _request_context(
        db,
        actor,
        class_level=class_level,
        subject=subject,
        chapter=chapter,
        # lesson_plan keeps its S2 goal string; the new kinds are prefixed
        goal="lesson_plan" if kind == "lesson_plan" else f"generate_{kind}",
    )
    return questions, chapter, ctx


#: Structured fields that carry a question addressed to a student. Everything
#: else in a generated payload is teacher-facing prose (lesson plans, rubric
#: criteria) and is deliberately not screened word-for-word -- see B-08.
_QUESTION_TEXT_KEYS = frozenset({"question", "question_text", "stem"})


def _iter_question_texts(node: Any) -> Iterator[str]:
    """Yield question-form text from a generated payload, depth-first.

    Handles every generator shape without per-kind knowledge: MCQ objects
    (``{"question": ...}``), cloze stems, and inline string question lists
    under any ``questions``-style key.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                isinstance(key, str)
                and key.lower() in _QUESTION_TEXT_KEYS
                and isinstance(value, str)
            ):
                yield value
                continue
            yield from _iter_question_texts(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_question_texts(item)


def _screen_free_text(texts: Iterable[str], *, where: str) -> None:
    """Refuse when any free-text fragment trips the child-safety panel.

    The same ``screen_question`` the student tutor runs on every turn
    (prompt-injection, self-harm, weapons, drugs, sexual content -- with the
    academic-science exemptions). A teacher generator used to be the one
    LLM path without it (B-08), while its documents are handed to minors.
    The 400 code is the unsafe-content contract the tutor refusal uses;
    the AiJob runner records the same code in the failed job.
    """
    from bangla_gpt_api.services.safety import screen_question

    for text in texts:
        if not text or not text.strip():
            continue
        verdict = screen_question(text)
        if not verdict.safe:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unsafe_content",
                    "message": (
                        "One or more texts failed the child-safety screen; "
                        "nothing was generated or charged for this request"
                    ),
                    "reason": verdict.reason or "unsafe_content",
                    "where": where,
                },
            )


async def _generate_document(
    app_ctx: Ctx, db: Session, actor: User, kind: str, gen: Any
) -> tuple[dict, list[SourceRef], str | None]:
    """THE single execution path of the document generators: the sync
    endpoints and the AiJob runner below share it, so a background job
    behaves exactly like the synchronous call.

    Because every generator funnels through here, this is also where the
    per-user AI budget is enforced and the spend ledgered (SEC-002). Doing it in
    the route handlers instead would leave ``POST /teacher/jobs`` -- which runs
    this on a detached task with its own session -- unbudgeted and unmetered,
    and ``/admin/ai/quality`` would under-report every teacher generation.
    """
    if app_ctx.tutor is None:
        raise ProviderError("provider not configured")
    class_level = int(gen.class_level)
    subject = str(gen.subject)
    chapter: str | None = getattr(gen, "chapter", None)
    # B-08: the child-safety screen is not student-turn-only. Teacher
    # free-text (subject/chapter and up to 50 inline answer-key questions)
    # used to reach the provider unscreened. Screen the free-text INPUTS
    # BEFORE any retrieval or provider spend -- an unsafe chapter is also a
    # chapter with no textbook evidence, so screening after prepare would
    # answer 404 no-evidence and never name the real reason -- and the
    # generated QUESTION texts after the provider, before the document is
    # persisted. Same compiled patterns every student tutor turn runs.
    gen_inline_questions = getattr(gen, "questions", None) or []
    _screen_free_text(
        [subject, chapter or "", *[str(q) for q in gen_inline_questions]],
        where=f"teacher/{kind} input",
    )
    # BE-01: reserve the ledger row before retrieval or provider spend and
    # commit it -- a concurrent generation's budget gate must count this
    # in-flight teacher spend, and a provider failure keeps the honest
    # prompt-side line instead of a row that never was.
    pending_usage = reserve_ai_usage(
        db,
        user_id=actor.id,
        route=f"teacher/{kind}",
        model=getattr(app_ctx.tutor.provider, "model", None) or app_ctx.tutor.provider.name,
        prompt_text=f"{subject} {chapter or ''} class {class_level}",
    )
    await asyncio.to_thread(db.commit)
    questions, chapter, ctx = await asyncio.to_thread(
        _generate_document_prepare,
        app_ctx,
        db,
        actor,
        kind,
        gen,
        class_level=class_level,
        subject=subject,
        chapter=chapter,
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
        raise DocumentInputError(404, "unknown_kind", "unknown generator kind")
    # B-08 output side: screen the generated QUESTION texts before the
    # document is persisted or ledgered. The provider is prompted for
    # curriculum content, but a jailbreak mirrored through the retrieval
    # context or a plain model slip must not reach a classroom printout.
    # Only structured question fields are screened -- lesson-plan prose
    # (deliberately open-ended teaching text) goes to the teacher hub, not
    # to a quiz paper handed to students.
    _screen_free_text(_iter_question_texts(doc_payload), where=f"teacher/{kind} output")
    # Ledger the spend: finalize the reserve -- one row per generation.
    # The prompt side is the retrieval context actually sent; the answer
    # side is the serialised document, which is what the tokens were spent
    # producing. Caller persists the document (or marks the AiJob ready)
    # and commits this row with it.
    await asyncio.to_thread(
        finalize_ai_usage,
        db,
        pending_usage,
        model=getattr(app_ctx.tutor.provider, "model", None) or app_ctx.tutor.provider.name,
        answer_text=json.dumps(doc_payload, ensure_ascii=False, default=str),
    )
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
    # caller controls commit boundary; commit once at route/service boundary
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
