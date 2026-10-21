"""Tutor routes, split by surface (C-03): the single-shot ask, the
conversation history, the streamed chat, feedback, and product events.

_ask — C-03 split of ``routers/tutor.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    AskRequest,
    AskResponse,
)
from bangla_gpt_api.services.activity import (
    record_activity,
)
from bangla_gpt_api.services.costs import (
    check_ai_budget,
    check_daily_cost_breaker,
    check_school_daily_budget,
    record_ai_usage,
)
from bangla_gpt_api.services.quiz_explain import quiz_explain_instruction

from ..common import (
    _request_context,
    _student_profile,
    canonical_subject,
)
from ..deps import (
    Ctx,
    CurrentUser,
    DbSession,
)
from ._shared import (  # noqa: F401
    DEFAULT_INFLIGHT_SINGLE as DEFAULT_INFLIGHT_SINGLE,
)
from ._shared import (
    _inflight_slot as _inflight_slot,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)


@router.post("/tutor/ask", response_model=AskResponse)
async def ask(app_ctx: Ctx, payload: AskRequest, db: DbSession, user: CurrentUser) -> AskResponse:
    tutor = app_ctx.tutor
    if tutor is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "tutor_unavailable", "message": "Tutor service unavailable"},
        )
    # AI-002: budget gate before spending upstream tokens.
    check_ai_budget(db, user_id=user.id, settings=app_ctx.settings)
    # A7-05: the platform-wide and per-school daily breakers bound spend that
    # spreads across accounts (a per-user monthly budget cannot).
    check_daily_cost_breaker(db, settings=app_ctx.settings)
    check_school_daily_budget(db, school_id=user.school_id, settings=app_ctx.settings)
    try:
        explain_instruction = quiz_explain_instruction(payload.explain) if payload.explain else None
        # retrieve on the quiz topic itself — the generic
        # 'explain this' phrasing carries no subject keywords. the
        # phrasing is dropped from the RETRIEVE/gate query entirely (it
        # diluted coverage below the grounding gate); it stays in the
        # prompt so the model still sees the student's own words.
        question = payload.question
        search_query: str | None = None
        if payload.explain:
            question = f"{payload.question}\n{payload.explain.question}"
            search_query = payload.explain.question
        # every AI call carries the central education context.
        ctx = _request_context(
            db,
            user,
            class_level=payload.class_level,
            subject=canonical_subject(payload.subject),
            chapter=payload.chapter,
            goal="quiz_explain" if payload.explain else "question",
        )
        with _inflight_slot(app_ctx, user, default=DEFAULT_INFLIGHT_SINGLE):
            response = await tutor.ask(
                question,
                payload.class_level,
                canonical_subject(payload.subject),
                chapter=payload.chapter,
                extra_instruction=explain_instruction,
                low_data=payload.low_data,
                context=ctx,
                search_query=search_query,
            )
        # AI-002: ledger the generation (adds only; this commit persists it).
        record_ai_usage(
            db,
            user_id=user.id,
            route="tutor.ask",
            model=getattr(tutor.provider, "model", None) or tutor.provider.name,
            prompt_text=question,
            answer_text=response.answer,
        )
        # one tutoring question ≈ one minute of study for the daily
        # counters (the chat routes already record; ask must not be a gap).
        if user.role == "student":
            record_activity(db, _student_profile(db, user).id, questions=1, minutes=1)
        db.commit()
        return response
    except ProviderError as exc:
        # Upstream LLM failure (timeout/exhausted retries/blocked) must be a
        # controlled 502, never an unhandled 500.
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_unavailable", "message": "LLM provider unavailable"},
        ) from exc
