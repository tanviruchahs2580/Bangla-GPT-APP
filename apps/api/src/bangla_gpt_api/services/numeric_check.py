"""Programmatic verification for numeric answers (A6-04 / AUD-A2-03).

A tutor answer that states an arithmetic result must not be shown unchecked.
This module extracts a simple arithmetic expression from the *question* (the
trusted side of the check), evaluates it with a whitelisted AST walk over
decimal numbers, and looks for the result in the *answer*.

Verdicts

- ``not_applicable`` -- the question carries no evaluable expression (worded
  problems, ranges like "১৯৭১-১৯৭২" without an arithmetic cue, several
  expressions at once: ambiguity is never resolved by guessing).
- ``verified`` -- the answer states the computed result (within 0.5% to allow
  rounded presentation like 3.14 for 22/7).
- ``mismatch`` -- the answer states a final result (after ``=``/``উত্তর``/
  "answer") that differs from the computed one. Callers treat this as failed
  grounding: show an honest non-answer instead of a wrong number.
- ``unverified`` -- an expression was evaluable but the answer never states a
  final result; the caller labels it rather than claiming verification.

Scope is deliberately narrow: two-operand arithmetic and short chains over
``+ - × * ÷ /`` with Bengali or ASCII digits. Anything wider is
``not_applicable`` -- the module must never manufacture a verdict.
"""

from __future__ import annotations

import ast
import re

__all__ = [
    "BENGALI_TO_ASCII",
    "check_numeric_answer",
    "evaluate_simple_expression",
]

BENGALI_TO_ASCII = str.maketrans(
    "\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef", "0123456789"
)

# "উত্তর" / "answer" followed (within a short phrase) by a number states a
# final result: "উত্তর: ৪২", "উত্তর হবে ২৫", "answer is 48".
_FINAL_MARKER = re.compile(
    "(?:\u0989\u09a4\u09cd\u09a4\u09b0|answer)\\s*[:\\-\u2013]?\\s*[^0-9\\n]{0,12}?([0-9][0-9,.]*)",
    re.IGNORECASE,
)
_EQ_NUMBER = re.compile(r"=\s*([0-9][0-9,.]*)")
_NUMBER = re.compile(r"[0-9]+(?:[.,][0-9]+)?")
_EXPR = re.compile(r"[0-9]+(?:[.,][0-9]+)?(?:\s*[+\-\u00d7x*\u00f7/]\s*[0-9]+(?:[.,][0-9]+)?)+")

# Cues that a "a - b" fragment is meant as arithmetic rather than a range/date.
_ARITHMETIC_CUES = (
    "=",
    "\u0995\u09a4",  # কত (how much)
    "\u09b9\u09bf\u09b8\u09be\u09ac",  # হিসাব (calculation)
    "\u0997\u09a3\u09a8\u09be",  # গণনা (compute)
    "\u09b8\u09ae\u09be\u09a8",  # সমান (equals)
    "\u09af\u09cb\u0997",  # যোগ (addition)
    "\u09ac\u09bf\u09af\u09bc\u09cb\u0997",  # বিয়োগ (subtraction)
    "\u0997\u09c1\u09a3",  # গুণ (multiplication)
    "\u09ad\u09be\u0997",  # ভাগ (division)
)

_ALLOWED_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub)


def _ascii(text: str) -> str:
    return text.translate(BENGALI_TO_ASCII)


def _normalise_number(token: str) -> float | None:
    """Parse "১,২৩৪.৫" / "12.5" / "1,5" (decimal comma) into a float."""
    token = token.strip()
    if not token:
        return None
    if "," in token and "." in token:
        token = token.replace(",", "")
    elif "," in token:
        if re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+", token):
            token = token.replace(",", "")
        else:
            token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _to_python_expression(expr: str) -> str:
    expr = _ascii(expr).replace("\u00d7", "*").replace("\u00f7", "/")
    # "x" as multiplication only when it sits between digits ("3x4").
    expr = re.sub(r"(?<=[0-9])\s*[xX]\s*(?=[0-9])", "*", expr)
    out: list[str] = []
    last = 0
    for match in re.finditer(r"[0-9][0-9,.]*", expr):
        value = _normalise_number(match.group(0))
        if value is None:
            return ""
        out.append(expr[last : match.start()])
        out.append(repr(value))
        last = match.end()
    out.append(expr[last:])
    return "".join(out)


def evaluate_simple_expression(expr: str) -> float | None:
    """Evaluate a whitelisted +-*/ expression; None when it is not evaluable."""
    source = _to_python_expression(_ascii(expr))
    if not source:
        return None
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and not isinstance(node.op, _ALLOWED_OPS):
            return None
        if not isinstance(
            node,
            (
                ast.Expression,
                ast.BinOp,
                ast.UnaryOp,
                ast.Constant,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.USub,
            ),
        ):
            return None
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            return None
    try:
        value = float(eval(compile(tree, "<numeric_check>", "eval")))  # noqa: S307 - whitelisted AST only
    except (ZeroDivisionError, ValueError, TypeError):
        return None
    return value


def _stated_values(answer: str, pattern: re.Pattern[str]) -> list[float]:
    """Numbers the answer states at the pattern's capture position."""
    found: list[float] = []
    for match in pattern.finditer(answer):
        parsed = _normalise_number(match.group(1))
        if parsed is not None:
            found.append(parsed)
    return found


def _matches(values: list[float], value: float, tolerance: float) -> bool:
    return any(abs(item - value) <= tolerance for item in values)


def _single_usable_expression(question: str) -> str | None:
    """The one evaluable expression in the question, or None when ambiguous.

    A bare "a - b" fragment is far more likely a year range or a list
    separator than a computation; without an arithmetic cue it is not a check.
    """
    expressions = [m.group(0) for m in _EXPR.finditer(question)]
    if len(expressions) != 1:
        return None
    expression = expressions[0]
    if any(op in expression for op in ("*", "/", "\u00d7", "\u00f7", "x", "X")):
        return expression
    if any(cue in question for cue in _ARITHMETIC_CUES):
        return expression
    return None


def check_numeric_answer(question: str, answer: str) -> str:
    """Verdict for one turn: verified | mismatch | unverified | not_applicable."""
    q = _ascii(question)
    a = _ascii(answer)
    expression = _single_usable_expression(q)
    if expression is None:
        return "not_applicable"
    value = evaluate_simple_expression(expression)
    if value is None:
        return "not_applicable"
    tolerance = max(0.01, abs(value) * 0.005)

    # An explicit conclusion ("উত্তর: X" / "answer: X") is the claim the child
    # reads; it dominates any correct intermediate "= Y" earlier in the text.
    for pattern in (_FINAL_MARKER, _EQ_NUMBER):
        stated = _stated_values(a, pattern)
        if stated:
            return "verified" if _matches(stated, value, tolerance) else "mismatch"

    numbers = [n for n in (_normalise_number(tok) for tok in _NUMBER.findall(a)) if n is not None]
    return "verified" if _matches(numbers, value, tolerance) else "unverified"
