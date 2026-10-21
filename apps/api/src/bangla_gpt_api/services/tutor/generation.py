"""Provider selection, streaming plumbing (heartbeats, fallback, aclose) and
the generation calls themselves, including the pedagogy prompt blocks.

generation — C-03 split of ``services/tutor.py``: moved verbatim;
`self` dispatch is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from bangla_gpt_api import tracing
from bangla_gpt_api.logging_config import trace_event
from bangla_gpt_api.metrics import (
    RAG_GATE_REFUSALS_TOTAL,
    record_tutor_answer,
)
from bangla_gpt_api.providers.base import (
    LLMProvider,
    ProviderError,
    sampling_kwargs,
    stage_timeout_seconds,
)
from bangla_gpt_api.schemas import AskResponse
from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)
from bangla_gpt_api.services.circuit_breaker import (
    CircuitBreakerMiddleware,
    CircuitOpenError,
)
from bangla_gpt_api.services.context import (
    RequestContext,
)
from bangla_gpt_api.services.costs import estimate_tokens
from bangla_gpt_api.services.prompt_registry import (  # noqa: F401 (re-export)
    PROMPTS_DIR_ENV,
    PromptSpec,
    load_prompt,
    prompts_dir,
)
from bangla_gpt_api.services.router import (
    Route,
    fast_eligible,
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
from bangla_gpt_api.services.tutor.evidence import (  # noqa: F401
    build_evidence_prompt_with_selection,
    render_evidence,
)
from bangla_gpt_api.services.tutor.prompts import (  # noqa: F401
    _OUTAGE,
    _UNAVAILABLE_ANSWER,
    EVIDENCE_ONLY_HEADER,
    GOAL_STUDY,
    HINT_FIRST_INSTRUCTION,
    PROMPT_VERSION,
    STUDY_STEPS_INSTRUCTION,
    SYSTEM_PROMPT,
)
from bangla_gpt_api.services.tutor.signals import (  # noqa: F401
    _null_ctx,
    is_homework_like,
)
from bangla_gpt_api.services.tutor.state import TutorState

logger = logging.getLogger("bangla_gpt_api.tutor")


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


class TutorGenerationMixin(TutorState):
    """See the module docstring."""

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
