import asyncio
import logging
import os
import re
import time
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

from bangla_gpt_api import tracing
from bangla_gpt_api.logging_config import json_log, trace_event
from bangla_gpt_api.metrics import (
    PII_REDACTED_TOTAL,
    RAG_CITATION_CHECKS_TOTAL,
    RAG_GATE_OUTCOMES_TOTAL,
    RAG_GATE_REFUSALS_TOTAL,
    RAG_RETRIEVAL_LATENCY_SECONDS,
    record_tutor_answer,
)
from bangla_gpt_api.providers.base import (
    LLMProvider,
    ProviderError,
    sampling_kwargs,
    stage_timeout_seconds,
)
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.retrieval.bm25 import indexable_text, tokenize
from bangla_gpt_api.retrieval.hybrid import light_stem, trigram_similarity
from bangla_gpt_api.retrieval.query_analysis import (
    content_terms,
    coverage_weights,
    english_gloss_terms,
    weighted_coverage,
)
from bangla_gpt_api.retrieval.vocabulary import TermStats
from bangla_gpt_api.schemas import AskResponse, SourceRef
from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)
from bangla_gpt_api.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerMiddleware,
    CircuitOpenError,
    ProviderFallbackRouter,
)
from bangla_gpt_api.services.context import (
    EVIDENCE_TOKEN_BUDGET,
    PassageSelection,
    RequestContext,
    TokenCounter,
    render_evidence_block,
    select_passages,
    set_current_context,
)
from bangla_gpt_api.services.costs import estimate_tokens
from bangla_gpt_api.services.pii import redact_pii
from bangla_gpt_api.services.prompt_registry import (  # noqa: F401 (re-export)
    PROMPTS_DIR_ENV,
    PromptSpec,
    load_prompt,
    prompts_dir,
)
from bangla_gpt_api.services.router import (
    Route,
    classify,
    fast_eligible,
    set_current_route,
)
from bangla_gpt_api.services.safety import (
    refusal_for,
    render_image_text_block,  # noqa: F401 (re-exported for callers/tests)
    sanitize_evidence,
    sanitize_image_text,  # noqa: F401 (re-exported for callers/tests)
    screen_question,
)
from bangla_gpt_api.services.trace_meta import index_fingerprint

logger = logging.getLogger("bangla_gpt_api.tutor")


# --- prompt registry (AUD-A2-06 / A5-02) -----------------------------------
#
# The loader lives in services/prompt_registry.py (A5-02/A1-04) so the
# generators and answer_structure can read the registry without an import
# cycle; it is re-exported here for the historic import path
# (``services.tutor.load_prompt``). Prompts are versioned files under
# ``apps/api/prompts/`` with an owner and a changelog in manifest.json; a
# missing or malformed registry fails loudly at import time. Changing a
# prompt means editing the file, bumping its version and adding a changelog
# entry in the same change -- see docs/operations/CHANGE_MANAGEMENT.md.


INSUFFICIENT_EVIDENCE_ANSWER = (
    "উত্তরটি পাঠ্যবইয়ের বিষয়বস্তুর ভিত্তিতে দেওয়া সম্ভব নয়। অনুগ্রহ করে পাঠ্যবইয়ের সংশ্লিষ্ট অধ্যায় থেকে প্রশ্ন করুন।"
)

# AUD-A2-03 / A6-01: the one-shot regeneration instruction used when the first
# answer fails the post-generation grounding check (citation overlap or an
# arithmetic contradiction). Trusted app text, prepended ahead of the evidence,
# same placement rule as the re-teach instruction. NEEDS NATIVE REVIEW.
GROUNDING_RETRY_INSTRUCTION = load_prompt("tutor_grounding_retry").text

# AUD-A2-19 / A11-03: hint-first instruction for homework-like prompts and the
# step-by-step instruction injected for study-mode turns (context goal).
HINT_FIRST_INSTRUCTION = load_prompt("tutor_hint_first").text
STUDY_STEPS_INSTRUCTION = load_prompt("tutor_study_steps").text

# Canonical non-answer phrasing the SYSTEM_PROMPT (rule ৪) instructs the
# model to use when the evidence does not contain the answer. Detecting it
# keeps the ``grounded`` flag honest: a "not in the textbook" reply is a
# refusal, not a grounded answer with citations attached.
_MODEL_REFUSAL_MARKER = "পাঠ্যবইয়ে নেই"


# Sentinel yielded by _stream_with_fallback when no provider can serve the
# stream. A real delta is always a non-empty str, so identity comparison is
# safe and the value can never collide with provider output.
_OUTAGE = object()


def _model_refused(answer: str) -> bool:
    return _MODEL_REFUSAL_MARKER in answer


# (vision contract): honest refusal for LLM_PROVIDER=mock, which cannot
# see images. A NEW constant -- the four protected SYSTEM_PROMPT constants and
# INSUFFICIENT_EVIDENCE_ANSWER above stay exactly as they are. The copy never
# claims to have looked at the picture (refused_reason='vision_unsupported').
VISION_UNSUPPORTED_ANSWER = (
    "দুঃখিত, এই সংস্করণে ছবি থেকে উত্তর দেওয়া এখনো সম্ভব হয়নি। "
    "অনুগ্রহ করে প্রশ্নটি লিখে পাঠান — আমি পাঠ্যবইয়ের ভিত্তিতে উত্তর দেব।"
)

# Streamed when no provider could serve the turn. This is an outage notice,
# not textbook content — the stream path must never mark it grounded.
_UNAVAILABLE_ANSWER = "দুঃখিত, AI সেবা এই মুহূর্তে ব্যবহার করা যাচ্ছে না। অনুগ্রহ করে পরে আবার চেষ্টা করুন।"

# AUD-A2-17 / A6-09: honest refusal for an image that cannot be read (blank,
# blurry, too small, or not decodable). Better a clear "send a clearer photo"
# than a vision model guessing at a picture nobody can read.
IMAGE_UNREADABLE_ANSWER = (
    "দুঃখিত, ছবিটি পড়া যায়নি (অস্পষ্ট, খুব ছোট বা ক্ষতিগ্রস্ত)। "
    "অনুগ্রহ করে পরিষ্কার ছবি আবার পাঠান, অথবা প্রশ্নটি লিখে পাঠান।"
)


# A9-03 graceful degradation: when NO provider can serve the turn, the
# student still gets the retrieved textbook passages with an honest notice
# instead of a dead end. Never marked grounded (no model wrote it) and never
# carries model citations -- the passages are quoted verbatim with their ids.
EVIDENCE_ONLY_HEADER = (
    "দুঃখিত, AI উত্তর এই মুহূর্তে দেওয়া যাচ্ছে না। তবে প্রশ্নের সঙ্গে সম্পর্কিত পাঠ্যবইয়ের অংশগুলো নিচে দেওয়া হলো:"
)

# --- streaming contract (A6-08 / AUD-A2-16) --------------------------------
#
# Documented here because it is the contract every SSE client depends on.
# The transport framing (``event: <type>\ndata: <json>\n\n``) lives in
# routers/tutor.py; this constant is the semantic half.
#
# Event schema
#   token     data {"text": <str>}          -- one answer delta, in order.
#   citation  data {"sources": [...], "citation_verified": true} -- emitted
#             once, after the tokens, ONLY when the answer passed the
#             post-generation grounding check. Carries the validated source
#             list so a client can render citations before the final event.
#   heartbeat data {"interval_seconds": <num>} -- emitted when no token has
#             been produced for STREAM_HEARTBEAT_SECONDS. Proves to the
#             client (and to any proxy) that the stream is alive through a
#             slow provider; carries no answer content.
#   error     data {"code": <str>, "recoverable": <bool>} -- emitted when the
#             stream fails after it has started. Tokens already sent stay on
#             screen; the following final event carries the honest
#             replacement (degraded passages or the outage notice).
#   final     data = the complete AskResponse (+ counts). Exactly one per
#             turn, always last. Its ``answer`` SUPERSEDES everything
#             streamed before it, because the grounding check runs only once
#             the full answer exists.
#
# Mid-stream error policy: a provider failure after the first token is never
# retried on the same stream (a truncated answer cannot be spliced); the
# client receives ``error`` plus one ``final`` event, and the persisted
# assistant turn is the final event's answer only.
#
# Reconnection policy: the user turn is persisted BEFORE streaming starts, so
# a client that reconnects must NOT resend it; it should GET the conversation
# messages and, if the last user turn has no assistant reply, request a fresh
# stream for the same turn. A reconnect never resumes a half-written answer:
# partial-answer persistence semantics are "the assistant turn is saved only
# from the final event", so a dropped stream leaves no partial row.
STREAM_HEARTBEAT_SECONDS = 10.0
STREAM_HEARTBEAT_ENV = "TUTOR_STREAM_HEARTBEAT_SECONDS"
STREAM_EVENT_TYPES = frozenset({"token", "citation", "heartbeat", "error", "final"})


def stream_heartbeat_seconds(settings: object | None = None) -> float:
    """Resolve the heartbeat interval: settings field, then env, then default.

    Interim plumbing until the settings field lands (handoff: api-rag2.md);
    the env override also lets tests shrink the interval without patching.
    """
    raw = (
        getattr(settings, "tutor_stream_heartbeat_seconds", None) if settings is not None else None
    )
    if raw is None:
        raw = os.environ.get(STREAM_HEARTBEAT_ENV)
    if raw is None:
        return STREAM_HEARTBEAT_SECONDS
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid %s=%r; using default", STREAM_HEARTBEAT_ENV, raw)
        return STREAM_HEARTBEAT_SECONDS


EVIDENCE_OPEN = "<evidence>"
EVIDENCE_CLOSE = "</evidence>"


@asynccontextmanager
async def _null_ctx() -> AsyncIterator[None]:
    """Async context manager that does nothing — for optional circuit breaker."""
    yield


# Prompt-injection guard: corpus chunks are untrusted data. They are
# wrapped in <evidence> delimiters and the system rule explicitly states
# that anything inside the delimiters is quoted data, never instructions.
# The student's own question is likewise wrapped and declared untrusted.
# The text lives in prompts/tutor_system.md (owner + changelog there).
_SYSTEM_PROMPT_SPEC = load_prompt("tutor_system")
SYSTEM_PROMPT = _SYSTEM_PROMPT_SPEC.text


#: Machine-derived prompt version (A5-02 / I-03): registry id + SemVer version
#: + the digest of the exact text in this build, recorded in every generation
#: trace. Deriving the digest instead of hand-maintaining a version string
#: means a prompt edit can never leave a stale version behind in a trace
#: record; the SemVer part comes from the registry changelog.
PROMPT_VERSION = _SYSTEM_PROMPT_SPEC.trace_version


_ZERO_WIDTH_TABLE = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")


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


def _provider_call_kwargs(provider: object, *, image: dict | None, task: str) -> dict[str, Any]:
    """Keyword arguments for one provider call (image + per-task sampling).

    One merged dict instead of two ``**`` spreads: the Protocol's keywords are
    typed, and a spread of two inferred dicts defeats that checking. Only the
    providers that declare ``supports_sampling`` receive ``sampling``.
    """
    kwargs: dict[str, Any] = sampling_kwargs(provider, task)
    if image is not None:
        kwargs["image"] = image
    return kwargs


def _screen_safety(question: str) -> tuple[str, str] | None:
    """Return (refusal_copy, reason) when the question violates safety rules."""
    verdict = screen_question(question)
    if not verdict.safe:
        reason = verdict.reason or "unsafe_content"
        return refusal_for(reason), reason
    return None


# --- pedagogy guardrails (AUD-A2-19 / A11-03) ------------------------------

#: Context goal the router sets for a study-mode turn; study mode appends the
#: step-by-step instruction (prompts/tutor_study_steps.md).
GOAL_STUDY = "study"

#: Homework-like phrasing that triggers hint-first behaviour: "did my
#: homework", "solve it for me", "মূল্যায়ন করা হবে" style phrasing where a
#: student pastes an assignment. Deliberately conservative -- a normal
#: curriculum question ("সালোকসংশ্লেষণ কী?") must NOT be hint-gated.
_HOMEWORK_CUES = (
    r"হোমওয়ার্ক",
    r"হোম\s*ওয়ার্ক",
    r"বাড়ির\s*কাজ",
    r"বাসার\s*কাজ",
    r"অ্যাসাইনমেন্ট",
    r"assignment",
    r"home\s*-?\s*work",
    r"সমাধান\s*করে\s*দাও",
    r"উত্তর\s*লিখে\s*দাও",
    r"solve\s+(?:it\s+)?for\s+me",
)
_HOMEWORK_CUE_RE = re.compile("|".join(_HOMEWORK_CUES), re.IGNORECASE)

#: Interim switch for hint-first behaviour until the settings field lands
#: (handoff: api-rag2.md). Truthy default: the pedagogy requirement is
#: hint-first for homework-like prompts; operators turn it off with
#: TUTOR_HINT_FIRST=0 (or the settings field once wired).
HINT_FIRST_ENV = "TUTOR_HINT_FIRST"
_FALSEY = frozenset({"0", "false", "no", "off", "disabled"})


def hint_first_enabled(settings: object | None = None, *, default: bool = True) -> bool:
    """Resolve the hint-first flag: settings field, then env, then default."""
    raw = getattr(settings, "tutor_hint_first", None) if settings is not None else None
    if raw is None:
        raw = os.environ.get(HINT_FIRST_ENV)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in _FALSEY


def is_homework_like(question: str, history: list[dict[str, str]] | None = None) -> bool:
    """True when the question reads like a pasted assignment/homework.

    A11-03: a homework dialogue is not one turn. The student pastes the task,
    gets a hint, then replies "I tried" -- and that follow-up carries no cue
    of its own, which used to let the hint-first guardrail expire exactly when
    the model was about to be asked for the solution. The LAST user turn is
    therefore part of the test: while the conversation is inside the same
    homework exchange the guardrail stays. A fresh curriculum question becomes
    the new last turn and the guardrail ends by itself.
    """
    if _HOMEWORK_CUE_RE.search(question):
        return True
    for turn in reversed(history or []):
        if turn.get("role") == "user":
            return bool(_HOMEWORK_CUE_RE.search(str(turn.get("content", ""))))
    return False


def sanitize_image_payload(image: dict | None) -> tuple[dict | None, str | None]:
    """Second-pass image hygiene before the bytes reach a provider (A6-09).

    Returns ``(payload, refusal_reason)``: ``(None, None)`` for text-only
    turns, ``(payload, None)`` with metadata-free, quality-checked bytes, or
    ``(None, "image_unreadable")`` when the picture cannot be read honestly.
    The route-level validation already ran; this pass strips EXIF/PNG text
    chunks/trailing bytes (re-encode) and refuses blank, blurry or tiny
    images, so the model never guesses at a picture nobody can read.
    """
    if image is None:
        return None, None
    from bangla_gpt_api.providers.image_safety import ImageSanitizeError, sanitize_inline_image

    try:
        sanitized = sanitize_inline_image(image.get("mime_type", ""), image.get("data", ""))
    except ImageSanitizeError as exc:
        # the reason is structural (size/blur/decode), never image content
        logger.warning("chat_image_rejected: %s", exc)
        return None, "image_unreadable"
    return {"mime_type": sanitized.mime_type, "data": sanitized.base64()}, None


class TutorService:
    #: Per-task sampling profiles (A6-06): providers that declare
    #: ``supports_sampling`` receive these instead of the vendor defaults.
    ANSWER_TASK = "tutor_answer"
    STREAM_TASK = "tutor_stream"
    #: Class-level defaults for the knobs __init__ sets, so a service handed to
    #: tests through ``TutorService.__new__`` (the seam-test style) still
    #: resolves them instead of raising AttributeError.
    evidence_token_budget: int = EVIDENCE_TOKEN_BUDGET
    hint_first: bool = True
    stream_heartbeat_seconds: float = STREAM_HEARTBEAT_SECONDS
    index_version: str = ""  # __init__ overwrites with the corpus fingerprint
    _token_counter: TokenCounter | None = None
    _concurrency: Any | None = None

    def __init__(
        self,
        index: RankingIndex,
        provider: LLMProvider,
        *,
        fast_provider: LLMProvider | None = None,
        min_score: float = 0.0,
        min_coverage: float = 0.5,
        top_k: int = 3,
        circuit_breaker: CircuitBreaker | None = None,
        fallback_provider: LLMProvider | None = None,
        term_stats: TermStats | None = None,
        evidence_token_budget: int = EVIDENCE_TOKEN_BUDGET,
        token_counter: TokenCounter | None = None,
        hint_first: bool | None = None,
        concurrency_limiter: Any | None = None,
    ) -> None:
        self.index = index
        # A5-01/AUD-A2-07: hard token ceiling for the evidence block and the
        # counter used to measure it (default: the conservative bound; a real
        # target-model tokenizer can be registered with register_token_counter).
        self.evidence_token_budget = int(evidence_token_budget)
        self._token_counter = token_counter
        # A11-03/AUD-A2-19: hint-first pedagogy for homework-like prompts.
        # None -> resolve from settings/env/default (hint_first_enabled).
        self.hint_first = hint_first_enabled() if hint_first is None else bool(hint_first)
        # A7-05/AUD-A2-10: optional per-identity in-flight generation cap.
        self._concurrency = concurrency_limiter
        # A6-08/AUD-A2-16: idle interval after which a stream emits a
        # heartbeat event (seconds; <= 0 disables).
        self.stream_heartbeat_seconds = stream_heartbeat_seconds()
        # Corpus term statistics (document frequencies) that let the
        # grounding gate weight rare curriculum terms above scaffolding.
        # Optional: without them the gate falls back to uniform weights
        # over content terms, which stays correct, only coarser.
        self.term_stats = term_stats
        self.provider = provider
        # optional lane for SIMPLE routes (services/router.py). None ->
        # the main provider serves every route (mock mode / no fast model).
        self.fast_provider = fast_provider
        # Absolute BM25 floors do NOT transfer across corpus sizes (verified
        # on the real NCTB corpus); the grounding gate therefore requires
        # that a sufficient fraction of query terms appear in the evidence.
        self.min_score = min_score
        self.min_coverage = min_coverage
        self.top_k = top_k
        # I-03: corpus identity for every trace record this instance emits.
        self.index_version = index_fingerprint(index)

        # Circuit breaker + fallback for AI resilience
        self._breaker = circuit_breaker
        self._fallback = fallback_provider
        self._router: ProviderFallbackRouter | None = None
        if circuit_breaker is not None:
            self._router = ProviderFallbackRouter(provider, fallback_provider, circuit_breaker)

    # Trigram similarity a near-identical evidence token must clear for a
    # missed query term to still count as covered. 0.6 admits single-keystroke
    # slips (dropped conjunct/vowel, e.g. সালোকসংশলেষণ for সালোকসংশ্লেষণ ≈ 0.75)
    # while far-off words stay uncovered; tokens with no trigrams (≤2 chars)
    # can never fuzzy-match.
    FUZZY_MATCH_SIMILARITY = 0.6

    def _term_covered(self, term: str, evidence_terms: set[str]) -> bool:
        """Exact stem match, else one conservative near-match allowance.

        Mobile-typed questions carry spelling slips that exact stem matching
        turns into ``insufficient_evidence`` refusals even when the evidence
        chunk is the right one; the trigram fallback keeps the gate honest
        (only near-identical tokens count) without letting paraphrases in.
        """
        if term in evidence_terms:
            return True
        for candidate in evidence_terms:
            if abs(len(candidate) - len(term)) > 3:
                continue
            if trigram_similarity(term, candidate) >= self.FUZZY_MATCH_SIMILARITY:
                return True
        return False

    def _trace_retrieval(
        self,
        hits: list,
        *,
        retrieval_ms: int,
        coverage: float,
        gate_pass: bool,
        stream: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> None:
        """Per-stage trace record for the retrieval stage (I-03 / A10-01).

        Carries what an incident responder needs to reproduce a bad answer:
        which corpus index served it, which chunks were retrieved with their
        per-hit scores (not only the best), the filter values the router
        passed ({class_level, subject, chapter}), and how the gate voted.
        No question text (see the service's logging posture) — filter
        *values* only, never the query.
        """
        trace_event(
            "retrieval",
            stream=stream,
            retrieval_ms=retrieval_ms,
            evidence_chunks=len(hits),
            top_score=(round(hits[0].score, 4) if hits else None),
            scores=[round(h.score, 4) for h in hits],
            filters=dict(filters or {}),
            coverage=round(float(coverage), 4),
            gate="pass" if gate_pass else "refuse",
            index_version=self.index_version,
            retrieved_ids=[getattr(getattr(h, "chunk", None), "id", None) for h in hits],
        )

    def _trace_generation(
        self,
        *,
        route: object,
        provider: object,
        prompt_text: str,
        answer: str,
        latency_ms: int,
    ) -> None:
        """Per-stage trace record for the generation stage (I-03).

        Token counts use the same estimator as the cost ledger, so a trace,
        a dashboard and a budget figure agree by construction.
        """
        trace_event(
            "generation",
            route=getattr(route, "value", str(route)),
            model=getattr(provider, "model", None) or getattr(provider, "name", "unknown"),
            prompt_version=PROMPT_VERSION,
            index_version=self.index_version,
            prompt_tokens=estimate_tokens(prompt_text),
            completion_tokens=estimate_tokens(answer),
            answer_chars=len(answer),
            latency_ms=latency_ms,
        )

    def _coverage_details(self, question: str, hits: list) -> tuple[float, bool]:
        """Weighted content-term coverage of the best chunk, plus the verdict.

        Replaces raw token coverage, which measurably refused answerable
        questions: "সালোকসংশ্লেষণ কী এবং কোথায় ঘটে?" scored 0.40 against its
        own section because কোথায় / ঘটে / এবং are function words a textbook
        passage cannot contain, and the gate counted them as must-cover terms
        with equal weight. Three corrections, each measured:

        * only **content terms** count (query_analysis: copulas, conjunctions,
          question particles, pronouns, postpositions in Bangla, Banglish and
          English);
        * the remaining terms are weighted by corpus document frequency --
          missing a term the whole book repeats costs nearly nothing, missing
          a one-of-a-kind curriculum term dominates the verdict;
        * the evidence the gate reads is the text the lexical lane indexes
          (heading + chapter + body), so a chapter-title question can be
          satisfied by its own section heading;
        * coverage is measured over the question's terms the corpus *knows*:
          the student's own framing vocabulary ("explain করো", "৬ষ্ঠ শ্রেণির")
          is absent from the textbook by construction, and weighting it at
          the IDF maximum made user phrasing dilute coverage. A question
          whose content terms are all absent from the corpus is
          out-of-corpus, and still refuses.

        The verdict passes when ANY retrieved chunk clears the threshold:
        ranking noise between near-tied chunks must not flip a grounded
        question into a refusal. Returns ``(best_coverage, passed)``.
        """
        query_terms = content_terms(question)
        if not query_terms:
            # a question made only of function words/punctuation: fall back to
            # every stemmed token, the pre-stop-word behaviour, rather than
            # scoring an empty term set as instant groundability.
            query_terms = tuple(
                dict.fromkeys(light_stem(t) for t in tokenize(question) if len(t) >= 2)
            )
        # Cross-script resolution: the retrieval lanes already widen a query
        # through the glossary (cell → কোষ) and the roman lane (bhognangsho →
        # ভগ্নাংশ); the gate must see the SAME resolved terms or it would
        # refuse, for script reasons, a question retrieval just answered.
        # Graceful degradation: statistics without the matching surfaces
        # resolve nothing, and the gate proceeds on the raw terms.
        roman_matcher = getattr(self.term_stats, "match_roman", None)
        resolved: list[str] = []
        for term in query_terms:
            if term.isascii():
                substitutes = english_gloss_terms(term)
                if not substitutes and roman_matcher is not None:
                    substitutes = tuple(roman_matcher(term))
                resolved.extend(substitutes)
                if not substitutes:
                    resolved.append(term)
            else:
                resolved.append(term)
        query_terms = tuple(dict.fromkeys(resolved))
        if not query_terms or not hits:
            return 0.0, False

        # Coverage is measured over the question's terms the corpus KNOWS
        # about (df >= 1), weighted by ln(1 + N/df). Two documented reasons:
        #
        # * a term the corpus has never seen (ইউক্লিড, স্বতঃসিদ্ধ, ক্রিকেট)
        #   is the question's subject world, not the textbook's: the evidence
        #   cannot contain it, and its uncovered maximum weight is exactly
        #   what refuses an out-of-corpus question (the out-of-domain matrix
        #   row). A question whose content terms are ALL df=0 is therefore
        #   out-of-corpus by definition and refuses here;
        # * terms the corpus does know carry ln(1 + N/df): missing a
        #   one-of-a-kind curriculum term dominates the verdict, while
        #   missing a term the whole book repeats costs little -- which is
        #   how "ভগ্নাংশ কী? explain করো" grounds on ভগ্নাংশ alone instead
        #   of being vetoed by the instruction word.
        if self.term_stats is not None and self.term_stats.total_documents > 0:
            in_corpus = tuple(t for t in query_terms if self.term_stats.document_frequency(t) > 0)
            absent = len(query_terms) - len(in_corpus)
            # A4-06 out-of-domain rule (majority form): a question whose
            # content terms are MOSTLY absent from the served index (more
            # df==0 terms than known terms) is outside the textbook's world
            # and refuses here, before weighting can answer it on its one
            # lucky overlap. The strict ">= 2 absent" count from the
            # divergence register was measured and declined: it refuses
            # 37-38% of ANSWERABLE chapter-title/Banglish questions on the
            # served corpus (probe 2026-10-19), while the majority form
            # separates the classes cleanly (4/4 curated adversarial refuse,
            # 0/317 answerable). Subsumes the all-terms-absent refusal that
            # sat here before (absent > known includes known == 0).
            if absent > len(in_corpus):
                json_log(
                    logger,
                    logging.INFO,
                    "tutor_retrieval",
                    gate="out_of_domain",
                    known_terms=len(in_corpus),
                    absent_terms=absent,
                    rule="majority_absent",
                )
                return 0.0, False
            if not in_corpus:
                # both counts zero: nothing measurable, refuse as before
                json_log(
                    logger,
                    logging.INFO,
                    "tutor_retrieval",
                    gate="out_of_domain",
                    out_of_corpus_terms=len(query_terms),
                )
                return 0.0, False
            query_terms = in_corpus

        if self.term_stats is not None and self.term_stats.total_documents > 0:
            weights = coverage_weights(
                query_terms,
                {t: self.term_stats.document_frequency(t) for t in query_terms},
                self.term_stats.total_documents,
            )
        else:
            weights = {t: 1.0 for t in query_terms}

        best_coverage = 0.0
        passed = False
        for hit in hits:
            evidence_terms = {light_stem(t) for t in tokenize(indexable_text(hit.chunk))}
            covered = [t for t in query_terms if self._term_covered(t, evidence_terms)]
            coverage = weighted_coverage(query_terms, covered, weights)
            best_coverage = max(best_coverage, coverage)
            if coverage >= self.min_coverage and hit.score > self.min_score:
                passed = True
        return round(best_coverage, 4), passed

    async def _retrieve_with_timeout(
        self, query: str, class_level: int, subject: str | None, chapter: str | None = None
    ) -> list:
        """Retrieval off the event loop and inside its own stage ceiling.

        A6-06: the CPU work runs in a thread (an SSE turn must not stall other
        streams) and the whole stage is bounded by
        ``providers.base.STAGE_TIMEOUT_SECONDS['retrieval']``. A retrieval that
        trips the ceiling is a fault, not an empty corpus: it is logged and the
        turn abstains with the honest "not in the textbook" answer instead of
        holding the worker.
        """
        try:
            async with asyncio.timeout(stage_timeout_seconds("retrieval")):
                return await asyncio.to_thread(self._retrieve, query, class_level, subject, chapter)
        except TimeoutError:
            logger.warning("tutor: retrieval stage exceeded its wall-clock ceiling")
            return []

    async def _retrieve_and_gate(
        self, query: str, class_level: int, subject: str | None, chapter: str | None
    ) -> tuple[list, int, float, bool]:
        """Retrieve, measure the stage and run the coverage gate.

        Shared by ask() and ask_stream() so the two paths cannot drift on
        latency accounting or gate metrics; returns (hits, latency_ms,
        coverage, gate_pass).
        """
        started = time.perf_counter()
        hits = await self._retrieve_with_timeout(query, class_level, subject, chapter)
        retrieval_ms = int((time.perf_counter() - started) * 1000)
        RAG_RETRIEVAL_LATENCY_SECONDS.observe(retrieval_ms / 1000.0)
        coverage_value, gate_pass = self._coverage_details(query, hits)
        RAG_GATE_OUTCOMES_TOTAL.labels(gate="pass" if gate_pass else "refuse").inc()
        return hits, retrieval_ms, coverage_value, gate_pass

    def _gate(self, question: str, hits: list) -> bool:
        """Coverage gate over the best retrieved chunk.

        Any single retrieved chunk that covers enough of the question's
        weighted *content* terms counts as sufficient evidence — ranking noise
        between near-tied chunks must not flip a grounded question into a
        refusal. Kept as the boolean form of :meth:`_coverage_details` because
        callers (and tests) reason about the verdict, not the number.
        """
        _coverage_value, passed = self._coverage_details(question, hits)
        return passed

    def _retrieve(
        self, question: str, class_level: int, subject: str | None, chapter: str | None = None
    ) -> list:
        hits = self.index.search(
            question,
            class_level=class_level,
            subject=subject,
            chapter=chapter,
            top_k=self.top_k,
        )
        if chapter and not self._gate(question, hits):
            # The student may have asked beyond the open chapter — fall back to
            # the full subject index instead of refusing outright.
            hits = self.index.search(
                question,
                class_level=class_level,
                subject=subject,
                top_k=self.top_k,
            )
        return hits

    #: a follow-up question may at most carry this many content terms of the
    #: previous user turn; more would turn BM25 into a blurred keyword soup.
    _FOLLOWUP_CONTEXT_TERMS = 8

    def _conversation_retrieval_query(
        self, question: str, history: list[dict[str, str]] | None
    ) -> str:
        """Resolve a short follow-up against the prior user turn.

        Multi-turn chat is the product's core surface, but retrieval ran on the
        bare latest message: a follow-up like "আরেকটু সহজ করে বোঝাও" ("explain
        it more simply") carries no retrievable subject, so its content-term
        set is empty and the coverage gate refused conversations that a
        first-time question grounds fine. When the question is **not**
        self-sufficient (≤1 content term) and a prior user turn exists, that
        turn's content terms are appended — retrieval and the gate then see
        the same resolved subject. Rich questions (≥2 content terms) and
        deliberate ``search_query`` overrides are never rewritten, so
        single-turn behaviour is byte-identical to before.
        """
        if not history:
            return question
        if len(content_terms(question)) > 1:
            return question
        prior_user = next(
            (turn.get("content", "") for turn in reversed(history) if turn.get("role") == "user"),
            "",
        )
        context_terms = content_terms(prior_user) if prior_user else ()
        if not context_terms:
            return question
        return question + " " + " ".join(context_terms[: self._FOLLOWUP_CONTEXT_TERMS])

    @staticmethod
    def _sources(hits: list) -> list[SourceRef]:
        return [
            SourceRef(
                book=hit.chunk.meta.book,
                chapter=hit.chunk.meta.chapter,
                section=hit.chunk.meta.section,
                page=hit.chunk.meta.page,
                score=hit.score,
                # full (delimiter-sanitized) evidence for the modal.
                excerpt=sanitize_evidence(hit.chunk.text),
            )
            for hit in hits
        ]

    async def _stream_with_fallback(
        self,
        context_blocks: str,
        *,
        provider: LLMProvider,
        image: dict | None,
        fallback: LLMProvider | None,
    ) -> AsyncIterator[Any]:
        """Yield provider deltas, switching to the fallback if the primary fails.

        Yields ``_OUTAGE`` (a sentinel, never a real delta) when the circuit is
        open and no fallback exists, so the caller can emit the outage notice
        once. Partial primary output is discarded before a fallback restart:
        concatenating a truncated half-answer with the restart reads as garbled
        text to the student.
        """
        primary = provider.stream(
            context_blocks,
            system=SYSTEM_PROMPT,
            **_provider_call_kwargs(provider, image=image, task=self.STREAM_TASK),
        )
        fallback_stream: AsyncIterator[str] | None = None
        try:
            try:
                async with (
                    CircuitBreakerMiddleware(self._breaker) if self._breaker else _null_ctx()
                ):
                    async for delta in primary:
                        yield delta
                return
            except ProviderError:
                if self._router is None or fallback is None or not self._router.fallback_active:
                    raise
                logger.warning(
                    "tutor_stream: primary provider failed during stream, switching to fallback",
                    exc_info=True,
                )
            except CircuitOpenError:
                if fallback is None:
                    logger.warning("tutor_stream: circuit breaker OPEN during stream, no fallback")
                    yield _OUTAGE
                    return
                logger.warning(
                    "tutor_stream: circuit breaker OPEN during stream, using fallback provider"
                )

            fallback_stream = fallback.stream(
                context_blocks,
                system=SYSTEM_PROMPT,
                **_provider_call_kwargs(fallback, image=image, task=self.STREAM_TASK),
            )
            async for delta in fallback_stream:
                yield delta
        finally:
            # A6-06: whichever way this generator ends -- exhaustion, an
            # exception, or the consumer closing it (SSE client disconnect) --
            # the upstream provider streams are closed here, so no orphaned
            # call keeps generating (and billing) in the background.
            await self._aclose(primary)
            if fallback_stream is not None:
                await self._aclose(fallback_stream)

    @staticmethod
    async def _aclose(source: object) -> None:
        """Close an upstream async generator, tolerating generators without one."""
        aclose = getattr(source, "aclose", None)
        if aclose is None:
            return
        with suppress(Exception):
            await aclose()

    async def _heartbeat_stream(self, source: AsyncIterator[Any]) -> AsyncIterator[tuple[str, Any]]:
        """Yield ``("token", delta)`` and ``("heartbeat", None)`` items.

        Heartbeat (A6-08): a provider that takes longer than
        ``stream_heartbeat_seconds`` to produce the next delta would otherwise
        leave the SSE connection silent, and silent connections are what
        proxies and clients time out. The provider generator is pumped by a
        background task so the timeout never cancels it.

        Cancellation (A6-06): the source generator is closed in the ``finally``
        block. When the SSE consumer goes away (client disconnect closes this
        generator), the pump task is cancelled and ``aclose()`` propagates the
        exit into the provider's HTTP stream, so no orphaned upstream call
        keeps generating (and billing) after the student left.
        """
        interval = self.stream_heartbeat_seconds
        if interval <= 0:
            try:
                async for delta in source:
                    yield "token", delta
            finally:
                await self._aclose(source)
            return

        queue: asyncio.Queue[Any] = asyncio.Queue()
        done = object()

        async def pump() -> None:
            try:
                async for delta in source:
                    queue.put_nowait(delta)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # surfaced to the consumer below
                queue.put_nowait(exc)
            finally:
                queue.put_nowait(done)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=interval)
                except TimeoutError:
                    yield "heartbeat", None
                    continue
                if item is done:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield "token", item
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await self._aclose(source)

    def _evidence_only_answer(self, hits: list) -> str:
        """Retrieval-only answer for the degraded mode (A9-03).

        Deterministic: the same hits render the same passage list, with the
        same stable passage ids the model would have seen.
        """
        selection = render_evidence(
            hits, budget_tokens=self.evidence_token_budget, counter=self._token_counter
        )
        passages = [f"{p.label}\n{sanitize_evidence(p.text)}" for p in selection.passages]
        return "\n\n".join([EVIDENCE_ONLY_HEADER, *passages]) if passages else _UNAVAILABLE_ANSWER

    async def _select_provider(
        self,
        context_blocks: str,
        *,
        image: dict | None,
        route: Route,
    ) -> tuple[LLMProvider, LLMProvider]:
        """Pick the provider for a call and let the circuit-breaker router
        override it only when the primary is unhealthy.

        Returns ``(route_based, effective)``: the route-based choice is what the
        ai_call log line reports, the effective one is what actually runs.
        """
        fast = self.fast_provider
        base: LLMProvider = (
            fast
            if fast is not None and fast_eligible(route, fast) and image is None
            else self.provider
        )
        if self._router is None:
            return base, base
        chosen = await self._router.select_provider(
            context_blocks, system=SYSTEM_PROMPT, image=image
        )
        # Preserve the route-based fast/main choice unless the router says the
        # primary is unhealthy.
        return base, (base if chosen is self.provider else chosen)

    def _pedagogy_instructions(
        self,
        question: str,
        *,
        context: RequestContext | None,
        extra_instruction: str | None,
        history: list[dict[str, str]] | None = None,
    ) -> list[str]:
        """Trusted teaching instructions for this turn, in a fixed order.

        Order: the caller's instruction (an explicit student-chosen strategy
        or the re-teach swap), then the pedagogy guardrails — hint-first for
        homework-like prompts, then the study-mode step instruction. Each is
        one registered prompt (prompts/manifest.json), never an inline string.
        """
        instructions: list[str] = []
        if extra_instruction:
            instructions.append(extra_instruction)
        if self.hint_first and is_homework_like(question, history):
            instructions.append(HINT_FIRST_INSTRUCTION)
        # getattr: seam tests pass minimal context stand-ins that only
        # implement render_block(); a missing goal means "not study mode".
        if getattr(context, "goal", "") == GOAL_STUDY:
            instructions.append(STUDY_STEPS_INSTRUCTION)
        return instructions

    def _prompt_blocks(
        self,
        hits: list,
        question: str,
        history: list[dict[str, str]] | None,
        *,
        extra_instruction: str | None,
        context: RequestContext | None,
        low_data: bool,
    ) -> str:
        """Build the evidence prompt with the trusted app text prepended.

        Order matters: extra instruction, then education context, then the
        untrusted evidence block. Both ask() and ask_stream() must use exactly
        this, so it lives in one place.
        """
        blocks, selection = build_evidence_prompt_with_selection(
            hits,
            question,
            history,
            budget_tokens=self.evidence_token_budget,
            counter=self._token_counter,
        )
        # Context-assembly trace (A5-01): which passages made it into the
        # prompt, in what order, under which budget. The ids are the corpus
        # chunk ids, so an answer's citations can be resolved to chunks.
        trace_event(
            "prompt",
            prompt_version=PROMPT_VERSION,
            index_version=self.index_version,
            evidence_ids=[p.source_id for p in selection.passages],
            evidence_tokens=selection.tokens,
            budget_tokens=selection.budget_tokens,
            # Field name is `tokenizer`, not `token_counter`: the log redactor
            # treats any key whose segment is `token` as a credential
            # (logging_config._SENSITIVE_KEY_RE) and replaced this value with
            # "[redacted]" in every prompt trace, which cost the A5-01 record
            # the name of the counter that measured the budget. `tokenizer`
            # survives redaction and says the same thing.
            tokenizer=selection.counter_name,
            dropped_duplicates=len(selection.dropped_duplicates),
            dropped_over_budget=len(selection.dropped_over_budget),
            truncated=len(selection.truncated_passages),
        )
        instructions = self._pedagogy_instructions(
            question, context=context, extra_instruction=extra_instruction, history=history
        )
        if low_data:
            instructions.append(SHORT_ANSWER_INSTRUCTION)
        if instructions:
            # app-level teaching instructions (strategy swap, hint-first,
            # study mode, low-data) — trusted app text, prepended ahead of the
            # untrusted evidence block.
            blocks = "\n".join(instructions) + "\n\n" + blocks
        if context is not None:
            # education context (trusted app text, same placement rule).
            blocks = f"{context.render_block()}\n\n{blocks}"
        return blocks

    @staticmethod
    def _refusal(answer: str, reason: str) -> AskResponse:
        """A refusal response, with its confidence derived the same way
        everywhere. Every refusal path (safety screen, coverage gate, model
        refusal) funnels through here so they cannot drift apart."""
        from bangla_gpt_api.services.safety import answer_confidence

        # Every refusal reason is one label value on the same counter: ops
        # gets the split between safety categories, evidence refusal and
        # provider refusal without a log query (HighRAGRefusalRate alerts on
        # the insufficient_evidence label).
        RAG_GATE_REFUSALS_TOTAL.labels(reason=reason).inc()
        # Business signal (I-02): same funnel as the per-reason counter, so
        # "refusals per day" and "refusal rate" exist without a DB query.
        record_tutor_answer("tutor", "refused")
        return AskResponse(
            answer=answer,
            grounded=False,
            refused_reason=reason,
            confidence=answer_confidence(False, reason, []),
        )

    async def _generate(
        self,
        context_blocks: str,
        *,
        image: dict | None,
        provider: LLMProvider,
    ) -> str:
        """LLM-call span (I-03), then the provider call itself.

        The span names the provider and the model but never the prompt or the
        answer: for this product that text is a student's wording, so spans
        carry identities and counts only (the per-stage trace record accounts
        for the tokens).
        """
        with tracing.span(
            "llm.generate",
            **{
                "llm.provider": str(getattr(provider, "name", "unknown")),
                "llm.model": str(
                    getattr(provider, "model", None) or getattr(provider, "name", "unknown")
                ),
            },
        ):
            return await self._generate_via_providers(
                context_blocks, image=image, provider=provider
            )

    async def _generate_via_providers(
        self,
        context_blocks: str,
        *,
        image: dict | None,
        provider: LLMProvider,
    ) -> str:
        """Run the provider, applying the circuit breaker and the fallback
        chain. Raises ProviderError when nothing can serve the request.

        A6-06: the generation stage runs inside its own wall-clock ceiling
        (providers.base.STAGE_TIMEOUT_SECONDS), so a provider chain that
        ignores its own per-attempt timeouts cannot pin the worker past the
        budget; the ceiling surfaces as the same ProviderError the fallback
        path already handles.
        """
        fallback = self._fallback
        try:
            async with asyncio.timeout(stage_timeout_seconds("generation")):
                async with (
                    CircuitBreakerMiddleware(self._breaker) if self._breaker else _null_ctx()
                ):
                    return await self._call_provider(
                        provider, context_blocks, image=image, task=self.ANSWER_TASK
                    )
        except TimeoutError as exc:
            logger.warning("tutor: generation stage exceeded its wall-clock ceiling")
            raise ProviderError("generation stage timed out") from exc
        except ProviderError:
            # Circuit breaker opened or provider error
            if self._router is not None and fallback is not None and self._router.fallback_active:
                logger.warning("tutor: primary provider failed, using fallback", exc_info=True)
                return await self._call_provider(
                    fallback, context_blocks, image=image, task=self.ANSWER_TASK
                )
            raise
        except CircuitOpenError:
            # Circuit is open — try fallback
            if fallback is not None:
                logger.warning("tutor: circuit breaker OPEN, using fallback provider")
                return await self._call_provider(
                    fallback, context_blocks, image=image, task=self.ANSWER_TASK
                )
            raise ProviderError(
                f"AI provider unavailable (circuit OPEN for {provider.name}; no fallback configured)"
            ) from None

    @staticmethod
    async def _call_provider(
        provider: LLMProvider, context_blocks: str, *, image: dict | None, task: str
    ) -> str:
        """One non-streaming provider call with the task's sampling profile."""
        return await provider.generate(
            context_blocks,
            system=SYSTEM_PROMPT,
            **_provider_call_kwargs(provider, image=image, task=task),
        )

    def _post_check(self, question: str, answer: str, hits: list) -> tuple[bool, str | None, str]:
        """Post-generation grounding enforcement (AUD-A2-03 / A6-01, A6-04).

        Returns ``(ok, refused_reason, numeric_verdict)``. Three checks run in
        order of how strongly a failure contradicts the evidence:

        1. arithmetic: an evaluable expression in the question whose stated
           result is wrong is a ``numeric_mismatch`` -- the strongest signal;
        2. citation overlap: an answer that leans on material outside the
           retrieved evidence fails the citation check (metered, logged);
        3. otherwise the answer passes and the numeric verdict is returned for
           the response label (``verified`` / ``unverified`` / ``not_applicable``).

        Callers never show a failed answer: the non-stream path regenerates
        once then abstains, the stream path replaces the answer in the final
        event (tokens already sent are superseded by that event).
        """
        from bangla_gpt_api.services.numeric_check import check_numeric_answer
        from bangla_gpt_api.services.safety import verify_citation

        numeric = check_numeric_answer(question, answer)
        if numeric == "mismatch":
            RAG_GATE_REFUSALS_TOTAL.labels(reason="numeric_mismatch").inc()
            logger.warning("numeric_check_failed: stated result contradicts the question")
            return False, "numeric_mismatch", numeric
        citation_ok = verify_citation(answer, " ".join(h.chunk.text for h in hits))
        RAG_CITATION_CHECKS_TOTAL.labels(result="pass" if citation_ok else "fail").inc()
        if not citation_ok:
            logger.warning(
                "citation_check_failed: grounded answer leans on material "
                "outside the retrieved evidence"
            )
            return False, "citation_unverified", numeric
        return True, None, numeric

    def _assemble(
        self,
        answer: str,
        hits: list,
        *,
        question: str,
        route: str,
        provider: LLMProvider,
        context_blocks: str,
        started: float,
    ) -> AskResponse:
        """Verify grounding, attach sources, and derive confidence.

        A6-01/AUD-A2-03: the post-generation checks are enforced, not advisory
        -- an answer that fails either check is replaced by the honest
        non-answer. Every response is produced here so the
        grounded/sources/confidence triple cannot drift between call sites."""
        from bangla_gpt_api.services.safety import answer_confidence

        if self._router is not None:
            self._router.record_result(True)
        json_log(
            logger,
            logging.INFO,
            "ai_call",
            route=getattr(route, "value", route),
            model=getattr(provider, "name", "unknown"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_chars=len(context_blocks),
            answer_chars=len(answer),
        )
        refs = self._sources(hits)
        refused = _model_refused(answer)
        if refused:
            RAG_GATE_REFUSALS_TOTAL.labels(reason="model_refused").inc()
            record_tutor_answer("tutor", "refused")
            return AskResponse(
                answer=answer,
                grounded=False,
                sources=[],
                citation_verified=None,
                refused_reason="model_refused",
                confidence=answer_confidence(False, "model_refused", []),
            )
        ok, fail_reason, numeric = self._post_check(question, answer, hits)
        if not ok:
            # The evidence does not support this answer (or its arithmetic
            # contradicts the question): never shown. ask() has already spent
            # its one regeneration attempt before this runs.
            return self._refusal(INSUFFICIENT_EVIDENCE_ANSWER, fail_reason or "citation_unverified")
        record_tutor_answer("tutor", "answered")
        return AskResponse(
            answer=answer,
            grounded=True,
            sources=refs,
            citation_verified=True,
            numeric_check=numeric,
            confidence=answer_confidence(
                True, None, [float(getattr(r, "score", 0.0)) for r in refs]
            ),
        )

    async def ask(
        self,
        question: str,
        class_level: int,
        subject: str | None = None,
        history: list[dict[str, str]] | None = None,
        chapter: str | None = None,
        extra_instruction: str | None = None,
        low_data: bool = False,
        context: RequestContext | None = None,
        search_query: str | None = None,
        image: dict | None = None,
    ) -> AskResponse:
        """One tutoring turn: safety screen → retrieve → gate → generate.

        ``search_query`` overrides what retrieval/coverage-gate run on while
        ``question`` still feeds the evidence prompt and routing (intent:
        quiz-explain turns retrieve on the quiz item, not the generic
        'explain this' phrasing, which dilutes gate coverage).

        ``image`` (already route-validated: mime + decoded size) is
        forwarded to the provider as an inline part; retrieval still runs on
        the text. The fast lane never carries images (vision needs the full
        model).
        """
        question = normalize_query(question)
        if search_query is not None:
            search_query = normalize_query(search_query)
        unsafe = _screen_safety(question)
        if unsafe:
            refusal_copy, reason = unsafe
            return self._refusal(refusal_copy, reason)
        # AUD-A2-17: sanitize the image before anything is spent on it.
        image, image_error = sanitize_image_payload(image)
        if image_error is not None:
            return self._refusal(IMAGE_UNREADABLE_ANSWER, image_error)

        # search_query is a deliberate override (quiz-explain): never rewritten.
        retrieval_query = search_query or self._conversation_retrieval_query(question, history)
        # Retrieval is synchronous CPU work (BM25 scan + rerank over the whole
        # corpus); offloaded off the event loop so a 120-250 ms p95 search no
        # longer freezes concurrent SSE streams on the same worker. The stage
        # ceiling lives in _retrieve_with_timeout (A6-06).
        hits, retrieval_ms, coverage_value, gate_pass = await self._retrieve_and_gate(
            retrieval_query, class_level, subject, chapter
        )
        # Retrieval telemetry. Logged without the question text: the privacy
        # posture of this service is that student wording is PII-adjacent and
        # is never written to logs (ask() redacts it before it leaves here).
        json_log(
            logger,
            logging.INFO,
            "tutor_retrieval",
            retrieval_ms=retrieval_ms,
            evidence_chunks=len(hits),
            top_score=(round(hits[0].score, 4) if hits else None),
            coverage=coverage_value,
            gate="pass" if gate_pass else "refuse",
        )
        self._trace_retrieval(
            hits,
            retrieval_ms=retrieval_ms,
            coverage=coverage_value,
            gate_pass=gate_pass,
            # A10-01: filter VALUES only (never the query text), so a trace
            # can reproduce the served slice.
            filters={"class_level": class_level, "subject": subject, "chapter": chapter},
        )
        if not gate_pass:
            return self._refusal(INSUFFICIENT_EVIDENCE_ANSWER, "insufficient_evidence")
        context_blocks = self._prompt_blocks(
            hits,
            question,
            history,
            extra_instruction=extra_instruction,
            context=context,
            low_data=low_data,
        )
        set_current_context(context)
        route = classify(question, goal=context.goal if context is not None else None)
        set_current_route(route)
        provider, provider_for_call = await self._select_provider(
            context_blocks, image=image, route=route
        )
        started = time.perf_counter()

        answer = await self._generate(context_blocks, image=image, provider=provider_for_call)
        self._trace_generation(
            route=route,
            provider=provider_for_call,
            prompt_text=context_blocks,
            answer=answer,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        answer = await self._regenerate_if_ungrounded(
            answer,
            hits=hits,
            question=question,
            route=route,
            provider=provider_for_call,
            history=history,
            context=context,
            low_data=low_data,
            image=image,
            extra_instruction=extra_instruction,
        )
        return self._assemble(
            answer,
            hits,
            question=question,
            route=route,
            provider=provider,
            context_blocks=context_blocks,
            started=started,
        )

    async def _regenerate_if_ungrounded(
        self,
        answer: str,
        *,
        hits: list,
        question: str,
        route: Any,
        provider: LLMProvider,
        history: list[dict[str, str]] | None,
        context: RequestContext | None,
        low_data: bool,
        image: dict | None,
        extra_instruction: str | None = None,
    ) -> str:
        """One bounded regeneration when the first answer fails the checks.

        A6-01/AUD-A2-03: the retry carries an explicit demand to stay inside
        <evidence>; if it also fails, ``_assemble`` abstains instead of showing
        it. A model refusal is not retried -- there is nothing to ground.

        A11-04: the caller's instruction (an explicit student-chosen strategy
        or the re-teach swap) SURVIVES the retry. The retry prompt used to
        replace it, so a strategy-chip answer that failed the grounding check
        came back as a strategy-less answer -- the chip silently stopped
        applying exactly when the student asked for help.
        """
        if _model_refused(answer):
            return answer
        first_ok, _, _ = self._post_check(question, answer, hits)
        if first_ok:
            return answer
        RAG_CITATION_CHECKS_TOTAL.labels(result="retry").inc()
        retry_instruction = (
            f"{GROUNDING_RETRY_INSTRUCTION}\n{extra_instruction}"
            if extra_instruction
            else GROUNDING_RETRY_INSTRUCTION
        )
        retry_blocks = self._prompt_blocks(
            hits,
            question,
            history,
            extra_instruction=retry_instruction,
            context=context,
            low_data=low_data,
        )
        retry_started = time.perf_counter()
        retry_answer = await self._generate(retry_blocks, image=image, provider=provider)
        self._trace_generation(
            route=route,
            provider=provider,
            prompt_text=retry_blocks,
            answer=retry_answer,
            latency_ms=int((time.perf_counter() - retry_started) * 1000),
        )
        return retry_answer

    async def ask_stream(
        self,
        question: str,
        class_level: int,
        subject: str | None = None,
        history: list[dict[str, str]] | None = None,
        chapter: str | None = None,
        extra_instruction: str | None = None,
        low_data: bool = False,
        context: RequestContext | None = None,
        search_query: str | None = None,
        image: dict | None = None,
    ) -> AsyncIterator["StreamEvent"]:
        """Streaming variant of:meth:`ask` (same ``search_query`` override and
        ``image`` forwarding rules).

        Yields ``StreamEvent`` items under the documented streaming contract
        (see ``STREAM_HEARTBEAT_SECONDS`` block above): zero or more ``token``
        events, ``heartbeat`` events when the provider is slow, at most one
        ``citation`` event for a grounded answer, an ``error`` event if the
        stream fails after it started, and exactly one ``final`` event
        carrying the complete AskResponse. ``final`` always supersedes what
        was streamed before it.
        """
        question = normalize_query(question)
        if search_query is not None:
            search_query = normalize_query(search_query)
        unsafe = _screen_safety(question)
        if unsafe:
            refusal_copy, reason = unsafe
            yield StreamEvent(type="token", text=refusal_copy)
            yield StreamEvent(
                type="final",
                response=AskResponse(answer=refusal_copy, grounded=False, refused_reason=reason),
            )
            RAG_GATE_REFUSALS_TOTAL.labels(reason=reason).inc()
            record_tutor_answer("tutor", "refused")
            return
        # AUD-A2-17: same second-pass image hygiene as the non-stream path.
        image, image_error = sanitize_image_payload(image)
        if image_error is not None:
            yield StreamEvent(type="token", text=IMAGE_UNREADABLE_ANSWER)
            yield StreamEvent(
                type="final",
                response=AskResponse(
                    answer=IMAGE_UNREADABLE_ANSWER, grounded=False, refused_reason=image_error
                ),
            )
            RAG_GATE_REFUSALS_TOTAL.labels(reason=image_error).inc()
            record_tutor_answer("tutor", "refused")
            return

        retrieval_query = search_query or self._conversation_retrieval_query(question, history)
        # Same event-loop offload and stage ceiling as the non-stream path: an
        # SSE turn must not stall other in-flight streams while it searches
        # the corpus (A6-06).
        hits, retrieval_ms, coverage_value, gate_pass = await self._retrieve_and_gate(
            retrieval_query, class_level, subject, chapter
        )
        json_log(
            logger,
            logging.INFO,
            "tutor_retrieval",
            stream=True,
            evidence_chunks=len(hits),
            top_score=(round(hits[0].score, 4) if hits else None),
            coverage=coverage_value,
            gate="pass" if gate_pass else "refuse",
        )
        self._trace_retrieval(
            hits,
            retrieval_ms=retrieval_ms,
            coverage=coverage_value,
            gate_pass=gate_pass,
            stream=True,
            # A10-01: same filter map as the non-stream path.
            filters={"class_level": class_level, "subject": subject, "chapter": chapter},
        )
        if not gate_pass:
            yield StreamEvent(type="token", text=INSUFFICIENT_EVIDENCE_ANSWER)
            RAG_GATE_REFUSALS_TOTAL.labels(reason="insufficient_evidence").inc()
            record_tutor_answer("tutor", "refused")
            yield StreamEvent(
                type="final",
                response=AskResponse(
                    answer=INSUFFICIENT_EVIDENCE_ANSWER,
                    grounded=False,
                    refused_reason="insufficient_evidence",
                ),
            )
            return

        context_blocks = self._prompt_blocks(
            hits,
            question,
            history,
            extra_instruction=extra_instruction,
            context=context,
            low_data=low_data,
        )
        set_current_context(context)
        route = classify(question, goal=context.goal if context is not None else None)
        set_current_route(route)
        # Only the effective provider matters on this path; the route-based
        # choice is reported by _select_provider's caller in ask().
        _, provider_for_stream = await self._select_provider(
            context_blocks, image=image, route=route
        )
        chunks: list[str] = []
        answer_is_grounded = True
        started = time.perf_counter()
        fallback_stream = self._fallback

        outage = False
        source = self._stream_with_fallback(
            context_blocks,
            provider=provider_for_stream,
            image=image,
            fallback=fallback_stream,
        )
        events = self._heartbeat_stream(source)
        try:
            async for kind, payload in events:
                if kind == "heartbeat":
                    # Liveness only: no answer content, sent while the provider
                    # is silent (documented streaming contract).
                    yield StreamEvent(
                        type="heartbeat",
                        extra={"interval_seconds": self.stream_heartbeat_seconds},
                    )
                    continue
                delta = payload
                if delta is _OUTAGE:
                    # No fallback could serve the stream; the caller emits the
                    # degraded/outage answer exactly once.
                    outage = True
                    break
                chunks.append(delta)
                yield StreamEvent(type="token", text=delta)
        finally:
            # The consumer closing this generator (SSE client disconnect) must
            # cancel the upstream call, not merely stop reading it (A6-06).
            await self._aclose(events)

        if outage:
            # A9-03: retrieval-only degraded mode. The provider is gone but
            # the evidence is not, so the student gets the retrieved
            # textbook passages with an explicit notice -- never presented as
            # a generated, grounded answer.
            answer_is_grounded = False
            degraded = self._evidence_only_answer(hits)
            chunks = [degraded]
            yield StreamEvent(
                type="error",
                extra={"code": "llm_unavailable", "recoverable": True, "degraded": "evidence_only"},
            )
            yield StreamEvent(type="token", text=degraded)

        if not chunks:
            # No chunks were yielded at all — provide a fallback response
            yield StreamEvent(type="token", text=_UNAVAILABLE_ANSWER)
            chunks = [_UNAVAILABLE_ANSWER]
            answer_is_grounded = False

        answer = "".join(chunks).strip()
        # Record result for circuit breaker
        if self._router is not None:
            self._router.record_result(True)
        self._trace_generation(
            route=route,
            provider=provider_for_stream,
            prompt_text=context_blocks,
            answer=answer,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        json_log(
            logger,
            logging.INFO,
            "ai_call_stream",
            route=route.value,
            model=getattr(provider_for_stream, "name", "unknown"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_chars=len(context_blocks),
            answer_chars=len(answer),
        )
        # Post-generation enforcement — same contract as _assemble
        # (AUD-A2-03): an outage notice or an empty stream is never verified
        # (there is no evidence-based text to vet); a grounded answer that
        # fails the citation or numeric check is replaced by the honest
        # non-answer in the final event. The client applies that event's
        # answer, superseding the tokens already streamed.
        numeric_verdict: str | None = None
        citation_ok = False
        refused_reason: str | None = None
        model_refused = _model_refused(answer)
        if answer_is_grounded and model_refused:
            # A "not in the textbook" reply is a refusal, not a grounded
            # answer (same honesty downgrade as the non-stream path).
            answer_is_grounded = False
        if model_refused:
            RAG_GATE_REFUSALS_TOTAL.labels(reason="model_refused").inc()
            refused_reason = "model_refused"
        elif answer_is_grounded:
            ok, fail_reason, numeric_verdict = self._post_check(question, answer, hits)
            if ok:
                citation_ok = True
            else:
                answer = INSUFFICIENT_EVIDENCE_ANSWER
                answer_is_grounded = False
                refused_reason = fail_reason
        record_tutor_answer("tutor", "answered" if answer_is_grounded else "refused")
        sources = self._sources(hits) if answer_is_grounded else []
        if answer_is_grounded:
            # A6-08/AUD-A2-16: the citation event carries the VALIDATED
            # source list (the answer passed the post-generation check), so a
            # client can render citations before the final event and no
            # citation is ever shown for a replaced answer.
            yield StreamEvent(
                type="citation",
                extra={
                    "sources": [s.model_dump(mode="json") for s in sources],
                    "citation_verified": True,
                    "numeric_check": numeric_verdict,
                },
            )
        yield StreamEvent(
            type="final",
            response=AskResponse(
                answer=answer,
                grounded=answer_is_grounded,
                sources=sources,
                # Contract parity with the non-stream path (and the seam
                # tests): a refusal carries no citation verdict, not a False
                # one -- None is the schema's documented "not applicable".
                citation_verified=citation_ok if answer_is_grounded else None,
                refused_reason=refused_reason,
                numeric_check=numeric_verdict if answer_is_grounded else None,
            ),
        )


@dataclass
class StreamEvent:
    """One item of a streaming tutoring turn."""

    type: str  # token | citation | heartbeat | error | final
    #: citation: {"sources": [...], "citation_verified": true}
    #: heartbeat: {"interval_seconds": n}; error: {"code", "recoverable"};
    #: final carries ``response``. See the streaming contract block above.
    text: str | None = None
    response: AskResponse | None = None
    extra: dict = field(default_factory=dict)
