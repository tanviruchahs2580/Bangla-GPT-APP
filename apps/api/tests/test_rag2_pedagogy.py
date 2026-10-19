"""AUD-A2-19 / A11-03, A11-04: pedagogy guardrails and strategy-chip proof.

Live-model A/B is BLOCKED (no LLM key exists on this host; AUD-A2-01), so the
proof here is at the RECORDED-REQUEST layer: what the app actually sends.

* homework-like prompts receive the hint-first instruction (configurable, with
  the flag resolved from settings/env, and off means off);
* study-mode turns receive the step-by-step instruction; other goals do not;
* the strategy chips and the re-teach rotation change the recorded request --
  the instruction reaches the prompt, in front of the untrusted evidence,
  differs per strategy, and the persisted strategy shows up in the context --
  which is the strongest honest statement without a model in the loop.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services import teach_strategy
from bangla_gpt_api.services.context import RequestContext
from bangla_gpt_api.services.tutor import (
    GOAL_STUDY,
    HINT_FIRST_ENV,
    HINT_FIRST_INSTRUCTION,
    STUDY_STEPS_INSTRUCTION,
    TutorService,
    hint_first_enabled,
    is_homework_like,
)

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


class _RecordingProvider:
    name = "recording"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt, *, system=None, **kwargs):
        self.prompts.append(prompt)
        return CHUNK_TEXT

    async def stream(self, prompt, *, system=None, **kwargs):
        self.prompts.append(prompt)
        yield CHUNK_TEXT


class _Index:
    chunks: ClassVar[list[Chunk]] = [Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT)]

    def search(self, query: str, **_kwargs) -> list[Hit]:
        return [Hit(chunk=self.chunks[0], score=1.0)]


def _service(provider, **kwargs) -> TutorService:
    return TutorService(
        index=_Index(), provider=provider, min_coverage=0.0, min_score=0.0, **kwargs
    )


async def _ask(service: TutorService, question: str, **kwargs) -> str:
    await service.ask(question, 6, "science", **kwargs)
    return service.provider.prompts[-1]


# ------------------------------------------------------------ hint-first ----
def test_homework_cues_are_recognised_and_normal_questions_are_not() -> None:
    for cue in (
        "আমার হোমওয়ার্কের উত্তর দাও",
        "বাড়ির কাজটি সমাধান করে দাও",
        "please solve it for me",
        "home work help",
        "এই অ্যাসাইনমেন্টের উত্তর লিখে দাও",
    ):
        assert is_homework_like(cue), cue
    for normal in ("সালোকসংশ্লেষণ কী?", "ভগ্নাংশ কী? উদাহরণ দাও।", "কোষ কী?"):
        assert not is_homework_like(normal), normal


@pytest.mark.asyncio
async def test_homework_like_prompt_carries_the_hint_first_instruction() -> None:
    provider = _RecordingProvider()
    prompt = await _ask(_service(provider), "আমার হোমওয়ার্কের উত্তর দাও: কোষ কী?")
    assert HINT_FIRST_INSTRUCTION in prompt
    assert prompt.index(HINT_FIRST_INSTRUCTION) < prompt.index("<evidence>")


@pytest.mark.asyncio
async def test_normal_question_does_not_carry_hint_first() -> None:
    provider = _RecordingProvider()
    prompt = await _ask(_service(provider), "কোষ কী?")
    assert HINT_FIRST_INSTRUCTION not in prompt


@pytest.mark.asyncio
async def test_hint_first_is_configurable_off_per_service() -> None:
    provider = _RecordingProvider()
    prompt = await _ask(_service(provider, hint_first=False), "আমার হোমওয়ার্কের উত্তর দাও: কোষ কী?")
    assert HINT_FIRST_INSTRUCTION not in prompt


def test_hint_first_flag_resolution_order(monkeypatch) -> None:
    class _Settings:
        def __init__(self, value: object) -> None:
            self.tutor_hint_first = value

    # settings field wins over the environment
    monkeypatch.setenv(HINT_FIRST_ENV, "0")
    assert hint_first_enabled(_Settings(True)) is True
    assert hint_first_enabled(_Settings(False)) is False
    # environment when settings does not carry the field
    assert hint_first_enabled(None) is False
    monkeypatch.setenv(HINT_FIRST_ENV, "yes")
    assert hint_first_enabled(None) is True
    # default when neither is set (hint-first is this product's pedagogy)
    monkeypatch.delenv(HINT_FIRST_ENV, raising=False)
    assert hint_first_enabled(None) is True


# ------------------------------------------------------------ study mode ----
@pytest.mark.asyncio
async def test_study_mode_turn_carries_the_step_instruction() -> None:
    provider = _RecordingProvider()
    context = RequestContext(role="student", class_level=6, subject="science", goal=GOAL_STUDY)
    prompt = await _ask(_service(provider), "কোষ কী?", context=context)
    assert STUDY_STEPS_INSTRUCTION in prompt
    assert "goal=study" in prompt
    assert prompt.index(STUDY_STEPS_INSTRUCTION) < prompt.index("<evidence>")


@pytest.mark.asyncio
async def test_non_study_goal_has_no_step_instruction() -> None:
    provider = _RecordingProvider()
    context = RequestContext(role="student", class_level=6, subject="science", goal="chat")
    prompt = await _ask(_service(provider), "কোষ কী?", context=context)
    assert STUDY_STEPS_INSTRUCTION not in prompt


# --------------------------------------------------- strategy chips (A11-04) --
@pytest.mark.asyncio
async def test_strategy_chip_instruction_reaches_the_prompt_and_differs() -> None:
    provider = _RecordingProvider()
    service = _service(provider)
    by_strategy: dict[str, str] = {}
    for key in ("steps", "example", "simple"):
        by_strategy[key] = await _ask(
            service,
            "কোষ কী?",
            extra_instruction=teach_strategy.explicit_strategy_instruction(key),
        )
    steps_prompt = by_strategy["steps"]
    assert teach_strategy.explicit_strategy_instruction("steps") in steps_prompt
    assert steps_prompt.index("শিক্ষক-নির্দেশ") < steps_prompt.index("<evidence>")
    assert len(set(by_strategy.values())) == 3, "each chip must change the request"


@pytest.mark.asyncio
async def test_reteach_rotation_changes_the_request_between_turns() -> None:
    provider = _RecordingProvider()
    service = _service(provider)
    key1, instruction1 = teach_strategy.reteach_instruction(None)
    first = await _ask(service, "কোষ কী?", extra_instruction=instruction1)
    key2, instruction2 = teach_strategy.reteach_instruction(key1)
    second = await _ask(service, "কোষ কী?", extra_instruction=instruction2)
    assert key2 != key1
    assert instruction1 in first and instruction2 in second
    assert first != second


@pytest.mark.asyncio
async def test_persisted_strategy_is_visible_in_the_next_request_context() -> None:
    provider = _RecordingProvider()
    service = _service(provider)
    context = RequestContext(
        role="student",
        class_level=6,
        subject="science",
        goal="reteach",
        history_summary="2 turns, strategy=example",
    )
    prompt = await _ask(service, "কোষ কী?", context=context)
    assert "history=2 turns, strategy=example" in prompt
    assert "goal=reteach" in prompt


@pytest.mark.asyncio
async def test_hint_first_and_strategy_instructions_coexist_in_order() -> None:
    provider = _RecordingProvider()
    strategy = teach_strategy.explicit_strategy_instruction("steps")
    prompt = await _ask(
        _service(provider), "আমার হোমওয়ার্কটি সমাধান করে দাও: কোষ কী?", extra_instruction=strategy
    )
    assert strategy in prompt and HINT_FIRST_INSTRUCTION in prompt
    assert prompt.index(strategy) < prompt.index(HINT_FIRST_INSTRUCTION)
    assert prompt.index(HINT_FIRST_INSTRUCTION) < prompt.index("<evidence>")
