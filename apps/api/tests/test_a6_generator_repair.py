"""A6-03: structured generation is schema-validated with ONE bounded repair.

Before this loop, a malformed model reply failed the generator immediately
(502, nothing persisted -- already pinned in test_content_engine). The audit
found the missing half: no bounded repair/retry carrying validation feedback.
Pinned here by fault injection:

* a first malformed reply is repaired with exactly ONE follow-up call whose
  prompt quotes the validation error and sits AHEAD of the evidence;
* a repaired reply flows on unchanged (the generator returns the parsed
  payload);
* two malformed replies (or a repair attempt that is itself malformed) raise
  ProviderError, so the invalid payload never reaches the caller/DB/UI;
* the repair loop never runs a second repair.

Bengali literals are Unicode escapes only (repo rule for new files).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services.generators._json import generate_validated, repair_prompt
from bangla_gpt_api.services.generators.worksheet import (
    WORKSHEET_SYSTEM_PROMPT,
    generate_worksheet,
    parse_worksheet_payload,
)

CHUNK_TEXT = "\u0995\u09cb\u09b7 \u099c\u09c0\u09ac\u09a6\u09c7\u09b9\u09c7\u09b0 \u098f\u0995\u0995\u0964"  #


class _ScriptedProvider:
    """Replays one reply per call; records every prompt it saw."""

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, system: str | None = None, **_kwargs) -> str:
        self.calls.append(prompt)
        return self.replies.pop(0)


def _valid_worksheet(subject: str = "science", class_level: int = 6) -> str:
    payload = {
        "subject": subject,
        "class_level": class_level,
        "chapter": "ch1",
        "tiers": [
            {
                "tier": tier,
                "questions": [
                    {
                        "text": f"Q-{tier}",
                        "options": ["a", "b", "c", "d"],
                        "answer_index": 0,
                        "marks": 1,
                    }
                ],
            }
            for tier in ("basic", "intermediate", "advanced")
        ],
        "answer_sheet": [{"ref": "Q-basic", "answer_index": 0, "answer": "a"}],
    }
    return json.dumps(payload)


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="book",
        source="sample",
        chapter="ch1",
        section="s1",
        page=1,
    )


class _Index:
    def search(self, _query, **_kwargs):
        return [Hit(chunk=Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT), score=1.0)]


def _parse(text: str) -> dict:
    return parse_worksheet_payload(text, class_level=6, subject="science")


def test_one_malformed_reply_is_repaired_with_feedback_and_reused() -> None:
    provider = _ScriptedProvider(["not json at all", _valid_worksheet()])
    result = asyncio.run(
        generate_validated(
            provider,
            "TARGET\n\n<evidence>\nchunk text\n</evidence>",
            system=WORKSHEET_SYSTEM_PROMPT,
            parse=_parse,
            label="worksheet",
        )
    )
    assert result["tiers"]
    assert len(provider.calls) == 2, "exactly one repair call"
    repair_call = provider.calls[1]
    assert repair_call.index("no JSON object") < repair_call.index("<evidence>"), (
        "the validation feedback must sit ahead of the untrusted evidence"
    )


def test_a_valid_reply_never_triggers_a_repair_call() -> None:
    provider = _ScriptedProvider([_valid_worksheet()])
    asyncio.run(
        generate_validated(
            provider,
            "prompt",
            system=WORKSHEET_SYSTEM_PROMPT,
            parse=_parse,
            label="worksheet",
        )
    )
    assert len(provider.calls) == 1


def test_two_malformed_replies_raise_and_do_not_repair_twice() -> None:
    provider = _ScriptedProvider(["garbage one", "garbage two"])
    with pytest.raises(ProviderError, match="after one repair"):
        asyncio.run(
            generate_validated(
                provider,
                "prompt",
                system=WORKSHEET_SYSTEM_PROMPT,
                parse=_parse,
                label="worksheet",
            )
        )
    assert len(provider.calls) == 2, "bounded: never a third attempt"


def test_repair_prompt_is_bounded_and_collapses_whitespace() -> None:
    long_error = "x" * 500 + "\n\nmore"
    prompt = repair_prompt("BODY", long_error)
    assert prompt.endswith("BODY")
    assert "\n\n\n" not in prompt
    assert len(prompt) < 700


def test_worksheet_generator_end_to_end_with_one_repair() -> None:
    provider = _ScriptedProvider(["not json", _valid_worksheet()])
    payload, sources = asyncio.run(
        generate_worksheet(_Index(), provider, class_level=6, subject="science", chapter="ch1")
    )
    assert payload["subject"] == "science" and payload["tiers"]
    assert len(sources) == 1
    assert len(provider.calls) == 2


def test_worksheet_generator_still_fails_hard_when_repair_also_fails() -> None:
    provider = _ScriptedProvider(["junk", "junk again"])
    with pytest.raises(ProviderError, match="after one repair"):
        asyncio.run(
            generate_worksheet(_Index(), provider, class_level=6, subject="science", chapter="ch1")
        )


def test_every_generator_call_is_traced_with_the_registry_prompt_version(monkeypatch) -> None:
    """A1-04: no untraced provider call -- first attempts and repairs both."""
    events: list[tuple[str, dict]] = []

    def _capture(event: str, **fields: object) -> None:
        events.append((event, fields))

    import bangla_gpt_api.services.generators._json as json_mod

    monkeypatch.setattr(json_mod, "trace_event", _capture)

    asyncio.run(
        generate_worksheet(
            _Index(),
            _ScriptedProvider([_valid_worksheet()]),
            class_level=6,
            subject="science",
            chapter="ch1",
        )
    )
    assert [e[0] for e in events] == ["generation"]
    fields = events[0][1]
    assert fields["route"] == "generator:worksheet"
    assert str(fields["prompt_version"]).startswith("worksheet_system@")
    assert fields["repair"] is False

    events.clear()
    asyncio.run(
        generate_worksheet(
            _Index(),
            _ScriptedProvider(["junk", _valid_worksheet()]),
            class_level=6,
            subject="science",
            chapter="ch1",
        )
    )
    assert [e[1]["repair"] for e in events] == [False, True]
