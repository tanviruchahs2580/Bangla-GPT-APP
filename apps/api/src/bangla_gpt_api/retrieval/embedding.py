"""S4.3 RAG v2 -- embedder abstraction with a deterministic local fallback.

Contract (spec 4.3): "multilingual embeddings". Real multilingual embedding
MODELS are a human/infra decision (R8): ``settings.embedding_model`` stays
empty in local/dev and the deterministic :class:`HashingEmbedder` serves the
vector lane. It is character n-gram hashing (no word tokenizer, so Bangla
grapheme clusters work directly), fixed-dimension, L2-normalised and fully
reproducible -- the same contract a real model must satisfy, so swapping in
a real embedder is a factory change, not a call-site change.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from bangla_gpt_api.providers.base import ProviderNotConfigured

# Letters+digits only: punctuation/hyphen n-grams are not semantic signal --
# they let a Latin gibberish string share trigrams ('-no', 'ot-') with Bengali
# curriculum text and score a fake vector hit (R12 grounding guard).
_LETTERS_RE = re.compile(r"[^0-9A-Za-z\u0980-\u09FF]+")

_EMBED_DIM = 384
_EMBED_NGRAMS = (2, 3, 4)


class Embedder(Protocol):
    """Text -> fixed-dimension float vector(s)."""

    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


_BANGLA_CHAR_RE = re.compile(r"[\u0980-\u09FF]")


def compact_bigrams(text: str) -> set[str]:
    """Character bigrams of the punctuation-stripped, lowercased text."""
    compact = _LETTERS_RE.sub("", text.strip().lower())
    return {compact[i : i + 2] for i in range(max(len(compact) - 1, 0))}


def bengali_bigrams(text: str) -> set[str]:
    """Bigrams containing at least one Bangla codepoint.

    A phonetic-spelling or morphological variant of a Bangla query always
    shares Bangla characters with the matching text. Shared LATIN bigrams
    between a gibberish query and ASCII inside the curriculum (variables
    ``x y``, function names ``sin cos``) are coincidences, not evidence.
    """
    return {g for g in compact_bigrams(text) if _BANGLA_CHAR_RE.search(g)}


class HashingEmbedder:
    """Deterministic char-ngram hashing embedder (dependency-free stand-in).

    Each character n-gram increments one of ``dim`` buckets, then the vector
    is L2-normalised, so cosine similarity approximates character n-gram
    overlap -- this captures Bangla morphological variants (ভগ্নাংশের ~
    ভগ্নাংশ) without any model download. Many grams share one bucket, so
    unrelated texts keep a small positive cosine from collisions and the
    vector lane must never stand alone as evidence: HybridIndex gates
    vector-only candidates on shared Bangla bigrams (:func:`bengali_bigrams`).
    """

    name = "hash-ngram-local"

    def __init__(self, dim: int = _EMBED_DIM, ngrams: tuple[int, ...] = _EMBED_NGRAMS) -> None:
        self.dim = dim
        self.ngrams = ngrams

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        compact = _LETTERS_RE.sub("", text.strip().lower())
        for n in self.ngrams:
            for i in range(max(len(compact) - n + 1, 0)):
                gram = compact[i : i + n]
                digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
                h = int.from_bytes(digest, "big")
                vec[h % self.dim] += 1.0
        return _l2_normalize(vec)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


def build_embedder(settings: object) -> Embedder:
    """Factory: local hashing embedder unless a real model is configured.

    R8: choosing/running a real multilingual embedding model (and pgvector)
    is staging human input. Until then ``EMBEDDING_MODEL`` stays empty and
    this returns the local embedder; naming one without the backend wired is
    a configuration error, not a silent downgrade.
    """
    model = str(getattr(settings, "embedding_model", "") or "").strip()
    if model:
        raise ProviderNotConfigured(
            f"embedding model '{model}' requires the staging embedding backend "
            "(human input, R8); leave EMBEDDING_MODEL empty for the local vector lane"
        )
    return HashingEmbedder()
