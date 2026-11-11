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

A model the table does not price is NOT the same fact as a free model:
``estimate_cost_usd`` cannot do better than 0.0 for it, so the ledger row
names it explicitly (:data:`UNPRICED_MODEL_MARKER`) and a warning is logged
— otherwise a typo'd or newly deployed model silently costs nothing and the
budget gate can never block on it (BE-FIX-008).
"""

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.logging_config import json_log

logger = logging.getLogger(__name__)

# (input USD per 1K tokens, output USD per 1K tokens). Estimates — see module doc.
MODEL_COSTS_USD_PER_1K: dict[str, tuple[float, float]] = {
    "mock": (0.0, 0.0),
    "gemini-3.1-flash-lite": (0.000075, 0.0003),
    "gemini-2.5-flash-lite": (0.000075, 0.0003),
    "gemini-2.5-flash": (0.0003, 0.0025),
    "gpt-4o-mini": (0.00015, 0.0006),
}

#: Suffix appended to a ledger row's ``model`` when ``MODEL_COSTS_USD_PER_1K``
#: has no rate for it (BE-FIX-008). An unpriced model's cost estimate falls
#: back to 0.0 — "we do not know this model's price" and "this model is free"
#: are different facts, and the former silently disables the budget gate. The
#: marker makes the row self-describing in the database and in
#: ``/admin/ai/quality``'s per-model breakdown.
UNPRICED_MODEL_MARKER = " [unpriced]"

_CHARS_PER_TOKEN = 4

#: ``model`` column width (db.models.AiUsage.model) — the name + marker must fit.
_MODEL_MAX_CHARS = 80


def estimate_tokens(text: str | None) -> int:
    """Heuristic token estimate for mixed Bangla/English text (see module doc)."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def is_priced_model(model: str | None) -> bool:
    """True when the cost table has a rate for this model (``mock`` included)."""
    return (model or "mock") in MODEL_COSTS_USD_PER_1K


def ledger_model_name(model: str | None) -> str:
    """The ``AiUsage.model`` cell: the model name, marked when unpriced.

    BE-FIX-008: the fallback rate for a model missing from the table is 0.0,
    so an unknown model would be metered as free forever and the monthly
    budget could never see it. The stored name carries
    :data:`UNPRICED_MODEL_MARKER` instead — the number stays the honest
    fallback the caller can audit, but the row says out loud that its cost is
    an unknown rather than a zero. Pricing itself still uses the RAW name, so
    marking cannot change any estimate.
    """
    name = (model or "mock").strip() or "mock"
    if is_priced_model(name) or name.endswith(UNPRICED_MODEL_MARKER):
        # Already in the table, or already marked by an earlier write for the
        # same row (reserve -> finalize) -- never mark twice.
        return name[:_MODEL_MAX_CHARS]
    marked = name[: _MODEL_MAX_CHARS - len(UNPRICED_MODEL_MARKER)] + UNPRICED_MODEL_MARKER
    json_log(logger, logging.WARNING, "ai_usage_unpriced_model", model=name)
    return marked


def estimate_cost_usd(model: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost for one generation (rounded to 10 decimal places).

    An unpriced model yields 0.0 (the documented fallback); the ledger marks
    that case via :func:`ledger_model_name` rather than pretending it is free.
    """
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
    prompt_tokens: int | None = None,
) -> AiUsage:
    """Append one ledger row. Adds only — the CALLER's commit persists it.

    ``prompt_tokens`` overrides the ``prompt_text`` heuristic (BE-FIX-008):
    a route that measures the COMPOSED prompt (system template + evidence
    budget + question) passes the measured count, because the composed text
    itself is assembled deeper in the stack and is not available here.
    """
    raw_model = model or "mock"
    effective_prompt_tokens = (
        int(prompt_tokens) if prompt_tokens is not None else estimate_tokens(prompt_text)
    )
    completion_tokens = estimate_tokens(answer_text)
    row = AiUsage(
        user_id=user_id,
        route=route[:40],
        model=ledger_model_name(raw_model),
        prompt_tokens=effective_prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimate_cost_usd(raw_model, effective_prompt_tokens, completion_tokens),
    )
    db.add(row)
    return row


def reserve_ai_usage(
    db: Session,
    *,
    user_id: int,
    route: str,
    model: str | None,
    prompt_text: str | None,
    prompt_tokens: int | None = None,
) -> AiUsage:
    """Insert the ledger row BEFORE the provider call (BE-01).

    The old shape ledgered only after completion, which broke budgeting
    twice: two parallel generations both passed ``check_ai_budget`` off a
    ledger that had not grown yet (check-then-commit race), and a stream
    the student disconnected mid-way never landed a row at all — tokens
    the platform paid for vanished from the books. The reserve is a real
    ledger row at the estimated prompt cost; ``finalize_ai_usage`` updates
    it in place with the answer, so a completed generation still owns
    exactly one row, and the budget gate now sees in-flight spend.

    The CALLER must commit right after reserving (their own short
    transaction — the reserve is only budget-visible once committed) and
    must finalize in every path: success, refusal, provider failure, and
    stream disconnect (with the partial text — a truncated answer is still
    the student's ledger line, never a silent zero).

    ``prompt_tokens`` is the caller-measured prompt size when the composed
    prompt is only known to the caller (BE-FIX-008).
    """
    return record_ai_usage(
        db,
        user_id=user_id,
        route=route,
        model=model,
        prompt_text=prompt_text,
        answer_text=None,
        prompt_tokens=prompt_tokens,
    )


def finalize_ai_usage(
    db: Session,
    row: AiUsage | None,
    *,
    model: str | None,
    answer_text: str | None,
) -> None:
    """Update a reserved ledger row in place with the (possibly partial)
    answer. Adds or updates only; the CALLER's commit persists it.

    BE-FIX-010: ``row=None`` is a programming error, not a legacy shape —
    every generation reserves before it calls a provider (BE-01), so a
    missing reserve would silently append an unfinalized second row and
    double-count the prompt spend; the docstring used to promise the
    opposite of what the body did. The body raises ``ValueError`` and the
    docstring now says so.
    """
    if row is None:
        raise ValueError("finalize_ai_usage requires a reserved row")
    completion_tokens = estimate_tokens(answer_text)
    row.model = ledger_model_name(model or row.model)
    row.completion_tokens = completion_tokens
    row.estimated_cost_usd = estimate_cost_usd(row.model, row.prompt_tokens, completion_tokens)
    db.add(row)


def abandon_ai_usage(db: Session, row: AiUsage | None, *, model: str | None, reason: str) -> None:
    """Finalize a reserved row for a generation that produced NOTHING.

    BE-FIX-003: the document pipeline reserves before it validates or calls a
    provider, so every early exit (unknown kind, a rejected input, the
    post-provider safety screen, a provider exception) used to leave the row
    unfinalized -- a ledger line whose answer side never ran, and a state no
    caller in this codebase knows how to finish. This is the one finalize
    shape for those paths: completion stays 0 (no answer was produced) and the
    route cell records WHY (``<route>:<reason>``) so an operator can tell a
    failure from a generation still in flight. Adds or updates only; the
    CALLER's commit persists it.
    """
    if row is None:
        return
    finalize_ai_usage(db, row, model=model, answer_text=None)
    row.route = f"{row.route}:{reason}"[:40]


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
