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

import os
import time
from collections.abc import Sequence

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
    ) -> None:
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

    # ── protocol ─────────────────────────────────────────────────────────────
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed every text, batched; order preserved; raises on a bad response.

        No silent fallback: a failed embedding call is a provider error the
        caller must see, because a partly-embedded corpus would degrade the
        served index without any artifact saying so.
        """
        import httpx

        prepared = [self._prepare(text) for text in texts]
        vectors: list[list[float]] = []
        for start in range(0, len(prepared), MAX_BATCH_SIZE):
            batch = prepared[start : start + MAX_BATCH_SIZE]
            payload = {
                "requests": [
                    {
                        "model": f"models/{self._model}",
                        "content": {"parts": [{"text": text}]},
                        "outputDimensionality": self._dimensions,
                    }
                    for text in batch
                ]
            }
            url = f"{_API_BASE}/models/{self._model}:batchEmbedContents"
            attempt = 0
            while True:
                self._pace()
                try:
                    response = httpx.post(
                        url,
                        json=payload,
                        headers={"x-goog-api-key": self._api_key},
                        timeout=self._timeout,
                    )
                    if response.status_code == 429:
                        # The free tier answers 429 with a retry hint; honour it
                        # (or the documented backoff) instead of failing a run
                        # that is making progress one batch at a time.
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
            if len(embeddings) != len(batch):
                raise ProviderError(
                    f"gemini embeddings returned {len(embeddings)} vectors for {len(batch)} texts"
                )
            vectors.extend([list(map(float, item.get("values") or [])) for item in embeddings])
        return vectors

    def _pace(self) -> None:
        """Space the START of batch calls by the configured interval."""
        if self._min_interval <= 0:
            return
        delay = self._min_interval - (time.monotonic() - self._last_call)
        if delay > 0:
            time.sleep(delay)
        self._last_call = time.monotonic()

    @staticmethod
    def _retry_delay(response: object) -> float:
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

    def truncated_name(self) -> str:
        """The name recorded when any text was truncated (artifact honesty)."""
        return f"{self.name}:truncated"


def gemini_api_key_from_env() -> str:
    """The key from the environment, never from a logged/serialized source."""
    return (os.environ.get("GEMINI_API_KEY") or "").strip()
