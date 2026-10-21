"""Turning provider output into a validated answer: the post-check, the
assembly of the response body, and the one-shot grounding retry.

assembly — C-03 split of ``services/tutor.py``: moved verbatim;
`self` dispatch is unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.metrics import (
    RAG_CITATION_CHECKS_TOTAL,
    RAG_GATE_REFUSALS_TOTAL,
    record_tutor_answer,
)
from bangla_gpt_api.providers.base import (
    LLMProvider,
)
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
)
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
    GROUNDING_RETRY_INSTRUCTION,
    INSUFFICIENT_EVIDENCE_ANSWER,
)
from bangla_gpt_api.services.tutor.signals import (  # noqa: F401
    _model_refused,
)
from bangla_gpt_api.services.tutor.state import TutorState

logger = logging.getLogger("bangla_gpt_api.tutor")


class TutorAssemblyMixin(TutorState):
    """See the module docstring."""

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
        refs = self._sources(self._cited_sources(answer, hits))
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
