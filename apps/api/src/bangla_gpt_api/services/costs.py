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

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.metrics import AI_COST_USD_TOTAL, AI_TOKENS_TOTAL

# (input USD per 1K tokens, output USD per 1K tokens). List prices as read
# from the vendors' pricing pages on 2026-10-18 -- see the module docstring
# for the URLs and the owner-confirmation note.
MODEL_COSTS_USD_PER_1K: dict[str, tuple[float, float]] = {
    "mock": (0.0, 0.0),
    # Gemini 3.1 Flash-Lite standard tier: $0.25 / $1.50 per 1M tokens.
    "gemini-3.1-flash-lite": (0.00025, 0.0015),
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
