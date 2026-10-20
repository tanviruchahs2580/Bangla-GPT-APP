"""quiz explain loop: compose the tutor context block for a wrong quiz item.

A5-02: the instruction skeleton (the labels and the closing explain demand)
is a registered prompt (apps/api/prompts/quiz_explain_instruction.md, owner +
SemVer + changelog); this module substitutes only the per-item DATA (the quiz
question, the option lines and the student's answer) into its
``{{quiz_item}}`` placeholder. The rendered block is byte-identical to the
pre-migration inline f-string (pinned by tests/test_rag2_prompt_registry.py).
"""

from __future__ import annotations

from bangla_gpt_api.schemas import QuizExplainContext
from bangla_gpt_api.services.prompt_registry import load_prompt

_LETTERS = ("ক", "খ", "গ", "ঘ", "ঙ", "চ")

_QUIZ_EXPLAIN_TEMPLATE = load_prompt("quiz_explain_instruction").text


def _option_label(options: list[str], idx: int) -> str:
    letter = _LETTERS[idx] if 0 <= idx < len(_LETTERS) else str(idx + 1)
    text = options[idx] if 0 <= idx < len(options) else ""
    return f"{letter}) {text}".strip()


def quiz_explain_instruction(ctx: QuizExplainContext) -> str:
    """Instruction block injected into the tutor prompt for a wrong quiz answer."""
    lines: list[str] = [
        f"প্রশ্ন: {ctx.question}",
    ]
    for i in range(len(ctx.options)):
        lines.append(f"  {_option_label(ctx.options, i)}")
    if ctx.user_answer >= 0:
        my_answer = _option_label(ctx.options, ctx.user_answer)
    else:
        my_answer = "(কোনো উত্তর দেয়নি)"
    lines.append(f"শিক্ষার্থীর উত্তর: {my_answer}")
    lines.append(f"সঠিক উত্তর: {_option_label(ctx.options, ctx.correct_index)}")
    if ctx.chapter:
        lines.append(f"অধ্যায়: {ctx.chapter}")
    return _QUIZ_EXPLAIN_TEMPLATE.replace("{{quiz_item}}", "\n".join(lines))
