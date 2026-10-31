"""F-052 / RAG-14: citation verification resolves ids and checks per chunk.

The old check concatenated every retrieved chunk and asked a whole-answer stem
overlap >= 0.25; the E-RAG-14 probe showed a fabricated sentence riding on two
shared stems verifying True. The replacement (services/safety.citation_check):
every citation marker must resolve to a retrieved chunk (numeric index or
chunk id), and every declarative sentence must be supported by ONE chunk over
its content terms. The tutor keeps the warn-level response policy; the verdict
is what changes.

Fixtures here are the exact E-RAG-14 probe strings plus the mock/golden flow
(a verbatim-quoting answer must still verify).
"""

from __future__ import annotations

import asyncio

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index, Hit
from bangla_gpt_api.services.safety import citation_check, verify_citation
from bangla_gpt_api.services.tutor import TutorService

EVIDENCE = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক। কোষে নিউক্লিয়াস থাকে।"
# The E-RAG-14 probe strings.
SUPPORTED = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক"
FABRICATED = "কোষ হলো জীবের গঠনগত একক এবং কোষে ক্লোরোপ্লাস্ট থাকে যা সালোকসংশ্লেষণ করে"
PURE_INVENTION = "চাঁদ মঙ্গলগ্রহের একটি উপগ্রহ এবং সেখানে পানি নেই"


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="sample",
        chapter="অধ্যায় ১",
        page=1,
    )


def _hits() -> list[Hit]:
    return [
        Hit(
            chunk=Chunk(id="abc123def456-c6", meta=_meta(), text=EVIDENCE),
            score=1.0,
        )
    ]


def test_fabricated_fact_probe_now_fails_verification() -> None:
    verdict = citation_check(FABRICATED, EVIDENCE, sources=_hits())
    assert verdict.verified is False
    assert verdict.reason == "unsupported_claim"
    assert verify_citation(FABRICATED, EVIDENCE) is False  # legacy 2-arg form


def test_genuine_grounded_answer_passes_verification() -> None:
    verdict = citation_check(SUPPORTED, EVIDENCE, sources=_hits())
    assert verdict.verified is True
    assert verdict.reason == "ok"
    assert verify_citation(SUPPORTED, EVIDENCE) is True


def test_pure_invention_fails() -> None:
    assert verify_citation(PURE_INVENTION, EVIDENCE) is False


def test_short_answer_declines_to_judge() -> None:
    verdict = citation_check("উত্তর", EVIDENCE)
    assert verdict.verified is True and verdict.reason == "insufficient_signal"


def test_substantive_answer_with_no_retrieved_evidence_fails() -> None:
    """Parity with the pre-rewrite verdict: an answer leaning on nothing fails."""
    verdict = citation_check(FABRICATED, "")
    assert verdict.verified is False and verdict.reason == "no_evidence"
    assert verify_citation(FABRICATED, "", sources=[]) is False


def test_empty_answer_with_no_evidence_is_not_judged() -> None:
    assert verify_citation("", "") is True


def test_retrieved_marker_resolves() -> None:
    assert citation_check(f"{SUPPORTED} [1]", EVIDENCE, sources=_hits()).verified is True
    assert citation_check(f"{SUPPORTED} [abc123def456-c6]", EVIDENCE, sources=_hits()).verified


def test_unretrieved_index_fails() -> None:
    verdict = citation_check(f"{SUPPORTED} [2]", EVIDENCE, sources=_hits())
    assert verdict.verified is False and verdict.reason == "unresolved_citation"


def test_fabricated_chunk_id_fails() -> None:
    verdict = citation_check(f"{SUPPORTED} [deadbeef1234-c6]", EVIDENCE, sources=_hits())
    assert verdict.verified is False and verdict.reason == "unresolved_citation"


def test_scaffolding_brackets_are_not_citations() -> None:
    assert citation_check(f"[mock] {SUPPORTED}.", EVIDENCE, sources=_hits()).verified is True


def test_per_chunk_support_not_concatenated_support() -> None:
    """A claim split across two chunks must not verify as one blended answer."""
    hits = [
        Hit(chunk=Chunk(id="a1-a", meta=_meta(), text="কোষ হলো জীবদেহের গঠনগত একক।"), score=1.0),
        Hit(
            chunk=Chunk(
                id="a2-a",
                meta=_meta(),
                text="কোষে ক্লোরোপ্লাস্ট, মাইটোকন্ড্রিয়া ও রাইবোজোম থাকে।",
            ),
            score=1.0,
        ),
    ]
    fabricated = "কোষ হলো জীবদেহের গঠনগত একক এবং ক্লোরোপ্লাস্ট, মাইটোকন্ড্রিয়া ও রাইবোজোম থাকে।"
    # Over the concatenation every term is present; no SINGLE chunk supports
    # the sentence, which is what the per-chunk rule measures.
    assert citation_check(fabricated, " ".join(h.chunk.text for h in hits)).verified is True
    assert (
        citation_check(fabricated, " ".join(h.chunk.text for h in hits), sources=hits).verified
        is False
    )


def test_mock_answer_quoting_evidence_still_verifies() -> None:
    """The hermetic mock/golden flow must keep verifying (warn-level policy)."""
    index = BM25Index([Chunk(id="c1-c6", meta=_meta(), text=EVIDENCE)])
    tutor = TutorService(index=index, provider=MockLLMProvider(), term_stats=index.term_stats)
    response = asyncio.run(tutor.ask("কোষ কী?", 6, "science"))
    assert response.grounded is True
    assert response.citation_verified is True


def test_fabricated_provider_answer_is_flagged_in_the_response() -> None:
    """A fabricated model answer is surfaced (citation_verified=False) and logged."""

    class FabricatingProvider:
        name = "fabricating"
        supports_vision = False

        async def generate(self, prompt: str, *, system: str | None = None, image=None) -> str:
            return FABRICATED

    index = BM25Index([Chunk(id="c1-c6", meta=_meta(), text=EVIDENCE)])
    tutor = TutorService(index=index, provider=FabricatingProvider(), term_stats=index.term_stats)
    response = asyncio.run(tutor.ask("কোষ কী?", 6, "science"))
    assert response.grounded is True  # warn-level policy: the answer is served
    assert response.citation_verified is False  # but the verdict is honest
