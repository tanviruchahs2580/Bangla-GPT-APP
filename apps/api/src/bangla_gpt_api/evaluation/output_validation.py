"""Semantic validation of structured generator output (LLM-07).

The generators already shape-check their payloads (field presence, option
count, answer_index range). Three semantic properties were missing, and each
is a real defect class:

* **counts against the request** -- a worksheet asked for eight questions and
  returning six silently produces a shorter sheet than the teacher specified;
* **unique options** -- two identical MCQ options reach a classroom and read
  as a trick question (the deterministic quiz path samples distinct
  distractors, the model-authored paths did not);
* **numeric answer keys recomputed independently** -- when a question is
  arithmetic, the correct option can be derived from the question text itself
  instead of trusted, which is the only way to catch a model that put the
  right numbers in the wrong order.

Every function returns a list of violation strings (empty means clean) rather
than raising, so a caller can log the whole set at once. The parsers keep the
strict, fail-closed behaviour they had; these checks are the *additional*
semantic layer, and :func:`validate_structured_output` is the dispatcher a
generator (or a test) calls with the parsed payload.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from fractions import Fraction
from typing import Any

#: Bangla digits -> ASCII, for arithmetic recomputation and option matching.
_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
#: Multiplication/division symbols models emit, normalised to ASCII operators.
_OPERATOR_ALIASES = {"×": "*", "x": "*", "X": "*", "÷": "/", "−": "-", "–": "-"}
_OPERATOR_RE = re.compile(r"[0-9+\-*/(). ]+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _to_fraction(text: str) -> Fraction | None:
    """Parse a Bangla/ASCII decimal number into an exact fraction."""
    cleaned = text.translate(_BANGLA_DIGITS).strip()
    if not cleaned:
        return None
    try:
        return Fraction(cleaned)
    except (ValueError, ZeroDivisionError):
        return None


def _normalise_expression(text: str) -> str:
    normalised = text.translate(_BANGLA_DIGITS)
    for symbol, alias in _OPERATOR_ALIASES.items():
        normalised = normalised.replace(symbol, alias)
    return normalised


def extract_arithmetic_expression(text: str) -> str | None:
    """The arithmetic the question asks for, or None when it is not arithmetic.

    Only expressions of digits, operators and parentheses are considered, so a
    prose question yields nothing and the caller simply cannot recompute an
    answer key. Division by zero and unparseable fragments also yield None --
    a false violation would be worse than a missed check.
    """
    normalised = _normalise_expression(text)
    # Prefer the longest operator-bearing run: "৩ + ৫ = কত?" -> "3 + 5 ".
    candidates = [match.group(0) for match in _OPERATOR_RE.finditer(normalised)]
    best = ""
    for candidate in candidates:
        stripped = candidate.strip().rstrip(".").strip()
        if not re.search(r"[+\-*/]", stripped):
            continue
        if len(_NUMBER_RE.findall(stripped)) < 2:
            continue
        if len(stripped) > len(best):
            best = stripped
    return best or None


def evaluate_expression(expression: str) -> Fraction | None:
    """Evaluate ``expression`` exactly, or None when it is not a total function.

    Python's ``eval`` is never used: the expression is parsed with ``ast`` and
    only numbers, binary arithmetic and parentheses are accepted.
    """
    import ast

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    return _eval_node(tree.body)


def _eval_node(node: Any) -> Fraction | None:
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        if value is None:
            return None
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        except ZeroDivisionError:
            return None
    return None


def validate_mcq_options(
    options: list[Any], answer_index: Any, *, label: str = "question"
) -> list[str]:
    """Exactly one correct option among four *distinct* non-empty options.

    The index range is the parsers' job; this function answers the semantic
    questions they never asked: are the options unique, and does the declared
    answer index exist and point at one of them.
    """
    violations: list[str] = []
    texts = [str(option).strip() for option in options]
    if len(texts) != 4:
        violations.append(f"{label}: expected exactly four options, got {len(texts)}")
    if any(not text for text in texts):
        violations.append(f"{label}: options must be non-empty")
    duplicates = {text for text in texts if texts.count(text) > 1}
    if duplicates:
        violations.append(f"{label}: duplicate options {sorted(duplicates)}")
    if not isinstance(answer_index, int) or isinstance(answer_index, bool):
        violations.append(f"{label}: answer_index must be an integer")
    elif not 0 <= answer_index < len(texts):
        violations.append(f"{label}: answer_index {answer_index} out of range")
    return violations


def recompute_numeric_answer(
    question: str, options: list[Any], answer_index: Any, *, label: str = "question"
) -> list[str]:
    """Independently derive the answer key when the question is arithmetic.

    ``৩ + ৫ = ?`` with options (৭, ৮, ৯, ১০) must have its answer at index 1;
    if the payload says otherwise, the option texts prove the key wrong without
    any model call. Non-arithmetic questions return no violations, because
    there is nothing to recompute -- a missed check, never a false one.
    """
    expression = extract_arithmetic_expression(question)
    if expression is None:
        return []
    expected = evaluate_expression(expression)
    if expected is None:
        return []
    texts = [str(option).translate(_BANGLA_DIGITS).strip() for option in options]
    expected_text = str(expected)
    if expected.denominator == 1:
        expected_text = str(expected.numerator)
    matches = [index for index, text in enumerate(texts) if _number_matches(text, expected)]
    if not matches:
        return [f"{label}: arithmetic answer {expected_text} is not among the options {texts}"]
    if answer_index not in matches:
        return [
            f"{label}: declared answer_index {answer_index} contradicts the recomputed "
            f"answer {expected_text} (option index {matches[0]})"
        ]
    return []


def _number_matches(text: str, expected: Fraction) -> bool:
    candidate = _to_fraction(text)
    if candidate is not None and candidate == expected:
        return True
    # "৮ সেমি" / "8 cm": a numeric option with a unit still matches the value.
    match = _NUMBER_RE.search(text)
    if match is None:
        return False
    candidate = _to_fraction(match.group(0))
    return candidate is not None and candidate == expected


def validate_counts(actual: int, requested: int, *, label: str = "items") -> list[str]:
    """The payload must deliver the count the request asked for."""
    if requested < 0:
        return []
    if actual != requested:
        return [f"{label}: requested {requested}, got {actual}"]
    return []


def validate_worksheet(payload: dict, *, questions_per_tier: int | None = None) -> list[str]:
    """Unique options per item and the requested count per tier."""
    violations: list[str] = []
    for tier in payload.get("tiers", []):
        questions = tier.get("questions", [])
        label = f"worksheet tier '{tier.get('tier')}'"
        if questions_per_tier is not None:
            violations += validate_counts(len(questions), questions_per_tier, label=label)
        for index, question in enumerate(questions, start=1):
            violations += validate_mcq_options(
                question.get("options", []),
                question.get("answer_index"),
                label=f"{label} question {index}",
            )
            violations += recompute_numeric_answer(
                str(question.get("text", "")),
                question.get("options", []),
                question.get("answer_index"),
                label=f"{label} question {index}",
            )
    return violations


def validate_question_paper(
    questions: list[dict],
    *,
    expected_count: int | None = None,
    total_marks: int | None = None,
    counts: dict[str, int] | None = None,
) -> list[str]:
    """MCQ semantics, the requested question count and the marks arithmetic."""
    violations: list[str] = []
    if expected_count is not None:
        violations += validate_counts(len(questions), expected_count, label="question paper")
    for index, question in enumerate(questions, start=1):
        label = f"question paper q{index}"
        violations += validate_mcq_options(
            question.get("options", []), question.get("answer_index"), label=label
        )
        violations += recompute_numeric_answer(
            str(question.get("text", "")),
            question.get("options", []),
            question.get("answer_index"),
            label=label,
        )
    if total_marks is not None:
        awarded = sum(int(question.get("marks", 0) or 0) for question in questions)
        violations += validate_counts(awarded, total_marks, label="question paper total marks")
    if counts is not None:
        for level, wanted in counts.items():
            got = sum(1 for question in questions if question.get("difficulty") == level)
            violations += validate_counts(got, wanted, label=f"question paper difficulty {level}")
    return violations


def validate_rubric(payload: dict, *, expected_criteria: int | None = None) -> list[str]:
    """Criterion count against the request and the marks arithmetic."""
    violations: list[str] = []
    criteria = payload.get("criteria", [])
    if expected_criteria is not None:
        violations += validate_counts(len(criteria), expected_criteria, label="rubric criteria")
    total = 0
    for index, criterion in enumerate(criteria, start=1):
        marks = criterion.get("max_marks")
        if not isinstance(marks, int) or marks <= 0:
            violations.append(f"rubric criterion {index}: max_marks must be a positive integer")
        else:
            total += marks
    declared = payload.get("total_marks")
    if isinstance(declared, int) and declared != total:
        violations.append(f"rubric total_marks {declared} != sum of criteria {total}")
    return violations


def validate_lesson_plan(payload: dict, *, expected_sections: list[str] | None = None) -> list[str]:
    """Every requested lesson section has non-empty content."""
    violations: list[str] = []
    for section in expected_sections or []:
        value = payload.get(section)
        if not isinstance(value, str) or not value.strip():
            violations.append(f"lesson plan: section '{section}' is missing or empty")
    return violations


#: Generator-id -> validator, for the dispatcher below.
VALIDATORS: dict[str, Callable[..., list[str]]] = {
    "worksheet": validate_worksheet,
    "question_paper": validate_question_paper,
    "rubric": validate_rubric,
    "lesson_plan": validate_lesson_plan,
}


def validate_structured_output(kind: str, payload: Any, **expectations: Any) -> list[str]:
    """Run the semantic checks for one generator payload.

    Unknown kinds raise: a silent skip would be a check that never runs, which
    is exactly the gap this module exists to close.
    """
    if kind not in VALIDATORS:
        raise KeyError(f"no semantic validator registered for {kind!r}")
    validator = VALIDATORS[kind]
    if kind == "question_paper":
        return validator(list(payload), **expectations)
    return validator(dict(payload), **expectations)
