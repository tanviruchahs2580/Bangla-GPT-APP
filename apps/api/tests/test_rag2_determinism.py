"""AUD-A2-08 / A6-06: per-task determinism, stage timeouts, stream cancellation.

Pinned here:

* both real providers put their documented sampling fields (temperature,
  top_p) into the request and RE-USE the same profile on a retry, so a retry
  cannot change the sampling regime;
* the per-task profiles are explicit and low-temperature (there is no
  creative task in this product);
* ``seed`` is only emitted by a provider that declares vendor support -- the
  configured providers do not (Gemini's GenerationConfig reference does not
  document it, OpenAI's docs were unreachable), and the plumbing is proven
  with a provider that does;
* each pipeline stage is bounded (retrieval and generation have wall-clock
  ceilings and degrade instead of hanging the worker);
* closing the consumer of ``ask_stream`` cancels the upstream provider call.
"""

from __future__ import annotations

import asyncio
import json
from typing import ClassVar

import httpx
import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.base import (
    STAGE_TIMEOUT_SECONDS,
    ProviderError,
    SamplingParams,
    sampling_for,
    stage_timeout_seconds,
)
from bangla_gpt_api.providers.gemini import GeminiProvider
from bangla_gpt_api.providers.openai import OpenAIProvider
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services.tutor import TutorService

CHUNK_TEXT = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক। কোষেই সকল জৈবনিক কাজ ঘটে।"


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="sample",
        chapter="অধ্যায় ১",
        section="কোষ",
        page=3,
    )


def _hit() -> Hit:
    return Hit(chunk=Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT), score=1.0)


class _Index:
    chunks: ClassVar[list[Chunk]] = [Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT)]

    def __init__(self, hits: list[Hit] | None = None) -> None:
        self._hits = hits if hits is not None else [_hit()]

    def search(self, query: str, **_kwargs) -> list[Hit]:
        return list(self._hits)


def _service(provider, **kwargs) -> TutorService:
    return TutorService(
        index=_Index(), provider=provider, min_coverage=0.0, min_score=0.0, **kwargs
    )


# --------------------------------------------------------------- sampling ---
def test_task_sampling_profiles_are_low_temperature_and_explicit() -> None:
    answer = sampling_for("tutor_answer")
    assert answer.temperature <= 0.3 and answer.top_p is not None
    assert sampling_for("tutor_stream") == answer  # a turn is a turn
    assert sampling_for("generation").temperature <= 0.3
    assert sampling_for("unknown-task") == sampling_for("default")


def test_sampling_fields_helper_gates_on_provider_capability() -> None:
    from bangla_gpt_api.providers.base import sampling_kwargs

    class Declared:
        supports_sampling = True

    class Undeclared:
        pass

    assert sampling_kwargs(Declared(), "tutor_answer")["sampling"].temperature <= 0.3
    assert sampling_kwargs(Undeclared(), "tutor_answer") == {}


@pytest.mark.asyncio
async def test_gemini_payload_carries_temperature_and_top_p_on_every_attempt() -> None:
    bodies: list[dict] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        bodies.append(json.loads(request.content.decode()))
        if calls == 1:  # first attempt fails retryably
            return httpx.Response(503, json={"error": {"message": "overloaded"}}, request=request)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}, request=request
        )

    monkeypatch_sleeps: list[float] = []
    provider = GeminiProvider(
        api_key="k",
        model="gemini-3.1-flash-lite",
        timeout_seconds=5.0,
        max_retries=2,
        max_output_tokens=256,
        transport=httpx.MockTransport(handler),
    )
    import bangla_gpt_api.providers.gemini as gemini_module

    async def _no_sleep(seconds: float) -> None:
        monkeypatch_sleeps.append(seconds)

    original_sleep = gemini_module.asyncio.sleep
    gemini_module.asyncio.sleep = _no_sleep
    try:
        assert await provider.generate("q", sampling=sampling_for("tutor_answer")) == "ok"
    finally:
        gemini_module.asyncio.sleep = original_sleep

    assert len(bodies) == 2, "the retryable failure must be retried"
    for body in bodies:
        config = body["generationConfig"]
        assert config["maxOutputTokens"] == 256
        assert config["temperature"] == sampling_for("tutor_answer").temperature
        assert config["topP"] == sampling_for("tutor_answer").top_p
        # seed is NOT sent: this provider does not declare vendor support.
        assert "seed" not in config
    assert len(monkeypatch_sleeps) == 1, "one retry pauses once"


@pytest.mark.asyncio
async def test_gemini_default_profile_is_the_generation_profile() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}, request=request
        )

    provider = GeminiProvider(
        api_key="k",
        model="gemini-3.1-flash-lite",
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    await provider.generate("q")
    expected = sampling_for("generation")
    assert captured["body"]["generationConfig"]["temperature"] == expected.temperature


@pytest.mark.asyncio
async def test_gemini_emits_seed_only_when_the_provider_declares_support() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}, request=request
        )

    class SeedCapableGemini(GeminiProvider):
        supports_seed = True

    provider = SeedCapableGemini(
        api_key="k",
        model="gemini-3.1-flash-lite",
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    await provider.generate("q", sampling=SamplingParams(temperature=0.2, seed=41))
    assert captured[0]["generationConfig"]["seed"] == 41


@pytest.mark.asyncio
async def test_openai_payload_carries_temperature_and_top_p() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            request=request,
        )

    provider = OpenAIProvider(
        api_key="k",
        model="gpt-4o-mini",
        timeout_seconds=5.0,
        max_retries=0,
        max_output_tokens=128,
        transport=httpx.MockTransport(handler),
    )
    await provider.generate("q", sampling=sampling_for("tutor_answer"))
    body = captured["body"]
    assert body["temperature"] == sampling_for("tutor_answer").temperature
    assert body["top_p"] == sampling_for("tutor_answer").top_p
    assert body["max_tokens"] == 128
    assert "seed" not in body  # unverified vendor support -> not sent


@pytest.mark.asyncio
async def test_gemini_stream_path_also_carries_sampling() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}\n\n',
            request=request,
        )

    provider = GeminiProvider(
        api_key="k",
        model="gemini-3.1-flash-lite",
        timeout_seconds=5.0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    chunks = [c async for c in provider.stream("q", sampling=sampling_for("tutor_stream"))]
    assert chunks == ["ok"]
    assert "temperature" in captured["body"]["generationConfig"]


# ---------------------------------------------------------- stage ceilings ---
def test_stage_timeouts_are_declared_and_bounded() -> None:
    assert stage_timeout_seconds("retrieval") <= 10.0
    assert stage_timeout_seconds("generation") <= 45.0
    assert set(STAGE_TIMEOUT_SECONDS) >= {"retrieval", "context", "generation"}
    with pytest.raises(KeyError):
        stage_timeout_seconds("no-such-stage")


@pytest.mark.asyncio
async def test_retrieval_stage_overrun_abstains_instead_of_hanging(monkeypatch) -> None:
    class SlowIndex(_Index):
        def search(self, query: str, **_kwargs) -> list[Hit]:
            import time

            time.sleep(0.5)
            return [_hit()]

    provider = _CapturingProvider()
    service = TutorService(index=SlowIndex(), provider=provider, min_coverage=0.0, min_score=0.0)
    monkeypatch.setattr(
        # C-03: the tutor service is a package now, and each seam imports the
        # knob into its own namespace, so the patch names the seam under test.
        "bangla_gpt_api.services.tutor.retrieval.stage_timeout_seconds",
        lambda stage: 0.01 if stage == "retrieval" else 45.0,
    )
    response = await service.ask("কোষ কী?", 6, "science")
    assert response.refused_reason == "insufficient_evidence"
    assert provider.calls == 0, "no provider call without evidence"


@pytest.mark.asyncio
async def test_generation_stage_overrun_surfaces_as_provider_error(monkeypatch) -> None:
    class HangingProvider:
        name = "hanging"

        async def generate(self, prompt, *, system=None, **kwargs):
            await asyncio.sleep(5)
            return "never"

        def stream(self, prompt, *, system=None, **kwargs):
            raise NotImplementedError

    service = _service(HangingProvider())
    monkeypatch.setattr(
        # C-03: the generation stage's ceiling is read in the generation seam.
        "bangla_gpt_api.services.tutor.generation.stage_timeout_seconds",
        lambda stage: 0.05 if stage == "generation" else 5.0,
    )
    with pytest.raises(ProviderError, match="timed out"):
        await service.ask("কোষ কী?", 6, "science")


class _CapturingProvider:
    name = "capturing"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt, *, system=None, **kwargs):
        self.calls += 1
        return "উত্তর"

    def stream(self, prompt, *, system=None, **kwargs):
        raise NotImplementedError


# ------------------------------------------------------- stream cancellation ---
class _ClosingProvider:
    """Streams slowly and records whether the upstream generator was closed."""

    name = "closing"

    def __init__(self) -> None:
        self.closed = False
        self.finished = False

    async def generate(self, prompt, *, system=None, **kwargs):
        return "উত্তর"

    async def stream(self, prompt, *, system=None, **kwargs):
        try:
            yield "প্রথম "
            await asyncio.sleep(5)  # the consumer never waits for this
            yield "শেষ"
            self.finished = True
        finally:
            self.closed = True


@pytest.mark.asyncio
async def test_closing_the_stream_cancels_the_upstream_provider_call() -> None:
    provider = _ClosingProvider()
    service = _service(provider)
    service.stream_heartbeat_seconds = 0
    stream = service.ask_stream("কোষ কী?", 6, "science")
    first = await stream.__anext__()
    assert first.type == "token"
    await stream.aclose()  # what an SSE client disconnect does
    assert provider.closed is True
    assert provider.finished is False


@pytest.mark.asyncio
async def test_stream_cancellation_through_the_heartbeat_pump() -> None:
    provider = _ClosingProvider()
    service = _service(provider)
    service.stream_heartbeat_seconds = 0.01  # heartbeat path pumps the source
    stream = service.ask_stream("কোষ কী?", 6, "science")
    kinds = []
    for _ in range(6):
        event = await stream.__anext__()
        kinds.append(event.type)
        if event.type == "token":
            break
    assert "token" in kinds
    await stream.aclose()
    assert provider.closed is True
