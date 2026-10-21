"""A2-20 / A9-02: the cost model -- measured tokens, cited prices, projections.

The audit's A9-02 was PARTIAL for three reasons, each addressed here:

1. **prices had no cited source.** :data:`PRICE_TABLE_CITATIONS` records, per
   model, the provider pricing page, the page's own last-updated date and the
   date this session read it, plus the input/output USD per 1M tokens. The
   numbers are then compared against the runtime table the app actually bills
   with (``services.costs.MODEL_COSTS_USD_PER_1K``) by
   :func:`verify_price_table`, so a stale runtime entry is a test failure, not
   a quiet drift.
2. **no cost per 1,000 answers.** :func:`cost_per_1000_answers` turns measured
   per-route token counts into that number, using the same estimator and price
   table as the ledger.
3. **no per-school projection.** :func:`school_monthly_projection` scales the
   measured per-route costs by documented monthly volumes; the volumes live in
   :data:`SCHOOL_ASSUMPTIONS` and are planning figures to be replaced with the
   owner's real usage, not measurements.

Budgets and alerts already exist in the product (per-user monthly budget with a
429 gate; a Prometheus projection alert) -- :func:`budget_alert_state` mirrors
the alert's arithmetic so a projection can be checked in CI or by hand without
Prometheus.
"""

from __future__ import annotations

from typing import Any

from bangla_gpt_api.services.costs import MODEL_COSTS_USD_PER_1K, estimate_cost_usd

#: Prices as read from the providers' own pages. ``verified`` is False when
#: this session could not read the page (a redirect or a JS-only page): the
#: entry then documents the attempt instead of pretending to a number.
PRICE_TABLE_CITATIONS: dict[str, dict[str, Any]] = {
    "gemini-3.1-flash-lite": {
        "provider": "Google",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
        "page_last_updated": "2026-10-16",
        "accessed": "2026-10-19",
        "tier": "standard paid (text/image/video input)",
        "input_usd_per_1m": 0.25,
        "output_usd_per_1m": 1.50,
        "verified": True,
    },
    "gemini-2.5-flash-lite": {
        "provider": "Google",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
        "page_last_updated": "2026-10-16",
        "accessed": "2026-10-19",
        "tier": "standard paid (text/image/video input)",
        "input_usd_per_1m": 0.10,
        "output_usd_per_1m": 0.40,
        "verified": True,
    },
    "gpt-4o-mini": {
        "provider": "OpenAI",
        "source": "https://platform.openai.com/docs/pricing",
        "page_last_updated": None,
        "accessed": "2026-10-19",
        "tier": "standard (unverified this session: the documented URL redirects "
        "to developers.openai.com, which this session did not fetch)",
        "input_usd_per_1m": 0.15,
        "output_usd_per_1m": 0.60,
        "verified": False,
    },
}

#: Planning volumes for one school. NOT measurements: the owner replaces these
#: with observed usage (or per-school settings) before any procurement decision.
SCHOOL_ASSUMPTIONS: dict[str, float] = {
    "students": 400,
    "student_asks_per_student_per_month": 40,
    "chat_turns_per_student_per_month": 20,
    "teacher_generations_per_month": 80,
}

#: Route -> the volume assumption that drives it in a projection.
ROUTE_VOLUMES: dict[str, str] = {
    "tutor.ask": "student_asks_per_student_per_month",
    "tutor.chat": "chat_turns_per_student_per_month",
    "tutor.chat.stream": "chat_turns_per_student_per_month",
    "teacher/question_paper": "teacher_generations_per_month",
    "teacher/worksheet": "teacher_generations_per_month",
    "teacher/rubric": "teacher_generations_per_month",
    "teacher/answer_key": "teacher_generations_per_month",
    "teacher/homework": "teacher_generations_per_month",
    "teacher/lesson_plan": "teacher_generations_per_month",
    "teacher/chapter_content": "teacher_generations_per_month",
}


def cost_per_1000_answers(model: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    """USD for 1,000 identical answers, from the runtime price table."""
    return round(estimate_cost_usd(model, prompt_tokens, completion_tokens) * 1000, 6)


def price_table_with_citations() -> dict[str, dict[str, Any]]:
    """The runtime price table joined with its citation, per model.

    ``matches_runtime`` is the check that matters: the number the ledger uses
    and the number the provider page published agree.
    """
    joined: dict[str, dict[str, Any]] = {}
    for model, citation in PRICE_TABLE_CITATIONS.items():
        runtime = MODEL_COSTS_USD_PER_1K.get(model)
        matches = False
        if runtime is not None:
            runtime_in, runtime_out = runtime
            matches = round(runtime_in * 1000, 8) == round(
                citation["input_usd_per_1m"], 8
            ) and round(runtime_out * 1000, 8) == round(citation["output_usd_per_1m"], 8)
        joined[model] = {
            **citation,
            "runtime_usd_per_1k": list(runtime) if runtime is not None else None,
            "matches_runtime": matches,
        }
    return joined


def verify_price_table() -> list[str]:
    """Mismatches between the cited page prices and the runtime table."""
    return [
        model
        for model, entry in price_table_with_citations().items()
        if entry["verified"] and not entry["matches_runtime"]
    ]


def school_monthly_projection(
    *,
    model: str | None,
    per_route_tokens: dict[str, tuple[int, int]],
    assumptions: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Monthly USD for one school, from measured per-route token counts.

    ``per_route_tokens`` maps a ledger route to ``(prompt_tokens,
    completion_tokens)`` for one answer. Routes without a documented volume
    assumption are reported as ``unprojected`` rather than guessed.
    """
    assumptions = {**SCHOOL_ASSUMPTIONS, **(assumptions or {})}
    students = float(assumptions["students"])
    breakdown: dict[str, dict[str, float]] = {}
    unprojected: list[str] = []
    total = 0.0
    for route, (prompt_tokens, completion_tokens) in sorted(per_route_tokens.items()):
        volume_key = ROUTE_VOLUMES.get(route)
        if volume_key is None:
            unprojected.append(route)
            continue
        per_call_usd = estimate_cost_usd(model, prompt_tokens, completion_tokens)
        # Student routes scale with the student count; teacher routes are already
        # a per-school monthly figure.
        if volume_key == "teacher_generations_per_month":
            monthly_calls = float(assumptions[volume_key])
        else:
            monthly_calls = students * float(assumptions[volume_key])
        cost = per_call_usd * monthly_calls
        total += cost
        breakdown[route] = {
            "per_call_usd": round(per_call_usd, 8),
            "monthly_calls": round(monthly_calls, 2),
            "monthly_usd": round(cost, 6),
        }
    return {
        "model": model,
        "assumptions": assumptions,
        "per_route": breakdown,
        "unprojected_routes": unprojected,
        "monthly_usd": round(total, 6),
        "monthly_usd_per_student": round(total / students, 6) if students else 0.0,
    }


def budget_alert_state(projected_month_usd: float, monthly_budget_usd: float) -> dict[str, Any]:
    """Mirror of the Prometheus projection alert, checkable without Prometheus.

    The rule (deploy/prometheus/alerts.yml) fires when the month-end projection
    exceeds the configured budget and the budget is > 0; an unconfigured
    deployment never alerts, and this function keeps that gate identical.
    """
    if monthly_budget_usd <= 0:
        return {
            "alert": False,
            "gate": "budget_unset",
            "message": "AI_MONTHLY_BUDGET_USD is 0/unset: the projection alert is gated off",
        }
    ratio = projected_month_usd / monthly_budget_usd
    return {
        "alert": projected_month_usd > monthly_budget_usd,
        "gate": "budget_set",
        "budget_usd": monthly_budget_usd,
        "projected_usd": round(projected_month_usd, 6),
        "ratio": round(ratio, 4),
        "message": (
            "projected month-end spend exceeds the configured monthly budget"
            if projected_month_usd > monthly_budget_usd
            else "projected month-end spend is within budget"
        ),
    }
