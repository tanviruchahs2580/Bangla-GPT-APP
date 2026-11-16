"""History-only token budget for the composed tutor prompt (Upgrade D3).

Conversation history reaches the prompt through two caps that do not bound
tokens: ``chat_history_messages`` (a count) and
``chat_history_message_char_limit`` (characters per message). Spaced-out
input inflates a capped message's token count far past its ordinary value,
so the composed prompt could carry an unbounded-token history.

This module bounds ONE thing: the prompt copy of conversation history.
Everything else in the request -- the current question, system/developer
instructions, assembled evidence, tool schemas, image payloads -- is
explicitly out of scope, and there is deliberately NO total-context
ceiling: no provider input window exists in Settings, and inventing one
would fabricate a guarantee the local estimator cannot back.

Counting uses :func:`bangla_gpt_api.retrieval.hybrid.tokenize`, the
Bangla-block-aware tokenizer that also measures ``EVIDENCE_TOKEN_BUDGET``.
Every number produced here is a LOCAL ESTIMATE, not a provider tokenizer
count or a context-window guarantee; ``services.costs.estimate_tokens``
(chars/4) remains the billing ledger's estimator and is untouched.

The plan is privacy-safe by construction: it carries indices, roles and
token counts only -- never message text, excerpts, hashes or identifiers.
Planning is pure: the caller's history list and its message dicts are
never mutated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from bangla_gpt_api.retrieval.hybrid import tokenize

__all__ = ["BudgetPlan", "ContextBudgetManager", "DroppedTurn", "count_tokens"]


def count_tokens(text: str) -> int:
    """Local token estimate for one piece of history text.

    Shares the evidence assembler's counting unit (the Bangla-block-aware
    tokenizer), so pruning and ``EVIDENCE_TOKEN_BUDGET`` measure the same
    thing. This is an estimate for budgeting, not provider-token parity.
    """
    return len(tokenize(text))


@dataclass(frozen=True)
class DroppedTurn:
    """One dropped history item -- metadata only, never content.

    One record maps to one original history-list item (the runtime history
    is a sequence of ``{"role", "content"}`` message dicts; no pairing or
    splitting is applied). ``name`` says "turn" for design continuity; it
    does not imply user/assistant pair grouping.
    """

    index: int
    role: str
    tokens: int


@dataclass(frozen=True)
class BudgetPlan:
    """Outcome of one planning pass -- indices and counts, never text."""

    kept: tuple[int, ...]
    dropped: tuple[DroppedTurn, ...]
    kept_tokens: int
    dropped_tokens: int


class ContextBudgetManager:
    """Plan the newest contiguous history suffix that fits a token budget.

    The scan runs newest to oldest and stops at the first item that does
    not fit: that item and every older item drop, and no older item is
    ever skipped into the retained set (a history with a hole in the
    middle reads to the model as a contradiction). Equality with the
    budget fits. A zero-token item inside the retained suffix stays; one
    older than the scan boundary drops with the rest.
    """

    def __init__(self, history_token_budget: int = 4000) -> None:
        if int(history_token_budget) <= 0:
            raise ValueError(f"history_token_budget must be positive, got {history_token_budget!r}")
        self.history_token_budget = int(history_token_budget)

    def plan(self, history: Sequence[Mapping[str, object]] | None) -> BudgetPlan:
        """Return the keep/drop plan for ``history`` without mutating it.

        ``history`` is the runtime shape produced by the router's
        ``_chat_history``: a sequence of ``{"role", "content"}`` message
        dicts with string content. A missing ``content`` counts as empty
        text (the prompt builder renders it the same way); a non-string
        content fails loudly rather than being stringified, serialised or
        silently counted as zero.
        """
        if not history:
            return BudgetPlan(kept=(), dropped=(), kept_tokens=0, dropped_tokens=0)

        counts: list[int] = []
        for item in history:
            content = item.get("content", "")
            if not isinstance(content, str):
                raise TypeError("history content must be str, got " + type(content).__name__)
            counts.append(count_tokens(content))

        # Newest-to-oldest scan: retain while the running total fits; the
        # first non-fitting item ends the suffix (it and everything older
        # drop). kept_start is the first retained index.
        kept_start = len(counts)
        running = 0
        for i in range(len(counts) - 1, -1, -1):
            if running + counts[i] > self.history_token_budget:
                break
            running += counts[i]
            kept_start = i

        kept = tuple(range(kept_start, len(counts)))
        dropped = tuple(
            DroppedTurn(index=i, role=str(history[i].get("role", "user")), tokens=counts[i])
            for i in range(0, kept_start)
        )
        return BudgetPlan(
            kept=kept,
            dropped=dropped,
            kept_tokens=sum(counts[i] for i in kept),
            dropped_tokens=sum(counts[i] for i in range(0, kept_start)),
        )
