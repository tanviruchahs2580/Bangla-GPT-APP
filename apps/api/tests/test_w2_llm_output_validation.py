"""Semantic validation of structured generator output (LLM-07 / F-118).

The audit's exact defect: `_validate_mcq` and the question-paper parser
required four non-empty options and a 0-3 answer index but never compared the
options, so a worksheet could reach a classroom with two identical choices.
These tests pin the semantic layer: uniqueness, counts against the request,
and the independent recomputation of a numeric answer key.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.evaluation.output_validation import (
    evaluate_expression,
    extract_arithmetic_expression,
    recompute_numeric_answer,
    validate_counts,
    validate_lesson_plan,
    validate_mcq_options,
    validate_question_paper,
    validate_rubric,
    validate_structured_output,
    validate_worksheet,
)

_OPTIONS = ["সাইটোপ্লাজম", "নিউক্লিয়াস", "কোষঝিল্লি", "রাইবোজোম"]


def test_duplicate_options_are_rejected() -> None:
    """F-118: two identical choices must never pass validation."""
    violations = validate_mcq_options(["কোষ", "কোষ", "নিউক্লিয়াস", "ঝিল্লি"], 1)
    assert any("duplicate" in violation for violation in violations)


def test_clean_mcq_has_no_violations() -> None:
    assert validate_mcq_options(_OPTIONS, 0) == []


def test_answer_index_out_of_range_is_reported() -> None:
    violations = validate_mcq_options(_OPTIONS, 4)
    assert any("out of range" in violation for violation in violations)


def test_option_count_and_emptiness_are_reported() -> None:
    assert validate_mcq_options(["ক", "খ", "গ"], 0)
    assert any("non-empty" in v for v in validate_mcq_options(["ক", " ", "গ", "ঘ"], 0))


def test_counts_must_match_the_request() -> None:
    assert validate_counts(8, 8) == []
    assert validate_counts(6, 8) == ["items: requested 8, got 6"]


def _worksheet(tier_counts: list[int]) -> dict:
    return {
        "tiers": [
            {
                "tier": name,
                "questions": [
                    {"text": f"প্রশ্ন {i}", "options": _OPTIONS, "answer_index": 1}
                    for i in range(count)
                ],
            }
            for name, count in zip(("basic", "intermediate", "advanced"), tier_counts, strict=True)
        ]
    }


def test_worksheet_counts_and_option_uniqueness() -> None:
    assert validate_worksheet(_worksheet([3, 3, 3]), questions_per_tier=3) == []
    violations = validate_worksheet(_worksheet([3, 2, 3]), questions_per_tier=3)
    assert any("requested 3, got 2" in violation for violation in violations)


def test_worksheet_duplicate_option_is_caught_per_question() -> None:
    payload = _worksheet([1, 1, 1])
    payload["tiers"][1]["questions"][0]["options"] = ["ক", "ক", "খ", "গ"]
    violations = validate_worksheet(payload)
    assert len(violations) == 1
    assert "duplicate" in violations[0]
    assert "intermediate" in violations[0]


def test_question_paper_marks_and_counts() -> None:
    questions = [
        {"text": "প্রশ্ন", "options": _OPTIONS, "answer_index": 2, "marks": 5, "difficulty": "easy"}
        for _ in range(4)
    ]
    assert validate_question_paper(questions, expected_count=4, total_marks=20) == []
    violations = validate_question_paper(questions, expected_count=5, total_marks=22)
    assert any("requested 5, got 4" in violation for violation in violations)
    assert any("total marks: requested 22, got 20" in violation for violation in violations)


def test_question_paper_difficulty_plan_is_recomputed() -> None:
    questions = [
        {"text": "প্রশ্ন", "options": _OPTIONS, "answer_index": 0, "marks": 1, "difficulty": "easy"},
        {"text": "প্রশ্ন", "options": _OPTIONS, "answer_index": 0, "marks": 1, "difficulty": "hard"},
    ]
    violations = validate_question_paper(questions, counts={"easy": 1, "medium": 1, "hard": 1})
    assert violations == ["question paper difficulty medium: requested 1, got 0"]


def test_rubric_total_is_the_sum_of_criteria() -> None:
    payload = {
        "criteria": [
            {"name": "স্পষ্টতা", "max_marks": 4, "levels": {"high": "a", "medium": "b", "low": "c"}},
            {"name": "নির্ভুলতা", "max_marks": 6, "levels": {"high": "a", "medium": "b", "low": "c"}},
        ],
        "total_marks": 10,
    }
    assert validate_rubric(payload, expected_criteria=2) == []
    payload["total_marks"] = 12
    violations = validate_rubric(payload, expected_criteria=3)
    assert any("total_marks 12 != sum of criteria 10" in violation for violation in violations)
    assert any("requested 3, got 2" in violation for violation in violations)


def test_lesson_plan_sections_must_be_present() -> None:
    payload = {"intro": "শুরু", "objectives": "", "activities": "কাজ"}
    violations = validate_lesson_plan(payload, expected_sections=["intro", "objectives", "closing"])
    assert len(violations) == 2


def test_arithmetic_expression_extraction() -> None:
    assert extract_arithmetic_expression("৩ + ৫ = কত?") == "3 + 5"
    assert extract_arithmetic_expression("12 × 3 = ?") == "12 * 3"
    assert extract_arithmetic_expression("৫০ ÷ ২ = ?") == "50 / 2"
    assert extract_arithmetic_expression("কোষ কী?") is None
    assert extract_arithmetic_expression("সালোকসংশ্লেষণ ব্যাখ্যা করো") is None


def test_expression_evaluation_is_exact_and_bounded() -> None:
    assert evaluate_expression("3 + 5") == 8
    assert evaluate_expression("50 / 2") == 25
    assert evaluate_expression("10 / 4") == 2.5
    # No code execution: only numbers and arithmetic parse.
    assert evaluate_expression("__import__('os').getcwd()") is None
    assert evaluate_expression("3 +") is None


def test_numeric_answer_key_is_recomputed_independently() -> None:
    """The key is derived from the question, not trusted from the model."""
    assert recompute_numeric_answer("৩ + ৫ = কত?", ["৬", "৭", "৮", "৯"], 2) == []
    violations = recompute_numeric_answer("৩ + ৫ = কত?", ["৬", "৭", "৮", "৯"], 0)
    assert len(violations) == 1
    assert "contradicts the recomputed answer 8" in violations[0]


def test_numeric_answer_accepts_units_and_bangla_digits() -> None:
    assert recompute_numeric_answer("১২ × ৩ = কত?", ["৩৬ সেমি", "৩৪", "৩৮", "৩০"], 0) == []


def test_numeric_answer_absent_from_options_is_reported() -> None:
    violations = recompute_numeric_answer("৫ + ৫ = কত?", ["১", "২", "৩", "৪"], 1)
    assert any("not among the options" in violation for violation in violations)


def test_non_arithmetic_question_yields_no_false_violation() -> None:
    assert recompute_numeric_answer("কোষ কী?", _OPTIONS, 3) == []


def test_dispatcher_requires_a_known_kind() -> None:
    assert validate_structured_output("worksheet", _worksheet([1, 1, 1])) == []
    with pytest.raises(KeyError):
        validate_structured_output("unknown_generator", {})
