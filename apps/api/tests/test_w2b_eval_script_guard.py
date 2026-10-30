"""Answer-side script integrity for generated text (F-120/LLM-14).

The defect: the repository's unicode gate (scripts/bn_scan.py) only ever ran
over tracked text, so an Assamese letter or a mangled glyph in a live model's
answer to a child would fail nothing. These tests pin the character rules, the
runtime flag (metric, warning and trace parameter) on both answer paths, and
the fact that a clean Bangla answer is not flagged.
"""

from __future__ import annotations

import asyncio

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation.metrics import script_violations
from bangla_gpt_api.evaluation.observability import AnswerTraceStore
from bangla_gpt_api.metrics import REGISTRY
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService

_QUESTION = "কোষ কী?"
_CLEAN_ANSWER = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক।"
#: U+09F0 (Assamese ra) inside an otherwise Bangla answer -- the codepoint the
#: repo's own bn_scan gate rejects in tracked text.
_ASSAMESE_ANSWER = "কোষ হলো জীব\u09f0দেহের একক।"


class _FixedAnswerProvider(MockLLMProvider):
    """Mock that returns one fixed answer on both the buffered and stream paths."""

    name = "stub-script"

    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def generate(self, prompt, *, system=None, image=None):  # type: ignore[override]
        return self._answer

    async def stream(self, prompt, *, system=None, image=None):  # type: ignore[override]
        yield self._answer


def _tutor(provider: MockLLMProvider, store: AnswerTraceStore) -> TutorService:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    return TutorService(
        index=index,
        provider=provider,
        term_stats=index.term_stats,
        trace_store=store,
    )


def _counter(rule: str) -> float:
    value = REGISTRY.get_sample_value("bgpt_rag_answer_script_violations_total", {"rule": rule})
    return 0.0 if value is None else value


def test_script_violations_flags_each_character_rule() -> None:
    assert script_violations(_CLEAN_ANSWER) == []
    assert script_violations(_ASSAMESE_ANSWER) == ["assamese_letters"]
    # Devanagari letters; the shared danda (U+0964) must not count.
    assert script_violations("কোষ कक्ष।") == ["devanagari_letters"]
    assert script_violations("কোষ। মাটি।") == []
    assert script_violations("কোষ \ufffd একক") == ["replacement_char"]


def test_script_violations_flags_non_nfc_text() -> None:
    # U+09C7 U+09BE is the decomposed form of the NFC letter U+09CB.
    decomposed = "\u09c7\u09be কোষ"
    assert "not_nfc" in script_violations(decomposed)
    assert "not_nfc" not in script_violations(_CLEAN_ANSWER)


def test_buffered_answer_is_flagged_and_traced() -> None:
    before = _counter("assamese_letters")
    store = AnswerTraceStore(capacity=2)
    tutor = _tutor(_FixedAnswerProvider(_ASSAMESE_ANSWER), store)
    response = asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    assert response.grounded is True  # flagged, not refused
    trace = store.recent(1)[0]
    assert trace.parameters["script_violations"] == ["assamese_letters"]
    assert _counter("assamese_letters") == before + 1


def test_streamed_answer_is_flagged_and_traced() -> None:
    before = _counter("assamese_letters")
    store = AnswerTraceStore(capacity=2)
    tutor = _tutor(_FixedAnswerProvider(_ASSAMESE_ANSWER), store)

    async def consume() -> None:
        async for _event in tutor.ask_stream(_QUESTION, 6, "science"):
            pass

    asyncio.run(consume())
    trace = store.recent(1)[0]
    assert trace.parameters["script_violations"] == ["assamese_letters"]
    assert _counter("assamese_letters") == before + 1


def test_clean_answer_is_not_flagged() -> None:
    store = AnswerTraceStore(capacity=2)
    tutor = _tutor(MockLLMProvider(), store)
    assert asyncio.run(tutor.ask(_QUESTION, 6, "science")).grounded is True
    assert "script_violations" not in store.recent(1)[0].parameters
