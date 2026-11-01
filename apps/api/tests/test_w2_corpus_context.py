"""Evidence assembly: token budget, duplicate collapse, stable ordering (RAG-10).

The prompt handed to the generator used to be bounded only by `top_k`, in
chunks the model does not pay for: neither a token budget nor a duplicate
check existed. These tests pin the three properties the fix must have, with
the tokenizer the index uses:

* the cost is measured in production tokens, not characters or words;
* the best-ranked hit survives any budget (a budget must never bury the
  evidence retrieval considered strongest);
* the returned list is a rank-ordered subsequence with duplicates collapsed.
"""

from __future__ import annotations

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.retrieval.context import (
    EVIDENCE_TOKEN_BUDGET,
    assemble_evidence,
    evidence_tokens,
)
from bangla_gpt_api.retrieval.hybrid import tokenize
from bangla_gpt_api.services.tutor import SYSTEM_PROMPT

SENTENCE = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক। "


def _hit(chunk_id: str, text: str, score: float) -> Hit:
    chunk = Chunk(
        id=chunk_id,
        text=text,
        meta=CurriculumMeta(
            curriculum_year=2012, class_level=6, subject="science", book="বিজ্ঞান", source="s"
        ),
    )
    return Hit(chunk=chunk, score=score)


def _hits(count: int, *, sentences: int = 8) -> list[Hit]:
    return [
        _hit(f"c{index}", SENTENCE * sentences + f"অনুচ্ছেদ {index}।", float(count - index))
        for index in range(count)
    ]


def test_evidence_cost_is_measured_in_production_tokens() -> None:
    # "3.5" is one whitespace word but two production tokens, so a word count
    # cannot be the budget unit.
    hit = _hit("n", "গতি 3.5 মিটার। " * 5, 1.0)
    assert evidence_tokens(hit) == len(tokenize(hit.chunk.text))
    assert evidence_tokens(hit) != len(hit.chunk.text.split())


def test_budget_fits_beside_the_system_prompt_in_the_capacity_model() -> None:
    """docs/capacity_plan.md budgets ~1.2k input tokens per LLM call."""
    assert len(tokenize(SYSTEM_PROMPT)) + EVIDENCE_TOKEN_BUDGET <= 1000


def test_all_hits_kept_when_they_fit() -> None:
    hits = _hits(3)
    assert assemble_evidence(hits, budget_tokens=10_000) == hits


def test_budget_drops_the_tail_and_keeps_order() -> None:
    hits = _hits(10)
    kept = assemble_evidence(hits, budget_tokens=evidence_tokens(hits[0]) * 3)
    assert len(kept) == 3
    assert [hit.chunk.id for hit in kept] == ["c0", "c1", "c2"]


def test_best_hit_survives_any_budget() -> None:
    hits = _hits(5)
    kept = assemble_evidence(hits, budget_tokens=1)
    assert [hit.chunk.id for hit in kept] == ["c0"]
    assert kept[0] is hits[0]


def test_duplicate_text_is_paid_for_once() -> None:
    hits = _hits(3)
    duplicate = _hit("dup", hits[0].chunk.text, 0.1)
    kept = assemble_evidence([*hits, duplicate], budget_tokens=10_000)
    assert [hit.chunk.id for hit in kept] == ["c0", "c1", "c2"]


def test_a_duplicate_frees_budget_for_the_next_distinct_hit() -> None:
    hits = _hits(4)
    duplicate = _hit("dup", hits[0].chunk.text, 0.1)
    budget = evidence_tokens(hits[0]) * 4
    without_dupe = assemble_evidence(hits, budget_tokens=budget)
    with_dupe = assemble_evidence([*hits, duplicate], budget_tokens=budget)
    assert len(with_dupe) == len(without_dupe)


def test_empty_input_stays_empty() -> None:
    assert assemble_evidence([]) == []


def test_dedupe_ignores_whitespace_differences() -> None:
    hit = _hit("a", SENTENCE * 3, 1.0)
    spaced = _hit("b", (SENTENCE * 3).replace(" ", "  "), 0.5)
    kept = assemble_evidence([hit, spaced], budget_tokens=10_000)
    assert [item.chunk.id for item in kept] == ["a"]
