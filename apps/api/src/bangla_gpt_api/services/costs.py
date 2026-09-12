"""AI-002: LLM usage estimation, ledger and per-user budgets.

Token counts are PLANNING ESTIMATES, not vendor-metered values:

* ``estimate_tokens`` uses ~4 characters per token, the standard heuristic
  for mixed Bangla/English text (Bangla script tokenizes denser than ASCII;
  4 chars/token is conservative for cost control — it over-counts short
  ASCII and under-counts long Bangla, erring toward budget safety).
* ``MODEL_COSTS_USD_PER_1K`` are list-price estimates reviewed 2026-09.
  Re-check vendor pricing pages before procurement decisions; the table is
  the single place to update.

Budgets: ``ai_monthly_budget_usd_per_user`` (0 = unlimited, the default).
When set, generation entry points refuse with 429 ``ai_budget_exceeded``
once the user's current-UTC-month ledger reaches the cap.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AiUsage

# (input USD per 1K tokens, output USD per 1K tokens). Estimates — see module doc.
MODEL_COSTS_USD_PER_1K: dict[str, tuple[float, float]] = {
    "mock": (0.0, 0.0),
    "gemini-3.1-flash-lite": (0.000075, 0.0003),
    "gemini-2.5-flash-lite": (0.000075, 0.0003),
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
    """Append one ledger row. Adds only — the CALLER's commit persists it."""
    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = estimate_tokens(answer_text)
    row = AiUsage(
        user_id=user_id,
        route=route[:40],
        model=(model or "mock")[:80],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimate_cost_usd(model, prompt_tokens, completion_tokens),
    )
    db.add(row)
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
