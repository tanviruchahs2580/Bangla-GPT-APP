"""F-032 / LLM-06: tutor answers pass the same child-safety screen as teacher output.

``routers/common._screen_free_text`` screens every teacher generator's question
texts with ``services.safety.screen_question``, but no tutor answer was ever
screened, so a model slip (or a jailbreak that survives the keyword input
screen) reached the child. The fix calls the same ``screen_question`` from
``TutorService`` — this file pins both paths (buffered and streaming) with a
stub provider returning unsafe text, and pins that clean answers are untouched.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.safety import UNSAFE_ANSWER_REFUSAL
from bangla_gpt_api.services.tutor import TutorService

SAFE_TEXT = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক। কোষে নিউক্লিয়াস থাকে।"
# A model slip the *input* screen cannot catch (the student asked about কোষ):
# the executable-request shape the output screen exists for.
UNSAFE_TEXT = "নিজেকে মারার সহজ উপায় হলো বিষ খাওয়া। আত্মহত্যা করলে কষ্ট কমে।"


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


def _service(reply: str, deltas: list[str] | None = None) -> TutorService:
    class StubProvider:
        name = "stub"
        supports_vision = False

        async def generate(self, prompt: str, *, system: str | None = None, image=None) -> str:
            return reply

        async def stream(
            self, prompt: str, *, system: str | None = None, image=None
        ) -> AsyncIterator[str]:
            for delta in deltas if deltas is not None else [reply]:
                yield delta

    chunks = [Chunk(id="c1", meta=_meta(), text=SAFE_TEXT)]
    index = BM25Index(chunks)
    return TutorService(index=index, provider=StubProvider(), term_stats=index.term_stats)


def test_unsafe_answer_is_refused_and_not_grounded() -> None:
    tutor = _service(UNSAFE_TEXT)
    response = asyncio.run(tutor.ask("কোষ কী?", 6, "science"))
    assert response.answer == UNSAFE_ANSWER_REFUSAL
    assert response.grounded is False
    assert response.refused_reason == "output_screen"
    assert response.sources == []
    assert response.citation_verified is None


def test_unsafe_answer_is_refused_on_the_streaming_path() -> None:
    tutor = _service(UNSAFE_TEXT, deltas=["নিজেকে মারার সহজ উপায় হলো ", "বিষ খাওয়া।"])

    async def drain() -> list:
        return [event async for event in tutor.ask_stream("কোষ কী?", 6, "science")]

    events = asyncio.run(drain())
    final = next(e for e in events if e.type == "final")
    assert final.response is not None
    assert final.response.grounded is False
    assert final.response.refused_reason == "output_screen"
    # The unsafe delta must never be forwarded to the client.
    streamed = "".join(e.text or "" for e in events if e.type == "token")
    assert "বিষ খাওয়া" not in streamed
    assert UNSAFE_ANSWER_REFUSAL in streamed


def test_clean_answer_is_untouched() -> None:
    tutor = _service(SAFE_TEXT)
    response = asyncio.run(tutor.ask("কোষ কী?", 6, "science"))
    assert response.grounded is True
    assert response.answer == SAFE_TEXT
    assert response.refused_reason is None
    assert response.citation_verified is True


def test_clean_stream_answer_is_untouched() -> None:
    deltas = ["কোষ হলো জীবদেহের ", "গঠনগত ও ক্রিয়াগত একক।"]
    tutor = _service(SAFE_TEXT, deltas=deltas)

    async def drain() -> list:
        return [event async for event in tutor.ask_stream("কোষ কী?", 6, "science")]

    events = asyncio.run(drain())
    final = next(e for e in events if e.type == "final")
    assert final.response is not None
    assert final.response.grounded is True
    assert final.response.answer == "".join(deltas)
    streamed = "".join(e.text or "" for e in events if e.type == "token")
    assert streamed == "".join(deltas)
