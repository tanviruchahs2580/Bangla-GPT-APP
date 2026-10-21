"""`TutorService` itself: the constructor, the streaming entry point
(`ask_stream`), and `StreamEvent`.

service — C-03 split of ``services/tutor.py``: moved verbatim;
`self` dispatch is unchanged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.metrics import (
    RAG_GATE_REFUSALS_TOTAL,
    record_tutor_answer,
)
from bangla_gpt_api.providers.base import (
    LLMProvider,
)
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.retrieval.vocabulary import TermStats
from bangla_gpt_api.schemas import AskResponse
from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)
from bangla_gpt_api.services.circuit_breaker import (
    CircuitBreaker,
    ProviderFallbackRouter,
)
from bangla_gpt_api.services.context import (
    EVIDENCE_TOKEN_BUDGET,
    RequestContext,
    TokenCounter,
    set_current_context,
)
from bangla_gpt_api.services.prompt_registry import (  # noqa: F401 (re-export)
    PROMPTS_DIR_ENV,
    PromptSpec,
    load_prompt,
    prompts_dir,
)
from bangla_gpt_api.services.router import (
    classify,
    set_current_route,
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
from bangla_gpt_api.services.trace_meta import index_fingerprint
from bangla_gpt_api.services.tutor.ask import TutorAskMixin
from bangla_gpt_api.services.tutor.assembly import TutorAssemblyMixin
from bangla_gpt_api.services.tutor.events import StreamEvent
from bangla_gpt_api.services.tutor.evidence import (  # noqa: F401
    normalize_query,
)
from bangla_gpt_api.services.tutor.generation import TutorGenerationMixin
from bangla_gpt_api.services.tutor.prompts import (  # noqa: F401
    _OUTAGE,
    _UNAVAILABLE_ANSWER,
    IMAGE_UNREADABLE_ANSWER,
    INSUFFICIENT_EVIDENCE_ANSWER,
)
from bangla_gpt_api.services.tutor.retrieval import TutorRetrievalMixin
from bangla_gpt_api.services.tutor.signals import (  # noqa: F401
    _model_refused,
    _screen_safety,
    hint_first_enabled,
    sanitize_image_payload,
    stream_heartbeat_seconds,
)

logger = logging.getLogger("bangla_gpt_api.tutor")


class TutorService(TutorRetrievalMixin, TutorGenerationMixin, TutorAssemblyMixin, TutorAskMixin):
    """C-03: composed from the three mixins; the public API is unchanged."""

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
    ) -> AsyncIterator[StreamEvent]:
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
        sources = self._sources(self._cited_sources(answer, hits)) if answer_is_grounded else []
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
