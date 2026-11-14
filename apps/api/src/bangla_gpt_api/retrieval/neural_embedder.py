"""RAG V5 (W2) — neural embedding adapter behind the existing Embedder
protocol.

Non-default by design (Master Prompt §5.5/§12 W2): the model-selection gate
is `BLOCKED_OWNER_DATA` — no human-reviewed Class 6 labels exist — so this
adapter ships for evaluation and explicit opt-in only, never as a hidden
default or a runtime fallback from a failing provider (V5 §8).

Identity contract (§4.2): ``name`` binds model id + immutable revision so
the corpus manifest identity check (F-129/RAG-11) can refuse a corpus
served with different vectors than it was measured with.

The backend is injected (anything with ``.encode(texts) ->
list[list[float]]`` — the sentence-transformers shape). Tests use a fake
backend: no model download, no network. E5-family query/document prefixes
are applied here because E5 models are trained with asymmetric inputs;
the prefixes are part of the recorded identity so a change invalidates the
manifest.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from bangla_gpt_api.retrieval.embedding import _l2_normalize

_E5_QUERY_PREFIX = "query: "
_E5_DOCUMENT_PREFIX = "passage: "


class _NeuralBackend(Protocol):
    """The slice of sentence-transformers the adapter depends on."""

    def encode(self, sentences: Sequence[str], **kwargs: Any) -> Any: ...


class NeuralEmbedder:
    """Local neural embedding lane (e5-family prefixes; L2-normalised)."""

    def __init__(
        self,
        *,
        model_id: str,
        dim: int,
        revision: str = "",
        backend: _NeuralBackend | None = None,
        e5_prefixes: bool = True,
        batch_size: int = 32,
    ) -> None:
        if not model_id:
            raise ValueError("model_id is required for the neural lane")
        self.model_id = model_id
        self.revision = revision
        self.dim = int(dim)
        self.batch_size = int(batch_size)
        self.e5_prefixes = e5_prefixes
        self._backend = backend
        # `name` is the identity the manifest gate checks.
        self.name = f"neural:{model_id}" + (f"@{revision}" if revision else "")
        if backend is None:
            # Lazy real-backend load: sentence-transformers is imported only
            # when the neural lane is actually selected (it is a heavy,
            # non-default dependency and must not sit on the startup path of
            # the default deployment).
            try:
                from sentence_transformers import (
                    SentenceTransformer,  # noqa: PLC0415 - lazy, non-default lane
                )
            except ImportError as exc:  # pragma: no cover - environment-specific
                raise ProviderNotInstalledNeural(
                    "EMBEDDING_PROVIDER=neural needs the sentence-transformers"
                    " dependency installed (non-default lane)"
                ) from exc
            self._backend = SentenceTransformer(model_id)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(list(texts), is_query=False)

    def embed_query(self, texts: Sequence[str]) -> list[list[float]]:
        """E5 asymmetric input: queries carry the `query:` instruction."""
        return self._encode(list(texts), is_query=True)

    def _encode(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        if not texts:
            return []
        if self._backend is None:  # pragma: no cover - constructor guarantees it
            raise RuntimeError("neural backend not initialised")
        prefix = ""
        if self.e5_prefixes:
            prefix = _E5_QUERY_PREFIX if is_query else _E5_DOCUMENT_PREFIX
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [prefix + t for t in texts[start : start + self.batch_size]]
            raw = self._backend.encode(batch, convert_to_numpy=False)
            for vec in raw:
                values = [float(v) for v in vec]
                if len(values) != self.dim:
                    raise ValueError(
                        f"neural embedder returned dim {len(values)}, expected {self.dim}"
                    )
                if not all(v == v and abs(v) != float("inf") for v in values):
                    raise ValueError("neural embedder returned a non-finite value")
                out.append(_l2_normalize(values))
        return out


class ProviderNotInstalledNeural(RuntimeError):
    """The neural lane was selected but its backend is not installed."""
