"""A4-02: the real multilingual embedding lane behind the `Embedder` protocol.

Model: ``gemini-embedding-001`` (Gemini API "Embeddings" reference, retrieved
2026-10-20). Properties that matter to this project, recorded with the
retrieved page and date:

* **multilingual** covers Bangla directly (no transliteration trick), which is
  the requirement ``docs/RAG_ARCHITECTURE.md`` states for the vector lane;
* **3 072 output dimensions** by default, and the reference accepts
  ``outputDimensionality`` (Matryoshka truncation) — this module defaults to
  768 so the vector lane's memory profile stays the same order as the hashing
  lane's 384 and the index build stays inside its budget;
* **2 048 input tokens per text**; longer text is rejected by the API, so the
  adapter truncates on the *token* estimate (the configured TokenCounter) and
  says so in its name (``gemini:gemini-embedding-001:truncated``);
* **licence/terms**: the Gemini API terms — the same key, tier and data-use
  rules the generation lane already documents in
  ``docs/compliance/provider-terms.md`` (free tier uses submitted content for
  improvement; paid tier does not; 55-day abuse retention).

The lane is selected by configuration only: ``EMBEDDING_MODEL`` names the
model and ``build_embedder`` returns this adapter; with the variable empty the
deterministic :class:`HashingEmbedder` keeps serving (dev/CI, and the served
index's own artifact). Naming a model this module cannot call is a
configuration error, not a silent downgrade.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from bangla_gpt_api.providers.base import ProviderError

#: Models this adapter can call (prefix match, so dated variants work).
SUPPORTED_EMBEDDING_MODELS = ("gemini-embedding", "text-embedding-004")

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
#: Output dimensions requested per vector (Matryoshka truncation).
DEFAULT_EMBEDDING_DIMENSIONS = 768
#: The reference's per-text input ceiling, in tokens.
MAX_INPUT_TOKENS = 2048
#: The endpoint accepts up to 100 requests per batch call.
MAX_BATCH_SIZE = 100
#: Free-tier keys cap embed requests per minute; a batch of N texts counts as
#: N requests, so a corpus-sized run needs pacing between BATCH calls. Reads
#: from the environment so the evaluation harness can pace without a code
#: change; 0 disables it (paid tiers).
MIN_INTERVAL_ENV = "EMBEDDING_MIN_INTERVAL_SECONDS"
#: Optional on-disk vector cache (append-only JSONL). Unset means no cache.
CACHE_PATH_ENV = "EMBEDDING_CACHE_PATH"
#: Seconds to wait after a 429 when the response carries no Retry-After.
RATE_LIMIT_BACKOFF_SECONDS = 30.0
#: How many times a single batch is retried on 429 before the run fails.
MAX_RATE_LIMIT_RETRIES = 6
_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiEmbedder:
    """`Embedder` implementation over the Gemini batchEmbedContents endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
        min_interval_seconds: float | None = None,
        transport: Any | None = None,
        cache_path: Path | None = None,
    ) -> None:
        #: Caller-injected transport (tests, or a proxy): anything with an
        #: httpx-compatible ``post(url, json=..., headers=..., timeout=...)``.
        self._transport = transport
        if not api_key:
            raise ProviderError("GeminiEmbedder requires an API key")
        self._api_key = api_key
        self._model = model
        self._dimensions = int(dimensions)
        self._timeout = float(timeout_seconds)
        self._max_retries = max(0, int(max_retries))
        if min_interval_seconds is None:
            raw = (os.environ.get(MIN_INTERVAL_ENV) or "").strip()
            min_interval_seconds = float(raw) if raw else 0.0
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._last_call = 0.0
        self.name = f"gemini:{model}"
        # A4-02: an append-only cache keyed by (model, dimensions, text hash).
        # The free tier's daily embedding quota is smaller than the served
        # corpus, and a corpus run that loses its work to a 429 cannot be
        # completed within one day without it; the cache also makes a re-run
        # after a corpus change cost only the changed texts.
        if cache_path is None:
            env_path = (os.environ.get(CACHE_PATH_ENV) or "").strip()
            cache_path = Path(env_path) if env_path else None
        self._cache_path = Path(cache_path) if cache_path is not None else None
        self._cache: dict[str, list[float]] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self._load_cache()

    # ── cache ────────────────────────────────────────────────────────────────
    def _cache_key(self, text: str) -> str:
        raw = f"{self._model}|{self._dimensions}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load_cache(self) -> None:
        if self._cache_path is None or not self._cache_path.is_file():
            return
        with self._cache_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._cache[row["key"]] = [float(value) for value in row["values"]]
                except (ValueError, KeyError, TypeError):
                    continue  # a torn tail line is skipped, never fatal

    def _store(self, rows: list[tuple[str, list[float]]]) -> None:
        if self._cache_path is None or not rows:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_path.open("a", encoding="utf-8") as handle:
            for key, values in rows:
                handle.write(json.dumps({"key": key, "values": values}) + "\n")
                self._cache[key] = values

    # ── protocol ─────────────────────────────────────────────────────────────
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed every text, batched; order preserved; raises on a bad response.

        No silent fallback: a failed embedding call is a provider error the
        caller must see, because a partly-embedded corpus would degrade the
        served index without any artifact saying so. Cached vectors are served
        from the cache and never re-requested.
        """
        prepared = [self._prepare(text) for text in texts]
        vectors: list[list[float]] = []
        pending: list[tuple[int, str, str]] = []  # (index, cache key, text)
        for position, text in enumerate(prepared):
            key = self._cache_key(text)
            cached = self._cache.get(key)
            if cached is not None:
                self.cache_hits += 1
                vectors.append(cached)
                continue
            self.cache_misses += 1
            vectors.append([])  # placeholder, filled below
            pending.append((position, key, text))
        for start in range(0, len(pending), MAX_BATCH_SIZE):
            chunk = pending[start : start + MAX_BATCH_SIZE]
            fetched = self._embed_batch([text for _index, _key, text in chunk])
            self._store(
                [(key, vec) for (_index, key, _text), vec in zip(chunk, fetched, strict=True)]
            )
            for (position, _key, _text), vector in zip(chunk, fetched, strict=True):
                vectors[position] = vector
        return vectors

    def _batch_request(self, text: str) -> dict[str, Any]:
        """One entry of a batchEmbedContents request."""
        return {
            "model": f"models/{self._model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": self._dimensions,
        }

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """Embed one batch (at most ``MAX_BATCH_SIZE`` texts), in input order.

        Paces the call and delegates the transport+retry story to
        :meth:`_post_batch`: a 429 is progress-not-failure, because a
        corpus-sized run must keep making one batch at a time.
        """
        payload = {"requests": [self._batch_request(text) for text in batch]}
        return self._post_batch(payload, len(batch))

    def _post_batch(self, payload: dict[str, Any], expected: int) -> list[list[float]]:
        """POST one batch, retrying 429s with the vendor hint; returns vectors.

        Split out of :meth:`_embed_batch` so both stay readable: this is the
        transport+retry story, the caller is the batching story.
        """
        url = f"{_API_BASE}/models/{self._model}:batchEmbedContents"
        attempt = 0
        while True:
            self._pace()
            try:
                response = self._post(url, json=payload)
                if response.status_code == 429:
                    if attempt >= MAX_RATE_LIMIT_RETRIES:
                        raise ProviderError(
                            "gemini embeddings rate-limited: "
                            f"{MAX_RATE_LIMIT_RETRIES} retries exhausted ({response.text[:120]})"
                        )
                    attempt += 1
                    time.sleep(self._retry_delay(response))
                    continue
                response.raise_for_status()
                body = response.json()
                break
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise ProviderError(
                        f"gemini embeddings failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                attempt += 1
        embeddings = body.get("embeddings") or []
        if len(embeddings) != expected:
            raise ProviderError(
                f"gemini embeddings returned {len(embeddings)} vectors for {expected} texts"
            )
        return [list(map(float, item.get("values") or [])) for item in embeddings]

    def _post(self, url: str, **kwargs: Any) -> Any:
        """One POST through the injected transport or httpx itself."""
        post = getattr(self._transport, "post", None) or httpx.post
        kwargs.setdefault("headers", {"x-goog-api-key": self._api_key})
        kwargs.setdefault("timeout", self._timeout)
        return post(url, **kwargs)

    def _pace(self) -> None:
        """Space the START of batch calls by the configured interval."""
        if self._min_interval <= 0:
            return
        delay = self._min_interval - (time.monotonic() - self._last_call)
        if delay > 0:
            time.sleep(delay)
        self._last_call = time.monotonic()

    @staticmethod
    def _retry_delay(response: Any) -> float:
        """The vendor's Retry-After when present, else the documented backoff."""
        headers = getattr(response, "headers", {}) or {}
        raw = str(headers.get("retry-after") or "").strip()
        try:
            return max(float(raw), 1.0) if raw else RATE_LIMIT_BACKOFF_SECONDS
        except ValueError:
            return RATE_LIMIT_BACKOFF_SECONDS

    # ── preparation ──────────────────────────────────────────────────────────
    def _prepare(self, text: str) -> str:
        """Truncate to the model's input ceiling before the call.

        The estimate uses ``services.context.TokenCounter`` (the calibrated
        upper bound by default), so the truncation is conservative: a text at
        the ceiling is cut below it rather than rejected by the API mid-run.
        """
        from bangla_gpt_api.services.context import token_counter

        clean = " ".join((text or "").split())
        if not clean:
            return "(empty)"  # the API rejects empty parts
        counter = token_counter()
        if counter.count(clean) <= MAX_INPUT_TOKENS:
            return clean
        words = clean.split(" ")
        keep = max(1, int(len(words) * MAX_INPUT_TOKENS / max(counter.count(clean), 1)))
        return " ".join(words[:keep])
