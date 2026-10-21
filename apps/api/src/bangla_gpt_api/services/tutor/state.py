"""The state `TutorService` owns, declared once for the split mixins (C-03).

``services/tutor.py`` was one 1814-line module: a class carrying both its state
and ~1300 lines of behaviour. The behaviour now lives in mixins (``retrieval``,
``generation``, ``assembly``, ``ask``, ``service``); this module is where the
attributes they share are declared -- annotations for what ``__init__`` sets,
and the class-level defaults for the knobs, exactly as the single class had
them, so a service handed to tests through ``TutorService.__new__`` still
resolves them instead of raising AttributeError.

The declaration is also the split's safety net: mypy checks
``TutorService.__init__`` against these annotations, so an attribute that gets
lost or retyped in a future move fails the type check instead of failing at
3am in the tutor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.retrieval.vocabulary import TermStats
from bangla_gpt_api.services.circuit_breaker import (
    CircuitBreaker,
    ProviderFallbackRouter,
)
from bangla_gpt_api.services.context import (
    EVIDENCE_TOKEN_BUDGET,
    TokenCounter,
)
from bangla_gpt_api.services.tutor.signals import STREAM_HEARTBEAT_SECONDS

# --- type-checking imports (generated) ---
if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterator,
    )
    from typing import (
        Any,
    )

    from bangla_gpt_api.providers.base import (
        LLMProvider,
    )
    from bangla_gpt_api.schemas import (
        AskResponse,
        SourceRef,
    )
    from bangla_gpt_api.services.context import (
        RequestContext,
    )
    from bangla_gpt_api.services.router import (
        Route,
    )


class TutorState:
    """Attributes ``TutorService.__init__`` sets, plus the knobs it defaults."""

    #: Per-task sampling profiles (A6-06): providers that declare
    #: ``supports_sampling`` receive these instead of the vendor defaults.
    ANSWER_TASK: ClassVar[str] = "tutor_answer"
    STREAM_TASK: ClassVar[str] = "tutor_stream"
    #: Class-level defaults for the knobs __init__ sets, so a service handed to
    #: tests through ``TutorService.__new__`` (the seam-test style) still
    #: resolves them instead of raising AttributeError.
    evidence_token_budget: int = EVIDENCE_TOKEN_BUDGET
    hint_first: bool = True
    stream_heartbeat_seconds: float = STREAM_HEARTBEAT_SECONDS
    index_version: str = ""  # __init__ overwrites with the corpus fingerprint
    _token_counter: TokenCounter | None = None
    _concurrency: Any | None = None
    #: Trigram similarity a near-identical evidence token must clear for a
    #: missed query term to still count as covered (see `_term_covered`).
    FUZZY_MATCH_SIMILARITY: ClassVar[float] = 0.6
    #: How many prior messages feed the conversational retrieval query.
    _FOLLOWUP_CONTEXT_TERMS: ClassVar[int] = 8

    # Written by `__init__`; annotated here so the mixins can use them.
    index: RankingIndex
    term_stats: TermStats | None
    provider: LLMProvider
    fast_provider: LLMProvider | None
    min_score: float
    min_coverage: float
    top_k: int
    _breaker: CircuitBreaker | None
    _fallback: LLMProvider | None
    _router: ProviderFallbackRouter | None

    # --- methods (type-checking only) ---
    if TYPE_CHECKING:
        # The method surface, declared for the type checker only: every one of
        # these is implemented by a mixin (retrieval / generation / assembly / ask
        # / service), and mypy checks each implementation against the signature
        # below. Learn the surface here; read the implementation in its seam.
        def _term_covered(self, term: str, evidence_terms: set[str]) -> bool: ...

        def _trace_retrieval(
            self,
            hits: list,
            *,
            retrieval_ms: int,
            coverage: float,
            gate_pass: bool,
            stream: bool = False,
            filters: dict[str, Any] | None = None,
        ) -> None: ...

        def _gate_query_terms(self, question: str) -> tuple[str, ...]: ...

        def _in_corpus_gate_terms(
            self, query_terms: tuple[str, ...]
        ) -> tuple[tuple[str, ...], bool]: ...

        def _best_hit_coverage(
            self, query_terms: tuple[str, ...], hits: list
        ) -> tuple[float, bool]: ...

        def _hit_coverage(self, hit: Any, query_terms: tuple[str, ...], weights: dict) -> float: ...

        def _coverage_details(self, question: str, hits: list) -> tuple[float, bool]: ...

        async def _retrieve_with_timeout(
            self, query: str, class_level: int, subject: str | None, chapter: str | None = None
        ) -> list: ...

        async def _retrieve_and_gate(
            self, query: str, class_level: int, subject: str | None, chapter: str | None
        ) -> tuple[list, int, float, bool]: ...

        def _gate(self, question: str, hits: list) -> bool: ...

        def _retrieve(
            self, question: str, class_level: int, subject: str | None, chapter: str | None = None
        ) -> list: ...

        def _conversation_retrieval_query(
            self, question: str, history: list[dict[str, str]] | None
        ) -> str: ...

        @staticmethod
        def _cited_sources(answer: str, hits: list) -> list: ...

        @staticmethod
        def _sources(hits: list) -> list[SourceRef]: ...

        def _trace_generation(
            self, *, route: object, provider: object, prompt_text: str, answer: str, latency_ms: int
        ) -> None: ...

        def _stream_with_fallback(
            self,
            context_blocks: str,
            *,
            provider: LLMProvider,
            image: dict | None,
            fallback: LLMProvider | None,
        ) -> AsyncIterator[Any]: ...

        @staticmethod
        async def _aclose(source: object) -> None: ...

        def _heartbeat_stream(
            self, source: AsyncIterator[Any]
        ) -> AsyncIterator[tuple[str, Any]]: ...

        def _evidence_only_answer(self, hits: list) -> str: ...

        async def _select_provider(
            self, context_blocks: str, *, image: dict | None, route: Route
        ) -> tuple[LLMProvider, LLMProvider]: ...

        def _pedagogy_instructions(
            self,
            question: str,
            *,
            context: RequestContext | None,
            extra_instruction: str | None,
            history: list[dict[str, str]] | None = None,
        ) -> list[str]: ...

        def _prompt_blocks(
            self,
            hits: list,
            question: str,
            history: list[dict[str, str]] | None,
            *,
            extra_instruction: str | None,
            context: RequestContext | None,
            low_data: bool,
        ) -> str: ...

        @staticmethod
        def _refusal(answer: str, reason: str) -> AskResponse: ...

        async def _generate(
            self, context_blocks: str, *, image: dict | None, provider: LLMProvider
        ) -> str: ...

        async def _generate_via_providers(
            self, context_blocks: str, *, image: dict | None, provider: LLMProvider
        ) -> str: ...

        @staticmethod
        async def _call_provider(
            provider: LLMProvider, context_blocks: str, *, image: dict | None, task: str
        ) -> str: ...

        def _post_check(
            self, question: str, answer: str, hits: list
        ) -> tuple[bool, str | None, str]: ...

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
        ) -> AskResponse: ...

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
        ) -> str: ...
