"""History-only token budget for the tutor prompt (Upgrade plan D3).

The defect this closes: conversation history is bounded by a MESSAGE COUNT
(``chat_history_messages`` = 8) and a per-message CHARACTER cap
(``chat_history_message_char_limit`` = 2000), and neither bounds TOKENS.
Spaced-out input can inflate a 2000-char message far past its ordinary
token count, so the existing caps permit an unbounded-token history in the
composed prompt.

Design rules these tests pin:

* the budget is HISTORY-ONLY -- it bounds the prompt copy of conversation
  history and nothing else. There is no total-context ceiling: no provider
  input window exists in Settings, and inventing one would fabricate a
  guarantee. The question, instructions, evidence and image payloads are
  never budgeted and never dropped;
* token counting uses the repo's Bangla-block-aware tokenizer
  (``retrieval.hybrid.tokenize``) -- the same local counting unit
  ``EVIDENCE_TOKEN_BUDGET`` is measured in. The result is a LOCAL
  ESTIMATE, not a provider tokenizer count or a context-window guarantee.
  ``services/costs.py::estimate_tokens`` (chars/4) is a different,
  deliberately conservative COST estimator for the billing ledger;
  mixing the two would make pruning disagree with the accounting it
  exists to protect;
* selection keeps the NEWEST CONTIGUOUS suffix: the scan runs newest to
  oldest and stops at the first item that does not fit -- that item and
  every older item drop, and no older item is ever skipped into the
  retained set. Equality with the budget fits;
* the plan is PRIVACY-SAFE and IMMUTABLE: it carries indices, roles and
  token counts only -- never message text, excerpts, hashes or ids -- and
  planning never mutates the caller's history.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

import pytest
from pydantic import ValidationError

from bangla_gpt_api.retrieval.hybrid import tokenize
from bangla_gpt_api.services.context_budget import (
    BudgetPlan,
    ContextBudgetManager,
    DroppedTurn,
    count_tokens,
)

SENTINEL_A = "গোপন বার্তা এক নমুনা"
SENTINEL_B = "গোপন বার্তা দুই নমুনা"


def _turn(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


# ------------------------------------------------------------- count_tokens --


def test_count_tokens_uses_the_repo_tokenizer() -> None:
    """The manager must share the evidence assembler's counting unit."""
    assert count_tokens("বিশ্বকাপ") == 1
    assert count_tokens("বিশ্বকাপ ফুটবল") == 2
    assert count_tokens("কোষ কী?") == len(tokenize("কোষ কী?"))
    assert count_tokens("") == 0
    assert count_tokens("   \n\t ") == 0


def test_count_tokens_is_a_local_estimate_not_a_guarantee() -> None:
    """Docstring-level pin: the helper is an estimate helper, and the module
    must not pretend provider-token parity. Asserted via the counting unit
    agreement above; this test documents the boundary in the suite."""
    assert count_tokens.__doc__ is not None
    assert "estimate" in count_tokens.__doc__.lower()


# ------------------------------------------------------------------- plan() --


def test_plan_within_budget_retains_every_item() -> None:
    manager = ContextBudgetManager(history_token_budget=1000)
    history = [_turn("user", "প্রশ্ন এক"), _turn("assistant", "উত্তর এক")]

    plan = manager.plan(history)

    assert plan.kept == (0, 1)
    assert plan.dropped == ()
    assert plan.kept_tokens == sum(count_tokens(m["content"]) for m in history)
    assert plan.dropped_tokens == 0


def test_exact_budget_equality_is_retained() -> None:
    total = sum(count_tokens(m["content"]) for m in (_turn("user", "এক দুই তিন"),))
    manager = ContextBudgetManager(history_token_budget=total)

    plan = manager.plan([_turn("user", "এক দুই তিন")])

    assert plan.kept == (0,)
    assert plan.dropped == ()


def test_oldest_first_pruning_keeps_the_newest_contiguous_suffix() -> None:
    """Each turn is 10 tokens; a 25-token budget keeps only the last two."""
    manager = ContextBudgetManager(history_token_budget=25)
    history = [_turn("user", "এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ") for _ in range(4)]
    assert count_tokens(history[0]["content"]) == 10

    plan = manager.plan(history)

    assert plan.kept == (2, 3)
    # dropped metadata is in ORIGINAL chronological order, oldest first
    assert [d.index for d in plan.dropped] == [0, 1]
    assert plan.kept_tokens == 20
    assert plan.dropped_tokens == 20


def test_first_non_fitting_item_stops_the_scan_no_skipping() -> None:
    """A small OLDER item must not be retained by skipping a large one: the
    scan stops at the first item that does not fit."""
    manager = ContextBudgetManager(history_token_budget=10)
    history = [
        _turn("user", "ছোট"),  # 1 token -- would fit, but is older
        _turn("user", "এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ"),  # 10 tokens
        _turn("assistant", "উত্তর"),  # 1 token -- newest, fits
    ]

    plan = manager.plan(history)

    assert plan.kept == (2,)
    assert [d.index for d in plan.dropped] == [0, 1]


def test_newest_item_exceeding_budget_retains_nothing() -> None:
    manager = ContextBudgetManager(history_token_budget=5)
    history = [_turn("user", "এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ")]

    plan = manager.plan(history)

    assert plan.kept == ()
    assert [d.index for d in plan.dropped] == [0]
    assert plan.kept_tokens == 0
    assert plan.dropped_tokens == 10


def test_zero_token_items_follow_the_suffix_rule() -> None:
    """A zero-token item inside the retained suffix stays; a zero-token item
    OLDER than the scan boundary drops with the rest -- no gap is created."""
    manager = ContextBudgetManager(history_token_budget=10)
    inside = [
        _turn("user", ""),
        _turn("user", "এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ"),
        _turn("assistant", ""),
    ]
    plan = manager.plan(inside)
    assert plan.kept == (0, 1, 2)

    outside = [
        _turn("user", ""),
        _turn("user", "এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ এগারো"),
        _turn("assistant", ""),
    ]
    plan = manager.plan(outside)
    assert plan.kept == (2,)
    assert [d.index for d in plan.dropped] == [0, 1]


def test_none_and_empty_history_are_no_ops() -> None:
    manager = ContextBudgetManager(history_token_budget=10)
    for empty in (None, []):
        plan = manager.plan(empty)
        assert plan.kept == ()
        assert plan.dropped == ()
        assert plan.kept_tokens == 0
        assert plan.dropped_tokens == 0


def test_role_defaults_match_the_prompt_builder() -> None:
    """``build_evidence_prompt`` reads ``turn.get("role", "user")``; the
    planner must not invent a different default."""
    manager = ContextBudgetManager(history_token_budget=5)
    plan = manager.plan([{"content": "এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ"}])
    assert plan.dropped[0].role == "user"


def test_non_string_content_fails_loudly() -> None:
    """The runtime schema is ``{"role": str, "content": str}`` (router
    ``_chat_history``). A non-str content must not be stringified, counted
    as zero, or JSON-serialised -- it fails loudly instead."""
    manager = ContextBudgetManager(history_token_budget=100)
    with pytest.raises(TypeError):
        manager.plan([{"role": "user", "content": {"payload": SENTINEL_A}}])  # type: ignore[list-item]


# ------------------------------------------------- purity and determinism --


def test_plan_is_pure_and_deterministic() -> None:
    manager = ContextBudgetManager(history_token_budget=10)
    history = [_turn("user", SENTINEL_A), _turn("assistant", SENTINEL_B)]
    snapshot = [dict(m) for m in history]

    first = manager.plan(history)
    second = manager.plan(history)

    assert history == snapshot, "planning must not mutate the caller's history"
    assert first == second, "the same input must produce the same plan"


def test_plan_does_not_mutate_nested_structures() -> None:
    manager = ContextBudgetManager(history_token_budget=10)
    history: list[dict[str, object]] = [
        {
            "role": "user",
            "content": SENTINEL_A,
            "metadata": {"labels": ["synthetic"]},
        }
    ]
    snapshot = deepcopy(history)

    manager.plan(history)

    assert history == snapshot


# ------------------------------------------------------- privacy of the plan --


def test_dropped_metadata_has_exactly_the_allowed_keys() -> None:
    manager = ContextBudgetManager(history_token_budget=1)
    plan = manager.plan([_turn("user", SENTINEL_A)])

    assert plan.kept == () and plan.dropped != ()
    assert set(asdict(plan.dropped[0])) == {"index", "role", "tokens"}
    assert all(isinstance(i, int) for i in plan.kept)


def test_plan_repr_never_carries_message_content() -> None:
    manager = ContextBudgetManager(history_token_budget=1)
    plan = manager.plan([_turn("user", SENTINEL_A), _turn("assistant", SENTINEL_B)])

    rendered = repr(plan) + repr(plan.dropped[0])
    assert SENTINEL_A not in rendered
    assert SENTINEL_B not in rendered


def test_budget_plan_type_is_frozen() -> None:
    plan = BudgetPlan(kept=(), dropped=(), kept_tokens=0, dropped_tokens=0)
    with pytest.raises(Exception):  # noqa: B017, PT011 - FrozenInstanceError
        plan.kept_tokens = 5  # type: ignore[misc]
    turn = DroppedTurn(index=0, role="user", tokens=1)
    with pytest.raises(Exception):  # noqa: B017, PT011 - FrozenInstanceError
        turn.tokens = 2  # type: ignore[misc]


# ------------------------------------------------------------ construction --


def test_default_budget_is_4000() -> None:
    assert ContextBudgetManager().history_token_budget == 4000


def test_non_positive_budgets_raise_value_error() -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ContextBudgetManager(history_token_budget=bad)


def test_settings_reject_non_positive_and_malformed_values() -> None:
    """The Settings boundary uses the existing pydantic validation system:
    a non-positive or non-integer value fails at config construction, not
    silently at request time."""
    from bangla_gpt_api.config import Settings

    with pytest.raises(ValidationError):
        Settings(env="test", jwt_secret="x" * 32, chat_history_token_budget=0)
    with pytest.raises(ValidationError):
        Settings(env="test", jwt_secret="x" * 32, chat_history_token_budget=-5)
    with pytest.raises(ValidationError):
        Settings(env="test", jwt_secret="x" * 32, chat_history_token_budget="abc")


# --------------------------------------------------------------- wiring pins --


def test_settings_default_matches_the_manager_default() -> None:
    """The shipped value must be one number in one place: a Settings default
    that disagreed with the constructor default would make the effective
    budget depend on whether the app or a test built the service."""
    from bangla_gpt_api.config import Settings

    assert Settings(env="test").chat_history_token_budget == 4000
    assert Settings(env="test").chat_history_token_budget == (
        ContextBudgetManager().history_token_budget
    )


def test_env_var_overrides_the_settings_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators set CHAT_HISTORY_TOKEN_BUDGET; the bare field name is the
    env name (no case conversion, no prefix)."""
    from bangla_gpt_api.config import Settings

    monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "1234")
    assert Settings(env="test").chat_history_token_budget == 1234


def test_templates_document_the_budget() -> None:
    """Both env templates and the compose file must carry the knob, or an
    operator cannot discover or set it (the generic template sweep in
    test_env_example.py covers .env.example; these two are the deploy path)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    assert "CHAT_HISTORY_TOKEN_BUDGET" in (root / ".env.production.example").read_text(
        encoding="utf-8"
    )
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "CHAT_HISTORY_TOKEN_BUDGET:" in compose
    assert "${CHAT_HISTORY_TOKEN_BUDGET:-4000}" in compose


def test_retarget_index_keeps_the_configured_budget() -> None:
    """A hot reindex swaps the corpus, not the operator's budget."""
    from bangla_gpt_api.services.tutor import TutorService

    original = TutorService(
        index=None,
        provider=None,
        history_token_budget=777,  # type: ignore[arg-type]
    )
    swapped = original.retarget_index(None, None)  # type: ignore[arg-type]

    assert original._context_budget.history_token_budget == 777
    assert swapped._context_budget.history_token_budget == 777
