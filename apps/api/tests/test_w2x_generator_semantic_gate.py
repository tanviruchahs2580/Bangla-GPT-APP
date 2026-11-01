"""F-118: the generators must run the semantic validator, not only the parsers.

The parsers checked field presence, option count and index range -- a
worksheet or question paper with two identical options parsed clean and could
reach a classroom. These tests drive the full ``generate_*`` entry points with
a provider that returns a defective payload, so they fail if the validator
call is ever dropped from the parse site.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.evaluation.output_validation import extract_arithmetic_expression
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services.generators.question_paper import generate_question_paper
from bangla_gpt_api.services.generators.worksheet import generate_worksheet

_EVIDENCE = (
    "কোষ হলো জীবদেহের গঠনমূলক ও কার্যমূলক একক। "
    "টিস্যু একই ধরনের কোষের সমষ্টি। "
    "অঙ্গ কয়েকটি টিস্যু মিলে গঠিত হয়। "
    "তন্ত্র কয়েকটি অঙ্গ নিয়ে গঠিত।"
)

_OPTIONS = ["কোষ", "টিস্যু", "অঙ্গ", "তন্ত্র"]


class _StubIndex:
    """One evidence hit per search, shaped like the real ranking index."""

    def __init__(self) -> None:
        self.chunks = [
            Chunk(
                id="sample-c1",
                text=_EVIDENCE,
                meta=CurriculumMeta(
                    curriculum_year=2026,
                    class_level=6,
                    subject="science",
                    book="sample",
                    source="sample",
                    chapter="কোষ",
                    section="কোষ",
                    page=1,
                ),
            )
        ]

    def search(self, *args, **kwargs) -> list[Hit]:
        return [Hit(chunk=self.chunks[0], score=1.0)]


class _CannedProvider:
    """Returns one fixed payload; the tests mutate it per case."""

    name = "canned"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def _mcq(index: int, *, options: list[str] | None = None) -> dict:
    return {
        "text": f"{_EVIDENCE.split('।')[index % 4]} — প্রশ্ন {index + 1}?",
        "options": list(options or _OPTIONS),
        "answer_index": 0,
        "marks": 2,
    }


def _worksheet_payload(question: dict) -> dict:
    return {
        "subject": "science",
        "class_level": 6,
        "chapter": "কোষ",
        "tiers": [
            {"tier": tier, "questions": [question]}
            for tier in ("basic", "intermediate", "advanced")
        ],
        "answer_sheet": [{"ref": "basic-1", "answer_index": 0, "answer": "কোষ"}],
    }


def test_worksheet_generator_rejects_duplicate_options() -> None:
    """A duplicated MCQ choice must never leave ``generate_worksheet``."""
    provider = _CannedProvider(_worksheet_payload(_mcq(0, options=["কোষ", "কোষ", "অঙ্গ", "তন্ত্র"])))
    with pytest.raises(ProviderError, match="duplicate options"):
        asyncio.run(
            generate_worksheet(
                _StubIndex(),  # type: ignore[arg-type]
                provider,  # type: ignore[arg-type]
                class_level=6,
                subject="science",
                chapter="কোষ",
            )
        )


def test_worksheet_generator_accepts_distinct_options() -> None:
    provider = _CannedProvider(_worksheet_payload(_mcq(0)))
    payload, sources = asyncio.run(
        generate_worksheet(
            _StubIndex(),  # type: ignore[arg-type]
            provider,  # type: ignore[arg-type]
            class_level=6,
            subject="science",
            chapter="কোষ",
        )
    )
    assert len(payload["tiers"]) == 3
    assert sources and sources[0].chapter == "কোষ"


def _qp_payload(count: int, *, duplicate_at: int | None = None) -> dict:
    questions = []
    for index in range(count):
        question = _mcq(index)
        if index == duplicate_at:
            question["options"] = ["কোষ", "কোষ", "অঙ্গ", "তন্ত্র"]
        questions.append(question)
    return {"questions": questions}


def test_question_paper_generator_rejects_duplicate_options() -> None:
    # marks=10 -> plan_counts allocates 5 questions (3 easy / 1 medium / 1 hard).
    provider = _CannedProvider(_qp_payload(5, duplicate_at=1))
    with pytest.raises(ProviderError, match="duplicate options"):
        asyncio.run(
            generate_question_paper(
                _StubIndex(),  # type: ignore[arg-type]
                provider,  # type: ignore[arg-type]
                class_level=6,
                subject="science",
                chapters=["কোষ"],
                marks=10,
                difficulty_pct={"easy": 50, "medium": 30, "hard": 20},
            )
        )


def test_question_paper_generator_rejects_the_wrong_count() -> None:
    """The SPEC line asked for the plan's count; a short paper must fail."""
    provider = _CannedProvider(_qp_payload(2))
    with pytest.raises(ProviderError, match="requested 5, got 2"):
        asyncio.run(
            generate_question_paper(
                _StubIndex(),  # type: ignore[arg-type]
                provider,  # type: ignore[arg-type]
                class_level=6,
                subject="science",
                chapters=["কোষ"],
                marks=10,
                difficulty_pct={"easy": 50, "medium": 30, "hard": 20},
            )
        )


def test_identifier_digits_are_not_arithmetic() -> None:
    """False-positive guard: a suffix like ``variant1-0`` has no answer key.

    The unanchored numeric run parsed ``1-0`` as subtraction and demanded an
    option equal to 1, so an otherwise clean generated paper was refused with
    a violation the model could not have satisfied.
    """
    assert extract_arithmetic_expression("প্রশ্ন variant1-0") is None
    assert extract_arithmetic_expression("COVID-19 কী?") is None
    assert extract_arithmetic_expression("৩ + ৫ = কত?") == "3 + 5"
