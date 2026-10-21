"""Numeric-answer verification (AUD-A2-03 / A6-04).

Each case is (question, answer, expected verdict). The cases pin the narrow
scope contract: the module must not guess. It resolves simple arithmetic with
Bengali or ASCII digits, tolerates rounded presentation, calls a stated wrong
result a mismatch, labels a result-less answer unverified, and stays out of
worded problems, date ranges and multi-expression questions.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.services.numeric_check import check_numeric_answer

CASES = [
    # Bengali digits, addition, exact result after "="
    ("১২ + ৩০ = কত?", "১২ + ৩০ = ৪২। উত্তর: ৪২", "verified"),
    # ASCII digits, multiplication
    ("12 * 4 = ?", "12 * 4 = 48.", "verified"),
    # Bengali multiplication sign, stated wrong result after the marker
    ("৫ × ৬ = কত?", "৫ × ৬ = ৩০ হলে উত্তর হবে ২৫।", "mismatch"),
    # Rounded presentation of a non-terminating quotient
    ("২২ ÷ ৭ = কত?", "২২ ÷ ৭ ≈ ৩.১৪", "verified"),
    # Evaluable expression, but the answer never states the result
    ("১২ + ৩০ = কত?", "যোগ করার সময় একক ও দশক আলাদা করে বসাও।", "unverified"),
    # Worded problem: no symbolic expression -> out of scope
    ("করিমের কাছে ৫টি আম আছে, তিনি ৩টি খেলেন। কতটি রইল?", "২টি আম থাকল।", "not_applicable"),
    # Year range without an arithmetic cue must not be evaluated
    ("১৯৪৫-১৯৭১ সালে কী ঘটেছিল?", "সূচনা ও মুক্তিযুদ্ধের কাল।", "not_applicable"),
    # Two expressions: ambiguity is never resolved by guessing
    ("২ + ৩ এবং ৪ × ৫ কত?", "৫ এবং ২০", "not_applicable"),
    # Division by zero
    ("৫ ÷ ০ = কত?", "শূন্য দিয়ে ভাগ করা যায় না।", "not_applicable"),
    # Symbolic subtraction with a Bengali arithmetic cue
    ("১৯৭১ - ১৯৪৫ = কত?", "= ২৬", "verified"),
    # Worded subtraction (numbers separated by words) is out of scope
    ("১৯৭১ থেকে ১৯৪৫ বিয়োগ করলে কত?", "২৬", "not_applicable"),
    # The explicit conclusion dominates a correct intermediate "="
    ("৫ × ৬ = কত?", "৫ × ৬ = ৩০, কিন্তু উত্তর: ২৫", "mismatch"),
    # Thousands separators in both sides
    ("১,০০০ + ৫০০ = কত?", "= ১,৫০০", "verified"),
    # Percent-style decimal comma is not a decimal here; answer uses a dot
    ("৩ × ১.৫ = কত?", "৩ × ১.৫ = ৪.৫", "verified"),
    # Empty answer
    ("৭ + ৭ = কত?", "", "unverified"),
]


@pytest.mark.parametrize(("question", "answer", "expected"), CASES)
def test_numeric_verdicts(question: str, answer: str, expected: str) -> None:
    assert check_numeric_answer(question, answer) == expected


def test_evaluator_rejects_non_arithmetic() -> None:
    from bangla_gpt_api.services.numeric_check import evaluate_simple_expression

    assert evaluate_simple_expression("১ + ২") == 3.0
    assert evaluate_simple_expression("__import__('os')") is None
    assert evaluate_simple_expression("১ ** ২") is None
    assert evaluate_simple_expression("১ ÷ ০") is None


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
