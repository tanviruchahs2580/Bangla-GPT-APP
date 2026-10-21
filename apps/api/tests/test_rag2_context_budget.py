"""AUD-A2-07 / A5-01: the context builder has a hard token budget.

The evidence block used to be an unbounded concatenation of whatever the
retriever returned. What is pinned here:

* the selection never exceeds the budget, whatever the input;
* duplicate passages are dropped, each kept passage is labelled with its
  stable corpus chunk id, and the rendered block keeps the ``<evidence>``
  delimiters the system prompt rules depend on;
* truncation is deterministic (same input -> same prompt) and always emits
  the ``context_budget_exceeded`` warning;
* the token count comes from a pluggable counter, so a real target-model
  tokenizer replaces the conservative default without touching the builder.
"""

from __future__ import annotations

import logging

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services.context import (
    EVIDENCE_TOKEN_BUDGET,
    HeuristicTokenCounter,
    PassageSelection,
    register_token_counter,
    select_passages,
    token_counter,
)
from bangla_gpt_api.services.tutor import build_evidence_prompt, render_evidence


def _meta(page: int = 1) -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="sample",
        chapter="অধ্যায় ১",
        section="কোষ",
        page=page,
    )


def _hits(count: int, *, chars: int = 200, page_step: int = 0) -> list[Hit]:
    """Distinct passages (each carries a section number, so none is a dupe)."""
    return [
        Hit(
            chunk=Chunk(
                id=f"c{i}",
                meta=_meta(page=1 + i * page_step),
                text=f"কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক (অংশ {i})। " * (chars // 40 + 1),
            ),
            score=1.0 - i / 100,
        )
        for i in range(count)
    ]


def test_selection_never_exceeds_the_budget() -> None:
    selection = select_passages(_hits(40, chars=400), budget_tokens=300)
    assert selection.tokens <= 300
    assert selection.passages, "a 300-token budget must still fit something"
    assert selection.budget_exceeded is True


def test_budget_is_the_default_when_unspecified() -> None:
    selection = select_passages(_hits(3, chars=100))
    assert selection.budget_tokens == EVIDENCE_TOKEN_BUDGET


def test_duplicate_passages_are_dropped() -> None:
    hits = _hits(3)
    duplicate = Hit(chunk=Chunk(id="dup", meta=_meta(), text=hits[0].chunk.text), score=0.5)
    selection = select_passages([*hits, duplicate], budget_tokens=5000)
    assert "dup" in selection.dropped_duplicates
    assert [p.source_id for p in selection.passages] == ["c0", "c1", "c2"]


def test_each_passage_is_labelled_with_its_stable_chunk_id() -> None:
    selection = select_passages(_hits(2), budget_tokens=5000)
    labels = [p.label for p in selection.passages]
    assert labels[0].startswith("[id=c0 |")
    assert "class 6" in labels[0] and "science" in labels[0] and "p.1" in labels[0]
    rendered = render_evidence(_hits(2), budget_tokens=5000)
    assert rendered.passages[0].label == labels[0]


def test_rendered_block_keeps_the_evidence_delimiters_and_ids() -> None:
    prompt = build_evidence_prompt(_hits(2), "কোষ কী?", budget_tokens=5000)
    assert prompt.count("<evidence>") == 2
    assert prompt.count("</evidence>") == 2
    assert "[id=c0 |" in prompt and "[id=c1 |" in prompt


def test_truncation_is_deterministic() -> None:
    hits = _hits(4, chars=900, page_step=1)
    first = build_evidence_prompt(hits, "কোষ কী?", budget_tokens=260)
    second = build_evidence_prompt(hits, "কোষ কী?", budget_tokens=260)
    assert first == second
    selection = render_evidence(hits, budget_tokens=260)
    assert selection.truncated_passages or selection.dropped_over_budget


def test_over_budget_context_logs_a_warning(caplog) -> None:
    import json

    with caplog.at_level(logging.WARNING, logger="bangla_gpt_api.tutor"):
        build_evidence_prompt(_hits(30, chars=600), "কোষ কী?", budget_tokens=250)
    record = next(r for r in caplog.records if "context_budget_exceeded" in r.getMessage())
    payload = json.loads(record.getMessage())
    assert payload["event"] == "context_budget_exceeded"
    assert payload["budget_tokens"] == 250
    assert payload["evidence_tokens"] <= 250
    assert payload["kept"] <= 30
    assert payload["counter"] == "heuristic-2.5cpt"
    assert payload["dropped_over_budget"] + payload["truncated"] > 0


def test_within_budget_context_logs_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="bangla_gpt_api.tutor"):
        build_evidence_prompt(_hits(2, chars=100), "কোষ কী?", budget_tokens=5000)
    assert not [r for r in caplog.records if "context_budget_exceeded" in r.getMessage()]


def test_a_passage_that_cannot_be_cut_cleanly_is_dropped_not_fragmented() -> None:
    # No sentence boundary inside the remaining budget: the builder drops the
    # passage instead of shipping half a sentence as "evidence".
    long_hit = Hit(chunk=Chunk(id="big", meta=_meta(), text="শব্দ " * 400), score=1.0)
    tiny_hit = Hit(chunk=Chunk(id="tiny", meta=_meta(), text="কোষ।"), score=0.5)
    selection = select_passages([long_hit, tiny_hit], budget_tokens=120)
    assert "big" in selection.dropped_over_budget
    assert selection.tokens <= 120
    assert [p.source_id for p in selection.passages] == ["tiny"]


def test_registered_target_tokenizer_changes_measurement() -> None:
    class AlwaysBig:
        name = "always-big"

        def count(self, text: str) -> int:
            return len(text)  # 1 token per character: deliberately pessimistic

    register_token_counter("test-rag2-big", AlwaysBig())
    counter = token_counter("test-rag2-big")
    assert counter.name == "always-big"
    hits = _hits(5, chars=200)
    pessimistic = select_passages(hits, budget_tokens=500, counter=counter)
    default = select_passages(hits, budget_tokens=500)
    assert pessimistic.tokens <= 500
    assert len(pessimistic.passages) < len(default.passages)


def test_default_counter_is_conservative_for_bangla() -> None:
    counter = HeuristicTokenCounter()
    # Bangla script tokenizes denser than ASCII; the default bound must claim
    # MORE tokens than a plain chars/4 estimate would, never fewer.
    bangla = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক।" * 10
    assert counter.count(bangla) > len(bangla) // 4


def test_selection_type_is_public() -> None:
    selection = select_passages([])
    assert isinstance(selection, PassageSelection)
    assert selection.passages == () and selection.tokens == 0
