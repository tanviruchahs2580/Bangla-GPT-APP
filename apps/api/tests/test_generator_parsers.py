"""Generator payload parsers: JSON booleans must not pass as integers.

``isinstance(True, int)`` is True, so a provider payload carrying
``"answer_index": true`` used to become a "valid" question whose answer sits on
option b, and a worksheet ``"marks": true`` became one mark. Both parsers must
reject booleans, exactly as ``routers/teacher_content.py`` already does on the
question-bank reuse path.
"""

from __future__ import annotations

import json

import pytest

from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.services.generators.question_paper import parse_qp_payload
from bangla_gpt_api.services.generators.worksheet import parse_worksheet_payload

CHAPTER = "কোষ"


def _qp_raw(answer_index: object) -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "text": "কোষ কী?",
                    "options": ["একক", "অণু", "পদার্থ", "শক্তি"],
                    "answer_index": answer_index,
                    "difficulty": "easy",
                    "chapter": CHAPTER,
                }
            ]
        },
        ensure_ascii=False,
    )


def test_qp_parser_rejects_boolean_answer_index() -> None:
    with pytest.raises(ProviderError, match=r"answer_index must be 0-3"):
        parse_qp_payload(_qp_raw(True), [CHAPTER])


def test_qp_parser_still_accepts_real_indices() -> None:
    for index in (0, 3):
        parsed = parse_qp_payload(_qp_raw(index), [CHAPTER])
        assert parsed[0]["answer_index"] == index


def _worksheet_payload() -> dict:
    def question(text: str) -> dict:
        return {
            "text": text,
            "options": ["একক", "অণু", "পদার্থ", "শক্তি"],
            "answer_index": 0,
            "marks": 2,
        }

    return {
        "subject": "science",
        "class_level": 6,
        "chapter": CHAPTER,
        "tiers": [
            {"tier": tier, "questions": [question(f"{tier} প্রশ্ন?")]}
            for tier in ("basic", "intermediate", "advanced")
        ],
        "answer_sheet": [{"ref": "q1", "answer_index": 0, "answer": "একক"}],
    }


def test_worksheet_parser_rejects_boolean_answer_index() -> None:
    payload = _worksheet_payload()
    payload["tiers"][0]["questions"][0]["answer_index"] = True
    with pytest.raises(ProviderError, match=r"answer_index must be 0-3"):
        parse_worksheet_payload(
            json.dumps(payload, ensure_ascii=False), class_level=6, subject="science"
        )


def test_worksheet_parser_rejects_boolean_marks() -> None:
    payload = _worksheet_payload()
    payload["tiers"][2]["questions"][0]["marks"] = True
    with pytest.raises(ProviderError, match=r"marks must be a positive integer"):
        parse_worksheet_payload(
            json.dumps(payload, ensure_ascii=False), class_level=6, subject="science"
        )


def test_worksheet_parser_still_accepts_integer_fields() -> None:
    parsed = parse_worksheet_payload(
        json.dumps(_worksheet_payload(), ensure_ascii=False), class_level=6, subject="science"
    )
    first = parsed["tiers"][0]["questions"][0]
    assert first["answer_index"] == 0 and first["marks"] == 2
