import math
from collections import Counter
from dataclasses import dataclass

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.hybrid import (
    expand_query,
    light_stem,
    tokenize,
    trigram_jaccard,
    trigram_ngrams,
)
from bangla_gpt_api.retrieval.normalize import normalize_nfkc
from bangla_gpt_api.retrieval.query_analysis import english_gloss_terms, is_stop_word
from bangla_gpt_api.retrieval.vocabulary import CorpusVocabulary

# Weight of the character-trigram fallback blended into the BM25 score.
_TRIGRAM_WEIGHT = 2.0

# Public re-export: callers that imported the shared tokenizer from this
# module keep working (bm25 owned tokenize before the query-analysis layer
# needed it; hybrid.py is the shared leaf).
__all__ = ["BM25Index", "Hit", "indexable_text", "tokenize"]


@dataclass
class Hit:
    chunk: Chunk
    score: float


def indexable_text(chunk: Chunk) -> str:
    """What the lexical index (and the grounding gate) sees for a chunk.

    The section heading is indexed with double weight and the chapter with
    single weight, ahead of the body. This closes a measured defect: five of
    the golden chapter-title questions pointed at text that existed *only in
    the heading* ("সূচক কী" → section "সূচকের নিয়ম"), and the heading was
    invisible to the lexical lane, so those questions refused or mis-ranked
    while the evidence existed. Prominence comes from repetition — BM25 has no
    field model, and repeating rare heading terms is the cheapest way to give
    a title the same influence a body paragraph earns by length.

    The evidence *displayed* to the student stays ``chunk.text`` — indexing
    text and showing text are different obligations, deliberately separated.
    """
    section = chunk.meta.section or ""
    chapter = chunk.meta.chapter or ""
    parts = [section, section, chapter, chunk.text]
    return "\n".join(part for part in parts if part)


class BM25Index:
    """Lexical Okapi BM25 index over curriculum chunks.

    Intentionally dependency-free so the retrieval contract is testable now;
    a vector store can replace/augment it once infrastructure exists.

    Also owns the :class:`CorpusVocabulary` — document frequencies, the
    spelling lane and the Banglish lane — because all three are built from
    the same tokenised corpus scan this index already performs. Exposed as
    :attr:`term_stats` for the grounding gate, which needs document frequency
    to weight query terms.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        indexed = [indexable_text(chunk) for chunk in chunks]
        self.term_freqs = [Counter(tokenize(text)) for text in indexed]
        self.doc_lengths = [sum(tf.values()) for tf in self.term_freqs]
        self.avgdl = (sum(self.doc_lengths) / len(self.doc_lengths)) if self.doc_lengths else 0.0
        self.doc_freq: Counter[str] = Counter()
        for tf in self.term_freqs:
            self.doc_freq.update(tf.keys())
        # Hybrid retrieval (A2): char-trigram sets per chunk for the
        # soft-match fallback signal. A8: precomputed ONCE at build time —
        # recomputing them per query over the whole corpus was the hot path.
        self._trigrams: list[frozenset[str]] = [trigram_ngrams(chunk.text) for chunk in chunks]
        self.vocabulary = CorpusVocabulary.from_frequencies(self.doc_freq, len(chunks))

    @property
    def term_stats(self) -> CorpusVocabulary:
        """Corpus term statistics for the grounding gate and reranker."""
        return self.vocabulary

    def search(
        self,
        query: str,
        *,
        class_level: int | None = None,
        subject: str | None = None,
        chapter: str | None = None,
        top_k: int = 4,
        min_score: float = 0.0,
    ) -> list[Hit]:
        # One normalization at the query boundary (F-104): the tokenizer and
        # the trigram lane both fold through the shared normalizer, so a word
        # typed with a zero-width joiner or in the decomposed য় form ranks
        # like the word the corpus was ingested with.
        query = normalize_nfkc(query)
        raw_terms = tokenize(query)
        query_terms = expand_query(
            [light_stem(t) for t in raw_terms],
            extra=self._query_side_expansions(raw_terms),
        )
        query_grams = trigram_ngrams(query)
        hits: list[Hit] = []
        for i, chunk in enumerate(self.chunks):
            if class_level is not None and chunk.meta.class_level != class_level:
                continue
            if subject is not None and chunk.meta.subject != subject:
                continue
            if chapter is not None and chunk.meta.chapter != chapter:
                continue
            score = self._score(query_terms, i)
            if score <= min_score:
                soft = _TRIGRAM_WEIGHT * trigram_jaccard(query_grams, self._trigrams[i])
                if soft > score:
                    score = soft
            else:
                score += 0.3 * _TRIGRAM_WEIGHT * trigram_jaccard(query_grams, self._trigrams[i])
            if score > 0:
                hits.append(Hit(chunk=chunk, score=round(score, 4)))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _query_side_expansions(self, raw_terms: list[str]) -> list[str]:
        """Corpus-vocabulary expansions for code-switched and misspelled tokens.

        Three lanes, in priority order: an English/Banglish *glossary* term maps
        to its Bangla curriculum term (``cell`` → ``কোষ``); a Latin token that
        matches the romanised form of a corpus term rides the Banglish lane
        (``kosh`` → ``কোষ``); a Bangla token that is *not* corpus vocabulary
        but looks like a typo of one is repaired (``কোশ`` → ``কোষ``). Every
        expansion is then stemmed, exactly like the query terms it joins.

        Cost is bounded by construction: glossary lookups are dictionary hits,
        and the spelling/roman lanes only run for tokens they cannot find in
        the vocabulary — ordinary Bangla queries pay a set-membership test.
        """
        extras: list[str] = []
        seen = set(self.doc_freq)
        for token in raw_terms:
            if token.isascii():
                if len(token) < 2 or is_stop_word(token):
                    continue
                if token not in seen:
                    for term in english_gloss_terms(token):
                        extras.append(light_stem(term))
                if token not in seen:
                    for term in self.vocabulary.match_roman(token):
                        extras.append(light_stem(term))
                continue
            stemmed = light_stem(token)
            if stemmed in seen:
                continue
            for term in self.vocabulary.match_spelling(token):
                extras.append(light_stem(term))
        return [term for term in extras if term]

    def _score(self, query_terms: list[str], doc_index: int) -> float:
        total = 0.0
        doc_len = self.doc_lengths[doc_index] or 1
        tf_map = self.term_freqs[doc_index]
        n_docs = len(self.chunks)
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            df = self.doc_freq[term]
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            denom = tf + self.k1 * (1 - self.b + self.b * doc_len / (self.avgdl or 1.0))
            total += idf * (tf * (self.k1 + 1)) / denom
        return total
