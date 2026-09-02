import math
import re
from collections import Counter
from dataclasses import dataclass

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.hybrid import expand_query, light_stem, trigram_similarity

_BANGLA_WORD_RE = re.compile(r"[A-Za-z0-9\u0980-\u09FF]+")

# Weight of the character-trigram fallback blended into the BM25 score.
_TRIGRAM_WEIGHT = 2.0


def tokenize(text: str) -> list[str]:
    """Tokenize keeping Bangla graphemes intact.

    ``\\w+`` splits on Bangla combining marks (vowel signs U+09BE-U+09CC,
    virama U+09CD), destroying words like 'বিশ্বকাপ'. The explicit range
    U+0980-U+09FF covers the full Bangla block incl. signs and digits.
    """
    return [match.group(0).lower() for match in _BANGLA_WORD_RE.finditer(text)]


@dataclass
class Hit:
    chunk: Chunk
    score: float


class BM25Index:
    """Lexical Okapi BM25 index over curriculum chunks.

    Intentionally dependency-free so the retrieval contract is testable now;
    a vector store can replace/augment it once infrastructure exists.
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
        self.term_freqs = [Counter(tokenize(chunk.text)) for chunk in chunks]
        self.doc_lengths = [sum(tf.values()) for tf in self.term_freqs]
        self.avgdl = (sum(self.doc_lengths) / len(self.doc_lengths)) if self.doc_lengths else 0.0
        self.doc_freq: Counter[str] = Counter()
        for tf in self.term_freqs:
            self.doc_freq.update(tf.keys())
        # Hybrid retrieval (A2): precomputed char-trigram sets per chunk for
        # the soft-match fallback signal.
        self._trigrams: list[frozenset[str]] | None = None

    def search(
        self,
        query: str,
        *,
        class_level: int | None = None,
        subject: str | None = None,
        top_k: int = 4,
        min_score: float = 0.0,
    ) -> list[Hit]:
        raw_terms = tokenize(query)
        # Query-side expansion: stems + curated synonyms improve recall for
        # paraphrased questions without touching document text.
        query_terms = expand_query([light_stem(t) for t in raw_terms])
        hits: list[Hit] = []
        for i, chunk in enumerate(self.chunks):
            if class_level is not None and chunk.meta.class_level != class_level:
                continue
            if subject is not None and chunk.meta.subject != subject:
                continue
            score = self._score(query_terms, i)
            if score <= min_score:
                soft = _TRIGRAM_WEIGHT * trigram_similarity(query, chunk.text)
                if soft > score:
                    score = soft
            else:
                score += 0.3 * _TRIGRAM_WEIGHT * trigram_similarity(query, chunk.text)
            if score > 0:
                hits.append(Hit(chunk=chunk, score=round(score, 4)))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

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
