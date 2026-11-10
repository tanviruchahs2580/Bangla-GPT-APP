"""quiz explain loop: compose the tutor context block for a wrong quiz item."""

from __future__ import annotations

from bangla_gpt_api.schemas import QuizExplainContext

_LETTERS = ("ক", "খ", "গ", "ঘ", "ঙ", "চ")

#: Per-option and chapter caps applied where client text enters the prompt
#: (RAG-001). The request schema bounds the option *count* (2-8) and the
#: chapter length, but not the text of a single option; one multi-KB option
#: would otherwise ride into the trusted instruction block and blow the prompt
#: budget. 200 chars matches the chapter column bound and sits far above any
#: real NCTB option.
MAX_OPTION_CHARS = 200
MAX_CHAPTER_CHARS = 200


def _option_label(options: list[str], idx: int) -> str:
    letter = _LETTERS[idx] if 0 <= idx < len(_LETTERS) else str(idx + 1)
    text = options[idx][:MAX_OPTION_CHARS] if 0 <= idx < len(options) else ""
    return f"{letter}) {text}".strip()


def quiz_explain_instruction(ctx: QuizExplainContext) -> str:
    """Instruction block injected into the tutor prompt for a wrong quiz answer.

    Every client-owned field is length-capped here (delimiter escaping happens
    once at the prompt boundary, services.tutor._prompt_blocks) so a single
    field cannot blow the prompt budget.
    """
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
        lines.append(f"অধ্যায়: {ctx.chapter[:MAX_CHAPTER_CHARS]}")
    lines.append("কেন সঠিক উত্তরটা ঠিক আর শিক্ষার্থীর উত্তরটা ভুল, সহজ ভাষায় বুঝিয়ে বলো।")
    return "\n".join(lines)
