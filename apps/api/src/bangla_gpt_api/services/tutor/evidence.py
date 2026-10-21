"""Query normalization, evidence rendering and prompt building: everything
between the retrieved passages and the provider call.

evidence — C-03 split of ``services/tutor.py``: moved verbatim.
"""

from __future__ import annotations

import logging
import unicodedata

from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.metrics import (
    PII_REDACTED_TOTAL,
)
from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)
from bangla_gpt_api.services.context import (
    EVIDENCE_TOKEN_BUDGET,
    PassageSelection,
    TokenCounter,
    render_evidence_block,
    select_passages,
)
from bangla_gpt_api.services.pii import redact_pii
from bangla_gpt_api.services.prompt_registry import (  # noqa: F401 (re-export)
    PROMPTS_DIR_ENV,
    PromptSpec,
    load_prompt,
    prompts_dir,
)
from bangla_gpt_api.services.safety import (
    render_image_text_block as render_image_text_block,
)
from bangla_gpt_api.services.safety import (
    sanitize_evidence as sanitize_evidence,
)
from bangla_gpt_api.services.safety import (
    sanitize_image_text as sanitize_image_text,
)
from bangla_gpt_api.services.tutor.prompts import (  # noqa: F401
    _ZERO_WIDTH_TABLE,
)

logger = logging.getLogger("bangla_gpt_api.tutor")

#: A8-08: the coverage a retrieved passage must carry before it counts as a
#: source the answer leans on (the floor `verify_citation` enforces over the
#: whole evidence, applied per passage); see `_cited_sources` for the numbers.
#:
#: 0.25 -> 0.40 in wave 7, measured before it was changed and recorded in the
#: pre-registration register (thresholds_v1.json, version 3). On the held-out
#: split the section-granularity citation precision was 0.8802 against the 0.95
#: target; the residual was neighbouring sections of the right chapter, which
#: carry the answer's generic vocabulary but far less of it than the passage the
#: answer is actually about. Sweeping the floor over the frozen split showed
#: precisely the shape the metric wants -- 0.25: 0.9086, 0.30: 0.9385, 0.35:
#: 0.9545, 0.40: 0.9655 section precision -- and 0.40 sits on the plateau where
#: the number stops moving, so the threshold is not tuned to the last decimal.
CITATION_SELECTION_FLOOR = 0.40


def normalize_query(text: str) -> str:
    """NFKC-normalize free-text input at the AI boundary.

    Folds mobile-keyboard compatibility variants (precomposed vs decomposed
    Bangla) before safety screening, retrieval, gating and routing, and
    strips zero-width characters (ZWSP/ZWJ/ZWNJ/BOM) — invisible inserts
    inside e.g. ``আত্মহত্যা`` would otherwise defeat the safety and
    injection regexes, which are plain substring patterns. Pure NFKC
    otherwise — no casefold/whitespace rewrite, so the text sent to the LLM
    keeps its original casing and spacing.
    """
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.translate(_ZERO_WIDTH_TABLE)


def render_evidence(
    hits: list,
    *,
    budget_tokens: int = EVIDENCE_TOKEN_BUDGET,
    counter: TokenCounter | None = None,
) -> PassageSelection:
    """Fit retrieved hits into the evidence token budget (A5-01/AUD-A2-07).

    Pure function: dedupe by normalized text, label each passage with its
    stable chunk id and place, then cut deterministically at the budget. The
    caller logs when ``budget_exceeded`` is true; nothing here can grow the
    prompt past ``budget_tokens``.
    """
    return select_passages(hits, budget_tokens=budget_tokens, counter=counter)


def _log_budget_if_needed(selection: PassageSelection) -> None:
    """One warning per turn when the context had to be cut or a chunk dropped."""
    if not selection.budget_exceeded:
        return
    json_log(
        logger,
        logging.WARNING,
        "context_budget_exceeded",
        budget_tokens=selection.budget_tokens,
        evidence_tokens=selection.tokens,
        counter=selection.counter_name,
        kept=len(selection.passages),
        dropped_duplicates=len(selection.dropped_duplicates),
        dropped_over_budget=len(selection.dropped_over_budget),
        truncated=len(selection.truncated_passages),
        kept_ids=[p.source_id for p in selection.passages],
    )


def build_evidence_prompt(
    hits: list,
    question: str,
    history: list[dict[str, str]] | None = None,
    *,
    budget_tokens: int = EVIDENCE_TOKEN_BUDGET,
    counter: TokenCounter | None = None,
) -> str:
    prompt, _ = build_evidence_prompt_with_selection(
        hits, question, history, budget_tokens=budget_tokens, counter=counter
    )
    return prompt


def build_evidence_prompt_with_selection(
    hits: list,
    question: str,
    history: list[dict[str, str]] | None = None,
    *,
    budget_tokens: int = EVIDENCE_TOKEN_BUDGET,
    counter: TokenCounter | None = None,
) -> tuple[str, PassageSelection]:
    """Token-budgeted evidence prompt plus the selection it was built from."""
    # strip pasted PII (phones, emails, NID runs) at the egress
    # boundary — retrieval/gating above run on the raw question (no ranking
    # drift); only the text sent upstream is sanitized, and every removal is
    # metered by kind.
    question, q_counts = redact_pii(question)
    redacted_history: list[dict[str, str]] | None = None
    h_counts: dict[str, int] = {"phone": 0, "email": 0, "nid": 0}
    if history:
        redacted_history = []
        for turn in history:
            content, counts = redact_pii(turn.get("content", ""))
            # History is rendered into the prompt after the evidence blocks —
            # sanitize delimiters exactly like retrieved chunk text.
            content = sanitize_evidence(content)
            for kind, num in counts.items():
                h_counts[kind] += num
            redacted_history.append({"role": turn.get("role", "user"), "content": content})
    for kind in ("phone", "email", "nid"):
        total = q_counts[kind] + h_counts[kind]
        if total:
            PII_REDACTED_TOTAL.labels(kind=kind).inc(total)
    selection = render_evidence(hits, budget_tokens=budget_tokens, counter=counter)
    _log_budget_if_needed(selection)
    blocks = render_evidence_block(selection, sanitizer=sanitize_evidence)
    parts = [f"পাঠ্যবইয়ের অংশ:\n{blocks}"]
    if redacted_history:
        turns = "\n".join(
            f"{'শিক্ষার্থী' if m['role'] == 'user' else 'শিক্ষক'}: {m['content']}"
            for m in redacted_history
        )
        parts.append(f"পূর্ববর্তী কথোপকথন (প্রসঙ্গ):\n{turns}")
    safe_question = sanitize_evidence(question)
    parts.append(f"প্রশ্ন: <user_question>{safe_question}</user_question>")
    return "\n\n".join(parts), selection
