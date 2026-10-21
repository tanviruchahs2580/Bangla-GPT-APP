"""AI-002: LLM usage estimation, ledger and per-user budgets.

Token counts are PLANNING ESTIMATES, not vendor-metered values:

* ``estimate_tokens`` uses ~4 characters per token, the standard heuristic
  for mixed Bangla/English text (Bangla script tokenizes denser than ASCII;
  4 chars/token is conservative for cost control — it over-counts short
  ASCII and under-counts long Bangla, erring toward budget safety).
* ``MODEL_COSTS_USD_PER_1K`` are list prices read from the vendors' own
  pricing pages on 2026-10-18 (AUD-HI-15 / I-11). The table is the single
  place to update; the docstring is the citation:

  - Google Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
    (page last updated 2026-10-16 UTC; values read 2026-10-18)
  - OpenAI API pricing: https://platform.openai.com/docs/pricing

  Owner action (I10): re-confirm the rows for the exact tier and region in
  use before any procurement decision. This module is a *planning* control
  (budgets, dashboards, burn-rate alerts), never a billing system: the
  vendor invoice is authoritative.

Budgets: ``ai_monthly_budget_usd_per_user`` (0 = unlimited, the default).
When set, generation entry points refuse with 429 ``ai_budget_exceeded``
once the user's current-UTC-month ledger reaches the cap.
"""

import logging
import os
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.metrics import AI_COST_USD_TOTAL, AI_TOKENS_TOTAL

logger = logging.getLogger("bangla_gpt_api.costs")

# (input USD per 1K tokens, output USD per 1K tokens). List prices as read
# from the vendors' pricing pages on 2026-10-18 -- see the module docstring
# for the URLs and the owner-confirmation note.
MODEL_COSTS_USD_PER_1K: dict[str, tuple[float, float]] = {
    "mock": (0.0, 0.0),
    # Gemini 3.1 Flash-Lite standard tier: $0.25 / $1.50 per 1M tokens.
    "gemini-3.1-flash-lite": (0.00025, 0.0015),
    # Gemini 3.5 Flash-Lite standard tier: $0.30 / $2.50 per 1M tokens (read
    # from the same vendor pricing page on 2026-10-19). The live evaluation runs
    # on this model: without the row every live call would be metered at the
    # "mock" fallback -- zero -- and the budget breakers above would never see
    # the spend they exist to bound.
    "gemini-3.5-flash-lite": (0.0003, 0.0025),
    # Gemini 2.5 Flash-Lite standard tier: $0.10 / $0.40 per 1M tokens.
    "gemini-2.5-flash-lite": (0.0001, 0.0004),
    "gemini-2.5-flash": (0.0003, 0.0025),
    "gpt-4o-mini": (0.00015, 0.0006),
}

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str | None) -> int:
    """Heuristic token estimate for mixed Bangla/English text (see module doc)."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_cost_usd(model: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost for one generation (rounded to 10 decimal places)."""
    per_in, per_out = MODEL_COSTS_USD_PER_1K.get(model or "mock", MODEL_COSTS_USD_PER_1K["mock"])
    return round(prompt_tokens / 1000 * per_in + completion_tokens / 1000 * per_out, 10)


def record_ai_usage(
    db: Session,
    *,
    user_id: int,
    route: str,
    model: str | None,
    prompt_text: str | None,
    answer_text: str | None,
) -> AiUsage:
    """Append one ledger row and export the token/cost counters.

    Adds only -- the CALLER's commit persists the row. The Prometheus
    counters are exported here (not at the provider call sites) because this
    is the single funnel every AI-bearing route goes through, so the
    dashboard and the budget alert cannot drift from the ledger.
    """
    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = estimate_tokens(answer_text)
    cost_usd = estimate_cost_usd(model, prompt_tokens, completion_tokens)
    row = AiUsage(
        user_id=user_id,
        route=route[:40],
        model=(model or "mock")[:80],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost_usd,
    )
    db.add(row)
    safe_model = (model or "mock")[:80]
    safe_route = route[:40]
    AI_TOKENS_TOTAL.labels(model=safe_model, direction="prompt").inc(prompt_tokens)
    AI_TOKENS_TOTAL.labels(model=safe_model, direction="completion").inc(completion_tokens)
    if cost_usd > 0:
        AI_COST_USD_TOTAL.labels(model=safe_model, route=safe_route).inc(cost_usd)
    return row


def month_cost_usd(db: Session, user_id: int, now: datetime | None = None) -> float:
    """Current-UTC-month ledger total for one user."""
    now = now or datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = month_start.replace(tzinfo=None)
    total = db.execute(
        select(func.coalesce(func.sum(AiUsage.estimated_cost_usd), 0.0)).where(
            AiUsage.user_id == user_id, AiUsage.created_at >= month_start
        )
    ).scalar_one()
    return float(total)


def check_ai_budget(db: Session, *, user_id: int, settings) -> None:
    """Refuse generation when the user's monthly budget is exhausted.

    ``ai_monthly_budget_usd_per_user <= 0`` disables the check (default).
    """
    budget = float(getattr(settings, "ai_monthly_budget_usd_per_user", 0.0) or 0.0)
    if budget <= 0:
        return
    if month_cost_usd(db, user_id) >= budget:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ai_budget_exceeded",
                "message": "Monthly AI budget exhausted. Please try again next month.",
            },
        )


# --- cost circuit breakers (AUD-A2-10 / A7-05) -----------------------------
#
# The per-user monthly budget above bounds one account. Two more breakers
# bound the platform: a whole-deployment DAILY ceiling (an abuse loop spreads
# across accounts) and a per-SCHOOL daily ceiling (one school's classroom
# cannot consume the national budget). Both read the same estimated ledger as
# the monthly budget and are 0 = disabled by default, so enabling them is an
# explicit operational decision.

DEFAULT_DAILY_BUDGET_USD = 0.0
DEFAULT_SCHOOL_DAILY_BUDGET_USD = 0.0
DEFAULT_MAX_CONVERSATION_MESSAGES = 200

#: Interim switch names for the breaker settings, used until the Settings
#: fields land (handoff: .audit/handoffs/api-rag2.md). A Settings field always
#: wins; the environment variable is only the fallback, so wiring the field
#: later changes nothing for an operator who already set the variable.
BREAKER_ENV_KEYS: dict[str, str] = {
    "ai_daily_budget_usd": "AI_DAILY_BUDGET_USD",
    "ai_daily_budget_usd_per_school": "AI_DAILY_BUDGET_USD_PER_SCHOOL",
    "ai_max_conversation_messages": "AI_MAX_CONVERSATION_MESSAGES",
}


def _numeric_setting(
    settings: object | None, field: str, default: float, *, as_int: bool = False
) -> float:
    """Resolve a numeric breaker setting: settings field, env, then default."""
    raw = getattr(settings, field, None) if settings is not None else None
    if raw is None:
        raw = os.environ.get(BREAKER_ENV_KEYS[field])
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid value for %s=%r; using %s", field, raw, default)
        return default
    return float(int(value)) if as_int else value


def _day_start(now: datetime | None = None) -> datetime:
    """UTC midnight of the current day, naive like the ledger column."""
    moment = now or datetime.now(UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def day_cost_usd(db: Session, *, user_id: int | None = None, now: datetime | None = None) -> float:
    """Current-UTC-day estimated spend, for one user or the whole deployment."""
    stmt = select(func.coalesce(func.sum(AiUsage.estimated_cost_usd), 0.0)).where(
        AiUsage.created_at >= _day_start(now)
    )
    if user_id is not None:
        stmt = stmt.where(AiUsage.user_id == user_id)
    return float(db.execute(stmt).scalar_one())


def school_day_cost_usd(db: Session, *, school_id: int, now: datetime | None = None) -> float:
    """Current-UTC-day estimated spend for one school's users."""
    from bangla_gpt_api.db.models import User

    total = db.execute(
        select(func.coalesce(func.sum(AiUsage.estimated_cost_usd), 0.0))
        .join(User, AiUsage.user_id == User.id)
        .where(AiUsage.created_at >= _day_start(now), User.school_id == school_id)
    ).scalar_one()
    return float(total)


def check_daily_cost_breaker(db: Session, *, settings, now: datetime | None = None) -> None:
    """Refuse generation when the deployment's daily spend hits its ceiling.

    ``ai_daily_budget_usd <= 0`` disables the breaker (default). This is the
    last-resort loop breaker: a retry storm or an abuse campaign that spreads
    over many accounts still stops here.
    """
    budget = _numeric_setting(settings, "ai_daily_budget_usd", DEFAULT_DAILY_BUDGET_USD)
    if budget <= 0:
        return
    if day_cost_usd(db, now=now) >= budget:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ai_daily_budget_exceeded",
                "message": "Daily AI budget exhausted. Please try again tomorrow.",
            },
        )


def check_school_daily_budget(
    db: Session, *, school_id: int | None, settings, now: datetime | None = None
) -> None:
    """Refuse generation when one school's daily spend hits its ceiling.

    ``ai_daily_budget_usd_per_school <= 0`` disables the check (default). A
    user without a school is unaffected (their per-user budget still applies).
    """
    if school_id is None:
        return
    budget = _numeric_setting(
        settings, "ai_daily_budget_usd_per_school", DEFAULT_SCHOOL_DAILY_BUDGET_USD
    )
    if budget <= 0:
        return
    if school_day_cost_usd(db, school_id=school_id, now=now) >= budget:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ai_school_budget_exceeded",
                "message": "This school's daily AI budget is exhausted. Please try again tomorrow.",
            },
        )


def check_conversation_cap(
    db: Session, *, conversation_id: int, settings, extra_messages: int = 0
) -> None:
    """Refuse a new turn when a conversation is at its message ceiling.

    ``ai_max_conversation_messages <= 0`` disables the cap (default: 200).
    An unbounded conversation is an unbounded prompt and an unbounded bill —
    the window sent to the model is bounded separately by
    ``chat_history_messages``, so the cap is about the stored conversation,
    not about context length.
    """
    from bangla_gpt_api.db.models import ChatMessage

    cap = int(
        _numeric_setting(
            settings,
            "ai_max_conversation_messages",
            DEFAULT_MAX_CONVERSATION_MESSAGES,
            as_int=True,
        )
    )
    if cap <= 0:
        return
    count = int(
        db.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
        ).scalar_one()
    )
    if count + max(0, extra_messages) >= cap:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "conversation_limit_reached",
                "message": "This conversation has reached its length limit. Please start a new one.",
            },
        )
