"""Evidence assembly for the generation prompt: budget, dedupe, ordering.

F-129/RAG-10. The tutor used to hand the generator an unbounded list of
retrieved chunks: `top_k` bounded the count, nothing bounded the size, and a
retrieved duplicate occupied budget that a distinct passage needed.

Two rules, both measured with the tokenizer the index uses
(`retrieval.hybrid.tokenize`), not an approximation:

* the best-ranked hit is always kept, so a budget can never bury the evidence
  the retrieval stage considered strongest;
* hits are deduplicated by normalized text before the budget is applied, so
  the same passage reached through two sources (or two class expansions) is
  paid for once and the next distinct hit takes the freed budget.

The budget is a *selection* budget, not a truncation: a hit is kept whole or
dropped. Truncating a Bangla passage mid-sentence would show the model a
different text than the student's citation points at.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from bangla_gpt_api.retrieval.bm25 import Hit, indexable_text, tokenize
from bangla_gpt_api.retrieval.normalize import collapse_whitespace

#: Evidence budget in production tokens. Derived from the capacity model
#: (docs/capacity_plan.md §2: ~1.2k input tokens per LLM call) minus the
#: measured fixed parts: system prompt 231 tokens and ~250 tokens of
#: question, history and app instructions. 770 rounds to a budget of 768.
EVIDENCE_TOKEN_BUDGET = 768


def evidence_tokens(hit: Hit) -> int:
    """Tokens the hit contributes to the prompt (the text shown to the model)."""
    return len(tokenize(hit.chunk.text))


def _text_key(hit: Hit) -> str:
    """Dedupe key: the normalized text the generator would actually read.

    Deliberately not the indexable text (heading + body): two hits whose
    headings differ but whose bodies are identical are the same evidence for
    answering, and the heading still travels in the citation metadata.
    """
    return collapse_whitespace(indexable_text(hit.chunk))


def assemble_evidence(
    hits: Sequence[Hit],
    *,
    budget_tokens: int = EVIDENCE_TOKEN_BUDGET,
    per_hit_tokens: Callable[[Hit], int] = evidence_tokens,
) -> list[Hit]:
    """Rank-ordered evidence within ``budget_tokens``, duplicates collapsed.

    The result is a subsequence of ``hits`` (order preserved): the generator
    must never see a lower-ranked passage ahead of a higher-ranked one.
    A hit that alone exceeds the budget is still kept when it is the best hit
    (an empty evidence set would force a refusal on a question that retrieved
    an answer), and dropped otherwise.
    """
    if not hits:
        return []
    selected: list[Hit] = []
    seen: set[str] = set()
    used = 0
    for position, hit in enumerate(hits):
        key = _text_key(hit)
        if key in seen:
            continue
        cost = per_hit_tokens(hit)
        is_best = position == 0
        if used + cost > budget_tokens and not is_best:
            continue
        selected.append(hit)
        seen.add(key)
        used += cost
    return selected
