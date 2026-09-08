"""S1.7 — quiz explain loop: compose the tutor context block for a wrong quiz item."""

from __future__ import annotations

from bangla_gpt_api.schemas import QuizExplainContext

_LETTERS = ("ক", "খ", "গ", "ঘ", "ঙ", "চ")


def _option_label(options: list[str], idx: int) -> str:
    letter = _LETTERS[idx] if 0 <= idx < len(_LETTERS) else str(idx + 1)
    text = options[idx] if 0 <= idx < len(options) else ""
    return f"{letter}) {text}".strip()


def quiz_explain_instruction(ctx: QuizExplainContext) -> str:
    """Instruction block injected into the tutor prompt for a wrong quiz answer."""
    lines: list[str] = [
        "শিক্ষার্থী একটি কুইজে এই প্রশ্নে ভুল করেছে। ব্যাখ্যা করে বোঝাও:",
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
    lines.append("কেন সঠিক উত্তরটা ঠিক আর শিক্ষার্থীর উত্তরটা ভুল, সহজ ভাষায় বুঝিয়ে বলো।")
    return "\n".join(lines)
