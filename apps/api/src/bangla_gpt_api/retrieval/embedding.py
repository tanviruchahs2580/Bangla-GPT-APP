"""RAG v2 -- embedder abstraction with a deterministic local fallback.

Contract (spec 4.3): "multilingual embeddings". Real multilingual embedding
MODELS are a human/infra decision: ``settings.embedding_model`` stays
empty in local/dev and the deterministic:class:`HashingEmbedder` serves the
vector lane. It is character n-gram hashing (no word tokenizer, so Bangla
grapheme clusters work directly), fixed-dimension, L2-normalised and fully
reproducible -- the same contract a real model must satisfy, so swapping in
a real embedder is a factory change, not a call-site change.
"""

import hashlib
import math
import re
import time
from collections.abc import Sequence
from typing import Protocol

import httpx

from bangla_gpt_api.providers.base import ProviderError, ProviderNotConfigured

# Letters+digits only: punctuation/hyphen n-grams are not semantic signal --
# they let a Latin gibberish string share trigrams ('-no', 'ot-') with Bengali
# curriculum text and score a fake vector hit (grounding guard).
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


_REMOTE_RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})
_REMOTE_MAX_ATTEMPTS = 3
_REMOTE_BATCH = 64


class RemoteEmbedder:
    """OpenAI-compatible ``/embeddings`` client (audit F-01/C2).

    Satisfies the same contract the local stand-in documents: fixed
    dimension, input-ordered batches, L2-normalisation on the way out. The
    corpus manifest check (:func:`_verify_embedder_identity`) applies to this
    lane too — a corpus measured with one embedder cannot be served with
    another; switching ``EMBEDDING_MODEL`` means rebuilding and re-measuring
    the corpus under the new name.
    """

    def __init__(
        self,
        *,
        model: str,
        api_base: str,
        api_key: str,
        timeout: float = 30.0,
        batch_size: int = _REMOTE_BATCH,
        transport: object | None = None,
    ) -> None:
        # plain attribute, not a property: the Embedder protocol declares a
        # mutable `name: str`, which a read-only property would not satisfy
        self.name = f"remote:{model}"
        self.model = model
        self.api_base = api_base.rstrip("/")
        # dimension is discovered from the endpoint's first response; the
        # manifest check skips the dim comparison until then
        self.dim: int | None = None
        self._api_key = api_key
        self._timeout = timeout
        self._batch_size = batch_size
        self._transport = transport  # test seam (httpx.MockTransport)

    def _client(self) -> "httpx.Client":
        return httpx.Client(
            base_url=self.api_base,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
            transport=self._transport,
        )

    def _post(self, batch: list[str]) -> list[list[float]]:
        last_status = -1
        with self._client() as client:
            for attempt in range(_REMOTE_MAX_ATTEMPTS):
                response = client.post(
                    "/embeddings",
                    json={"model": self.model, "input": batch, "encoding_format": "float"},
                )
                if response.status_code in _REMOTE_RETRYABLE and attempt + 1 < _REMOTE_MAX_ATTEMPTS:
                    time.sleep(min(0.5 * 2**attempt, 4.0))
                    last_status = response.status_code
                    continue
                if response.status_code != 200:
                    detail = response.text[:200]
                    hint = (
                        f" (after {attempt + 1} attempts, last status {last_status})"
                        if last_status >= 0
                        else ""
                    )
                    raise ProviderError(
                        f"embedding endpoint returned {response.status_code}{hint}: {detail}"
                    )
                return self._parse(response.json(), expected=len(batch))
        raise ProviderError("embedding endpoint exhausted retries")  # pragma: no cover

    def _parse(self, payload: object, expected: int) -> list[list[float]]:
        if not isinstance(payload, dict):
            raise ProviderError("embedding endpoint returned a non-object payload")
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) != expected:
            raise ProviderError(
                f"embedding endpoint returned {len(rows) if isinstance(rows, list) else 'no'} "
                f"vectors for {expected} inputs"
            )
        vectors: list[list[float]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ProviderError("embedding endpoint returned a malformed vector row")
            vector = row.get("embedding")
            if (
                not isinstance(vector, list)
                or not vector
                or not all(isinstance(v, (int, float)) for v in vector)
            ):
                raise ProviderError("embedding endpoint returned a non-numeric vector")
            if self.dim is None:
                self.dim = len(vector)
            elif len(vector) != self.dim:
                raise ProviderError(
                    f"embedding endpoint changed dimensions mid-corpus ({self.dim} -> {len(vector)})"
                )
            vectors.append([float(v) for v in vector])
        return vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), max(self._batch_size, 1)):
            batch = [texts[start + i] for i in range(min(self._batch_size, len(texts) - start))]
            vectors.extend(self._post(batch))
        return [_l2_normalize(v) for v in vectors]


def build_embedder(settings: object) -> Embedder:
    """Factory: local hashing embedder unless a real model is configured.

    Naming ``EMBEDDING_MODEL`` selects :class:`RemoteEmbedder` and requires
    the endpoint+key to come with it (``EMBEDDING_API_BASE``/``KEY``) — a
    model name without a backend is a configuration error, not a silent
    downgrade to the hashing lane, whose similarity semantics are entirely
    different.

    The embedder identity is checked against the corpus manifest
    (F-129/RAG-11) in BOTH lanes: a corpus measured with embedder A and
    served with embedder B has different vectors for the same chunks, so the
    recorded retrieval numbers no longer describe the deployment.
    """
    model = str(getattr(settings, "embedding_model", "") or "").strip()
    if not model:
        embedder: Embedder = HashingEmbedder()
    else:
        api_base = str(getattr(settings, "embedding_api_base", "") or "").strip()
        api_key = str(getattr(settings, "embedding_api_key", "") or "").strip()
        if not api_base or not api_key:
            raise ProviderNotConfigured(
                f"embedding model '{model}' needs EMBEDDING_API_BASE and EMBEDDING_API_KEY; "
                "leave EMBEDDING_MODEL empty for the local vector lane"
            )
        timeout = float(getattr(settings, "llm_timeout_seconds", 30.0) or 30.0)
        embedder = RemoteEmbedder(model=model, api_base=api_base, api_key=api_key, timeout=timeout)
    _verify_embedder_identity(settings, embedder)
    return embedder


def _verify_embedder_identity(settings: object, embedder: Embedder) -> None:
    """Refuse to serve a manifest-pinned corpus with a different embedder."""
    from pathlib import Path

    corpus_dir = str(getattr(settings, "nctb_corpus_dir", "") or "").strip()
    if not corpus_dir:
        return
    from bangla_gpt_api.nctb.manifest import corpus_manifest_path, read_json
    from bangla_gpt_api.retrieval.index_manifest import embedder_problems

    manifest_path = corpus_manifest_path(Path(corpus_dir))
    if not manifest_path.exists():
        return
    declared = (read_json(manifest_path).get("derived") or {}).get("embedder")
    problems = embedder_problems(declared, name=embedder.name, dim=getattr(embedder, "dim", None))
    if problems:
        raise ProviderNotConfigured(
            f"the corpus at {corpus_dir} was built and measured with a different "
            f"embedder ({'; '.join(problems)}); the recorded retrieval numbers "
            "would not describe this deployment"
        )
