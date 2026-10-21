"""A2-20 / A9-02: the cost model's arithmetic, citations and alert gate.

The tests pin the numbers a report reader would otherwise have to trust: the
cited price matches the table the ledger bills with, a 1,000-answer cost is
exactly the per-answer estimate times 1,000, the projection scales by the
documented volumes, and an unset budget can never alert.
"""

from __future__ import annotations

from bangla_gpt_api.evaluation import cost_model


def test_cited_prices_match_the_runtime_table() -> None:
    table = cost_model.price_table_with_citations()
    gemini = table["gemini-3.1-flash-lite"]
    assert gemini["source"] == "https://ai.google.dev/gemini-api/docs/pricing"
    assert gemini["page_last_updated"] == "2026-10-16"
    assert gemini["accessed"] == "2026-10-19"
    assert gemini["input_usd_per_1m"] == 0.25
    assert gemini["output_usd_per_1m"] == 1.50
    assert gemini["verified"] is True and gemini["matches_runtime"] is True
    assert cost_model.verify_price_table() == [], "no verified price may drift from the ledger"
    # the page this session could not read is marked, not guessed as verified
    assert table["gpt-4o-mini"]["verified"] is False


def test_cost_per_1000_answers_is_the_per_answer_cost_times_a_thousand() -> None:
    # 1000 prompt + 1000 completion tokens on the default model:
    # 0.25/1M * 1000 + 1.50/1M * 1000 = 0.00025 + 0.0015 = 0.00175 per answer
    assert cost_model.cost_per_1000_answers("gemini-3.1-flash-lite", 1000, 1000) == 1.75
    assert cost_model.cost_per_1000_answers("mock", 10_000, 10_000) == 0.0


def test_projection_scales_by_the_documented_volumes() -> None:
    projection = cost_model.school_monthly_projection(
        model="gemini-3.1-flash-lite",
        per_route_tokens={"tutor.ask": (1000, 1000)},
        assumptions={
            "students": 100,
            "student_asks_per_student_per_month": 10,
            "chat_turns_per_student_per_month": 0,
            "teacher_generations_per_month": 0,
        },
    )
    assert projection["per_route"]["tutor.ask"]["monthly_calls"] == 1000
    assert projection["per_route"]["tutor.ask"]["monthly_usd"] == 1.75
    assert projection["monthly_usd"] == 1.75
    assert projection["monthly_usd_per_student"] == 0.0175


def test_routes_without_a_volume_assumption_are_reported_not_guessed() -> None:
    projection = cost_model.school_monthly_projection(
        model="gemini-3.1-flash-lite",
        per_route_tokens={"some/future_route": (100, 100)},
        assumptions={"students": 10},
    )
    assert projection["per_route"] == {}
    assert projection["unprojected_routes"] == ["some/future_route"]
    assert projection["monthly_usd"] == 0.0


def test_budget_alert_gate_matches_the_prometheus_rule() -> None:
    unset = cost_model.budget_alert_state(8.23, 0.0)
    assert unset["alert"] is False and unset["gate"] == "budget_unset"
    over = cost_model.budget_alert_state(8.23, 5.0)
    assert over["alert"] is True and over["ratio"] == round(8.23 / 5.0, 4)
    under = cost_model.budget_alert_state(8.23, 20.0)
    assert under["alert"] is False and under["gate"] == "budget_set"


def test_default_assumptions_are_labelled_planning_figures() -> None:
    assert cost_model.SCHOOL_ASSUMPTIONS["students"] == 400
    # every route the projection knows maps to an assumption key it also knows
    for route, volume_key in cost_model.ROUTE_VOLUMES.items():
        assert volume_key in cost_model.SCHOOL_ASSUMPTIONS, route
