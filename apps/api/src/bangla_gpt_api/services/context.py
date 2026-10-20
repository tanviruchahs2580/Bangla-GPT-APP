"""Education Context Engine.

ONE central place builds the education context attached to every AI call:
who is asking (role/class), what topic (subject/chapter), why (goal), how
much conversation precedes it (history_summary) and what we already know
about mastery (mastery_snapshot).

It also owns the *evidence context budget* (AUD-A2-07 / A5-01): retrieved
passages are counted in tokens with the target tokenizer, deduplicated,
labelled with their stable chunk id and cut to a hard token cap before they
reach a prompt. Deterministic selection: the same hits always produce the
same block, independent of dict order or timing.

Rules honoured here:
- The context is TRUSTED APP TEXT injected into the USER prompt; system
  prompts stay byte-identical so their secrecy/injection protections
  never move or change.
- log_fields is safe for observability: counts, ids, concepts -- never
  message content or PII (, same discipline as product_event props).
"""

import math
import re
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

# --- the central structure ------------------------------------------------


@dataclass(frozen=True)
class RequestContext:
    """Everything the AI layer is allowed to know about one request."""

    role: str
    class_level: int
    subject: str | None = None
    chapter_id: str | None = None
    goal: str = "question"  # question | chat | reteach | quiz_explain |...
    history_summary: str = "0 turns"  # counts/strategy only, never content
    mastery_snapshot: Mapping[str, float] = field(default_factory=dict)
    # gated personalization line (weak-chapter facts + explanation
    # style directive). Empty string -> NO personalization is rendered; the
    # caller leaves it empty when the student disabled their learning memory.
    memory_block: str = ""

    def log_fields(self) -> dict[str, object]:
        """JSON-safe observability fields (eval + cost attribution)."""
        return {
            "ai_role": self.role,
            "ai_class_level": self.class_level,
            "ai_subject": self.subject or "",
            "ai_chapter": self.chapter_id or "",
            "ai_goal": self.goal,
            "ai_history": self.history_summary,
            "ai_mastery_concepts": len(self.mastery_snapshot),
        }

    def render_block(self) -> str:
        """Trusted app-text header prepended to the USER prompt.

        ASCII keys keep it stable for tests and provider-agnostic; the model
        sees structured education context, never raw user history.

        A5-04/A5-05 defence in depth: ``memory_block`` is delimited data even
        though it is app-composed (weak-chapter names come from the corpus,
        style directives from a fixed vocabulary). A value that somehow
        carried a prompt delimiter (``</education-context>``, ``<evidence>``,
        an instruction-shaped tag) is neutralized here, so memory can never
        close this block, open the evidence block, or smuggle instructions
        into the trusted region.
        """
        mastery = (
            ",".join(f"{c}={p:.0f}" for c, p in sorted(self.mastery_snapshot.items()))
            if self.mastery_snapshot
            else "none"
        )
        # the personalization line renders ONLY when the caller put
        # content in memory_block (memory enabled). Byte-identical output
        # when empty -- existing consumers/tests are unaffected.
        memory_line = (
            f"\nmemory: {_sanitize_block_text(self.memory_block)}" if self.memory_block else ""
        )
        return (
            "[education-context]\n"
            f"role={self.role} class_level={self.class_level} subject={self.subject or 'any'}"
            f" chapter={self.chapter_id or 'any'} goal={self.goal}"
            f" history={self.history_summary} mastery_recent={mastery}"
            f"{memory_line}"
            "\n[/education-context]"
        )


# --- pure helpers (unit-tested) -------------------------------------------


#: Delimiter-shaped sequences that must never appear inside a delimited block
#: rendered by this module (see RequestContext.render_block).
_BLOCK_DELIMITER_RE = re.compile(
    r"<\s*/?\s*(?:education-context|evidence|user_question)\s*>", re.IGNORECASE
)


def _sanitize_block_text(text: str) -> str:
    """Neutralize delimiter escapes inside a delimited data block."""
    return _BLOCK_DELIMITER_RE.sub("", text)


def history_summary(turns: int, strategy: str | None = None) -> str:
    """Compact history label: counts + last strategy, never message text."""
    base = f"{turns} turns"
    return f"{base}, strategy={strategy}" if strategy else base


def snapshot_mastery(
    accuracy_by_concept: Mapping[str, float | None], limit: int = 8
) -> dict[str, float]:
    """Weakest-first mastery snapshot capped at `limit` concepts.

    Input: per-concept accuracy percentages (None = ungraded -> skipped).
    """
    scored = [(c, float(a)) for c, a in accuracy_by_concept.items() if a is not None]
    scored.sort(key=lambda item: (item[1], item[0]))
    return {c: round(p, 1) for c, p in scored[:limit]}


# --- request-scoped propagation (mirrors request_id_var logging pattern) --

_current: ContextVar[RequestContext | None] = ContextVar("education_context", default=None)


def set_current_context(ctx: RequestContext | None) -> None:
    _current.set(ctx)


def get_current_context() -> RequestContext | None:
    return _current.get()


# --- evidence token budget (AUD-A2-07 / A5-01) -----------------------------
#
# The context builder used to concatenate every retrieved chunk: the token
# count of the prompt grew with the corpus and with whatever the retriever
# returned, with no cap and no warning. This block gives the prompt a measured
# token budget, stable passage ids, dedupe and deterministic truncation.

#: Hard ceiling for the rendered evidence block, in target-model tokens.
#: Chosen to leave room for the system prompt (~520 tokens), the education
#: context and the conversation history inside the worker budget while still
#: fitting several full textbook passages. Recalibrate with a measurement if
#: the retrieval depth (top_k) or the model window changes.
EVIDENCE_TOKEN_BUDGET = 2400

#: A passage with less budget left than this is dropped rather than cut to a
#: fragment: half a sentence of evidence invites confident nonsense.
MIN_PASSAGE_TOKENS = 40

#: Sentence-ish boundaries used by deterministic truncation. Bangla danda
#: first; the table includes the ASCII/Latin enders used by mixed text.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[।!?\.\n])\s+")

#: Default conservative characters-per-token ratio for the target models.
#: Bangla script tokenizes denser than ASCII in every multilingual tokenizer
#: the repo has looked at; 2.5 chars/token is used as an UPPER BOUND (more
#: tokens than the vendor reports) so a budget check cannot pass in planning
#: and fail upstream. Calibrated against the vendor: the 2026-10-19 run
#: (``eval/token_counter_calibration.json``, 20 golden items, 120 REST
#: countTokens calls) measured this heuristic at 1.07x-1.20x the vendor
#: count (mean 1.13x; an earlier r3 sample measured 1.27x-1.58x). The exact
#: vendor counter is switchable: settings.llm_exact_token_counting wires
#: providers.token_counter.ExactTokenCounter (A5-01).
DEFAULT_CHARS_PER_TOKEN = 2.5
TARGET_TOKENIZER_NOTE = (
    "Conservative Bangla-aware upper bound until a vendor tokenizer is registered; "
    "register_token_counter('gemini'|'openai', counter) plugs in the real one."
)


class TokenCounter(Protocol):
    """Counts prompt tokens the way the target model will see them."""

    name: str

    def count(self, text: str) -> int: ...


class HeuristicTokenCounter:
    """Conservative character-based upper bound (see DEFAULT_CHARS_PER_TOKEN)."""

    def __init__(self, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN, name: str = "") -> None:
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        self._chars_per_token = float(chars_per_token)
        self.name = name or f"heuristic-{chars_per_token:g}cpt"

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token))


_TOKEN_COUNTERS: dict[str, TokenCounter] = {"default": HeuristicTokenCounter()}


def register_token_counter(family: str, counter: TokenCounter) -> None:
    """Register a real target-model tokenizer under ``family``.

    Called at wiring time (or in tests) with a vendor tokenizer; the context
    builder then measures the budget in that model's own tokens.
    """
    _TOKEN_COUNTERS[family.strip().lower()] = counter


def token_counter(family: str = "default") -> TokenCounter:
    """Return the counter for a model family (falls back to the default)."""
    return _TOKEN_COUNTERS.get(family.strip().lower(), _TOKEN_COUNTERS["default"])


@dataclass(frozen=True)
class Passage:
    """One evidence passage as it will be rendered into the prompt."""

    position: int
    source_id: str
    label: str
    text: str
    tokens: int


@dataclass(frozen=True)
class PassageSelection:
    """Deterministic result of fitting retrieved hits into the token budget."""

    passages: tuple[Passage, ...]
    dropped_duplicates: tuple[str, ...] = ()
    dropped_over_budget: tuple[str, ...] = ()
    truncated_passages: tuple[str, ...] = ()
    budget_tokens: int = EVIDENCE_TOKEN_BUDGET
    counter_name: str = "default"

    @property
    def tokens(self) -> int:
        return sum(p.tokens for p in self.passages)

    @property
    def budget_exceeded(self) -> bool:
        """True when anything was dropped or truncated: the caller must warn."""
        return bool(self.dropped_over_budget or self.truncated_passages)


def _default_label(hit: Any) -> str:
    """Stable, model-visible passage header: position id + chunk id + place.

    The chunk id is the corpus-stable identifier, so a citation in the answer
    can be resolved back to the exact chunk that produced it.
    """
    chunk = getattr(hit, "chunk", None)
    meta = getattr(chunk, "meta", None)
    if meta is None:
        return f"[id={getattr(chunk, 'id', 'unknown')}]"
    where = " › ".join(
        part
        for part in (
            f"class {meta.class_level}",
            meta.subject,
            meta.chapter,
            meta.section or "",
        )
        if part
    )
    page = f" | p.{meta.page}" if meta.page is not None else ""
    return f"[id={getattr(chunk, 'id', 'unknown')} | {where}{page}]"


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _truncate_to_tokens(text: str, max_tokens: int, counter: TokenCounter) -> str:
    """Cut ``text`` at the last sentence boundary that fits ``max_tokens``.

    Deterministic: no randomness, no wall-clock input; the same text and
    budget always produce the same prefix.
    """
    sentences = _SENTENCE_SPLIT_RE.split(text)
    kept: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*kept, sentence]).strip()
        if counter.count(candidate) > max_tokens:
            break
        kept.append(sentence)
        if counter.count(candidate) >= max_tokens:
            break
    return " ".join(kept).strip()


def select_passages(
    hits: Sequence[Any],
    *,
    budget_tokens: int = EVIDENCE_TOKEN_BUDGET,
    counter: TokenCounter | None = None,
    labeler: Callable[[Any], str] | None = None,
) -> PassageSelection:
    """Dedupe, label and fit retrieved hits into ``budget_tokens``.

    Order is the retriever's ranking order (best first) and is preserved.
    Duplicate passages (same normalized text) and over-budget passages are
    dropped; the last passage that does not fully fit is truncated at a
    sentence boundary, or dropped when less than MIN_PASSAGE_TOKENS remain.
    The returned selection NEVER exceeds ``budget_tokens``.
    """
    counter = counter or token_counter()
    labeler = labeler or _default_label
    if budget_tokens <= 0:
        raise ValueError("budget_tokens must be positive")

    passages: list[Passage] = []
    dropped_duplicates: list[str] = []
    dropped_over_budget: list[str] = []
    truncated: list[str] = []
    seen: set[str] = set()
    used = 0
    for hit in hits:
        chunk = getattr(hit, "chunk", None)
        source_id = str(getattr(chunk, "id", "") or f"hit-{len(passages)}")
        raw_text = str(getattr(chunk, "text", "") or "")
        fingerprint = _normalized(raw_text)
        if not fingerprint:
            dropped_duplicates.append(source_id)
            continue
        if fingerprint in seen:
            dropped_duplicates.append(source_id)
            continue
        seen.add(fingerprint)
        label = labeler(hit)
        label_tokens = counter.count(label)
        body_budget = budget_tokens - used - label_tokens
        if body_budget < MIN_PASSAGE_TOKENS:
            dropped_over_budget.append(source_id)
            continue
        text = raw_text
        tokens = counter.count(text)
        if used + label_tokens + tokens > budget_tokens:
            text = _truncate_to_tokens(text, body_budget, counter)
            tokens = counter.count(text)
            truncated.append(source_id)
            if tokens < MIN_PASSAGE_TOKENS:
                truncated.pop()
                dropped_over_budget.append(source_id)
                continue
        passages.append(
            Passage(
                position=len(passages) + 1,
                source_id=source_id,
                label=label,
                text=text,
                tokens=tokens + label_tokens,
            )
        )
        used += tokens + label_tokens
    return PassageSelection(
        passages=tuple(passages),
        dropped_duplicates=tuple(dropped_duplicates),
        dropped_over_budget=tuple(dropped_over_budget),
        truncated_passages=tuple(truncated),
        budget_tokens=budget_tokens,
        counter_name=counter.name,
    )


def render_evidence_block(selection: PassageSelection, *, sanitizer: Callable[[str], str]) -> str:
    """Render the selected passages as labelled ``<evidence>`` blocks.

    The label (stable chunk id + place) sits IMMEDIATELY BEFORE its block,
    OUTSIDE the delimiters: it is app-generated metadata, not quoted textbook
    text, and anything inside the tags is data a model may echo -- the mock
    provider's evaluator quotes the evidence verbatim, and an in-tag label was
    measured to appear in the generated answer, costing 9.4pp of the
    faithfulness metric on the dev split (E-R2-rag2-018 / E-R2-rag2-022).

    ``sanitizer`` is passed in by the caller (services.tutor.sanitize_evidence)
    so this module stays free of prompt-injection policy.
    """
    rendered = [
        f"{p.label}\n<evidence>\n{sanitizer(p.text)}\n</evidence>" for p in selection.passages
    ]
    return "\n".join(rendered)
