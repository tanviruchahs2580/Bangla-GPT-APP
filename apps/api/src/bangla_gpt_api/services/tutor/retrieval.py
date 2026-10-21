"""Retrieval, the grounding gate and citation selection. The gate is why
this cluster exists: it decides whether an answer is allowed at all, so it
reads as one unit instead of being interleaved with generation.

retrieval — C-03 split of ``services/tutor.py``: moved verbatim;
`self` dispatch is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from bangla_gpt_api.logging_config import json_log, trace_event
from bangla_gpt_api.metrics import (
    RAG_GATE_OUTCOMES_TOTAL,
    RAG_RETRIEVAL_LATENCY_SECONDS,
)
from bangla_gpt_api.providers.base import (
    stage_timeout_seconds,
)
from bangla_gpt_api.retrieval.bm25 import indexable_text, tokenize
from bangla_gpt_api.retrieval.hybrid import light_stem, trigram_similarity
from bangla_gpt_api.retrieval.query_analysis import (
    content_terms,
    coverage_weights,
    english_gloss_terms,
    weighted_coverage,
)
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
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
from bangla_gpt_api.services.tutor.evidence import (  # noqa: F401
    CITATION_SELECTION_FLOOR,
)
from bangla_gpt_api.services.tutor.state import TutorState

logger = logging.getLogger("bangla_gpt_api.tutor")


class TutorRetrievalMixin(TutorState):
    """See the module docstring."""

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

    def _gate_query_terms(self, question: str) -> tuple[str, ...]:
        """The question's gate vocabulary, resolved across scripts.

        Only **content terms** count (query_analysis: copulas, conjunctions,
        question particles, pronouns, postpositions in Bangla, Banglish and
        English) -- raw token coverage measurably refused answerable questions
        ("সালোকসংশ্লেষণ কী এবং কোথায় ঘটে?" scored 0.40 against its own section
        because কোথায় / ঘটে / এবং are function words a textbook passage cannot
        contain and the gate counted them as must-cover terms with equal
        weight). A question made only of function words falls back to every
        stemmed token, the pre-stop-word behaviour, rather than scoring an
        empty term set as instant groundability.

        Cross-script resolution: the retrieval lanes already widen a query
        through the glossary (cell → কোষ) and the roman lane (bhognangsho →
        ভগ্নাংশ); the gate must see the SAME resolved terms or it would refuse,
        for script reasons, a question retrieval just answered. Graceful
        degradation: statistics without the matching surfaces resolve nothing,
        and the gate proceeds on the raw terms.
        """
        query_terms = content_terms(question)
        if not query_terms:
            query_terms = tuple(
                dict.fromkeys(light_stem(t) for t in tokenize(question) if len(t) >= 2)
            )
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
        return tuple(dict.fromkeys(resolved))

    def _in_corpus_gate_terms(self, query_terms: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
        """Keep the terms the corpus knows; report when the question is OOD.

        Coverage is measured over the question's terms the corpus KNOWS about
        (df >= 1), weighted by ln(1 + N/df). Two documented reasons:

        * a term the corpus has never seen (ইউক্লিড, স্বতঃসিদ্ধ, ক্রিকেট) is the
          question's subject world, not the textbook's: the evidence cannot
          contain it, and its uncovered maximum weight is exactly what refuses
          an out-of-corpus question (the out-of-domain matrix row). A question
          whose content terms are ALL df=0 is therefore out-of-corpus by
          definition and refuses here;
        * terms the corpus does know carry ln(1 + N/df): missing a
          one-of-a-kind curriculum term dominates the verdict, while missing a
          term the whole book repeats costs little -- which is how "ভগ্নাংশ কী?
          explain করো" grounds on ভগ্নাংশ alone instead of being vetoed by the
          instruction word.

        The A4-06 out-of-domain rule (majority form): a question whose content
        terms are MOSTLY absent from the served index (more df==0 terms than
        known terms) is outside the textbook's world and refuses here, before
        weighting can answer it on its one lucky overlap. The strict ">= 2
        absent" count from the divergence register was measured and declined:
        it refuses 37-38% of ANSWERABLE chapter-title/Banglish questions on the
        served corpus (probe 2026-10-19), while the majority form separates the
        classes cleanly (4/4 curated adversarial refuse, 0/317 answerable).
        Subsumes the all-terms-absent refusal that sat here before (absent >
        known includes known == 0). Returns ``(terms, refuse)``.
        """
        if self.term_stats is None or self.term_stats.total_documents <= 0:
            return query_terms, False
        in_corpus = tuple(t for t in query_terms if self.term_stats.document_frequency(t) > 0)
        absent = len(query_terms) - len(in_corpus)
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
            return (), True
        if not in_corpus:
            # both counts zero: nothing measurable, refuse as before
            json_log(
                logger,
                logging.INFO,
                "tutor_retrieval",
                gate="out_of_domain",
                out_of_corpus_terms=len(query_terms),
            )
            return (), True
        return in_corpus, False

    def _best_hit_coverage(self, query_terms: tuple[str, ...], hits: list) -> tuple[float, bool]:
        """Weighted coverage of the best chunk, and whether any chunk passes.

        The verdict passes when ANY retrieved chunk clears the threshold:
        ranking noise between near-tied chunks must not flip a grounded
        question into a refusal. The evidence read is the text the lexical
        lane indexes (heading + chapter + body), so a chapter-title question
        can be satisfied by its own section heading.
        """
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
            coverage = self._hit_coverage(hit, query_terms, weights)
            best_coverage = max(best_coverage, coverage)
            if coverage >= self.min_coverage and hit.score > self.min_score:
                passed = True
        return round(best_coverage, 4), passed

    def _hit_coverage(self, hit: Any, query_terms: tuple[str, ...], weights: dict) -> float:
        """Weighted coverage of one retrieved chunk over the gate terms."""
        evidence_terms = {light_stem(t) for t in tokenize(indexable_text(hit.chunk))}
        covered = [t for t in query_terms if self._term_covered(t, evidence_terms)]
        return weighted_coverage(query_terms, covered, weights)

    def _coverage_details(self, question: str, hits: list) -> tuple[float, bool]:
        """Weighted content-term coverage of the best chunk, plus the verdict.

        Three phases, each with its own rationale and its own test surface:
        :meth:`_gate_query_terms` (what the question asks, resolved across
        scripts), :meth:`_in_corpus_gate_terms` (which of those terms the
        served corpus knows, and the A4-06 out-of-domain refusal) and
        :meth:`_best_hit_coverage` (the weighted coverage verdict over the
        retrieved chunks).
        """
        query_terms = self._gate_query_terms(question)
        if not query_terms or not hits:
            return 0.0, False
        query_terms, refuse = self._in_corpus_gate_terms(query_terms)
        if refuse:
            return 0.0, False
        return self._best_hit_coverage(query_terms, hits)

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

    def retrieved_sources(
        self, question: str, class_level: int, subject: str | None
    ) -> list[SourceRef]:
        """The passages retrieval returns for a question, as sources (A8-08).

        The evaluation needs both readings of citation precision: the
        passages the answer leaned on (which the response attaches) and the
        passages retrieval returned. This exposes the second without adding a
        field to the served response schema.
        """
        return self._sources(self._retrieve(question, class_level, subject))

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
    def _cited_sources(answer: str, hits: list) -> list:
        """The retrieved passages the answer actually leans on (A8-08).

        Per-passage stem coverage of the answer — the same primitive
        ``verify_citation`` thresholds over the concatenation — keeps the
        passages at or above :data:`CITATION_SELECTION_FLOOR`, in retrieval
        order. Measured on the frozen test set, the answer leans on 2 of the
        3 retrieved passages on average, and the ones it does not lean on are
        where the imprecise citations came from.

        An answer whose overlap is thin on every passage keeps its BEST
        passage rather than the whole retrieved set: the response must never
        lose its evidence because the overlap measurement came out low, but the
        passages it demonstrably does not lean on are exactly where the
        imprecise citations came from -- measured on the frozen split, attaching
        the whole set in that case is what kept section-granularity citation
        precision at 0.8802. One passage is always attached, so a reader can
        still follow the answer to its source.
        """
        from bangla_gpt_api.services.safety import citation_coverage

        scored = [(citation_coverage(answer, hit.chunk.text), hit) for hit in hits]
        selected = [hit for coverage, hit in scored if coverage >= CITATION_SELECTION_FLOOR]
        if selected:
            return selected
        # Thin everywhere: keep the best-covered passage, not the whole set.
        return [max(scored, key=lambda pair: pair[0])[1]] if scored else []

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
