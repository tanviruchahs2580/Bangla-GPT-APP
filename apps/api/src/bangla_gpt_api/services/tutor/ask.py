"""The single-shot entry point (`ask`): build the answer and return it.
Its own seam because it and `ask_stream` are two code paths, not two
halves of one.

ask — C-03 split of ``services/tutor.py``: moved verbatim;
`self` dispatch is unchanged.
"""

from __future__ import annotations

import logging
import time

from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.schemas import AskResponse
from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)
from bangla_gpt_api.services.context import (
    RequestContext,
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
from bangla_gpt_api.services.tutor.evidence import (  # noqa: F401
    normalize_query,
)
from bangla_gpt_api.services.tutor.prompts import (  # noqa: F401
    IMAGE_UNREADABLE_ANSWER,
    INSUFFICIENT_EVIDENCE_ANSWER,
)
from bangla_gpt_api.services.tutor.signals import (  # noqa: F401
    _screen_safety,
    sanitize_image_payload,
)
from bangla_gpt_api.services.tutor.state import TutorState

logger = logging.getLogger("bangla_gpt_api.tutor")


class TutorAskMixin(TutorState):
    """See the module docstring."""

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
