"""RAG v2 — the cross-encoder rerank stage (pluggable, degrades safely).

The target flow's rerank stage is a cross-encoder; the served engine ships a
deterministic lexical feature ranker at exactly that stage
(`hybrid_index.make_lexical_rerank`). This module closes the gap the way the
index's own docstring anticipated: the cross-encoder DECORATES the lexical
ranker and replaces its ordering when it is configured and healthy.

Contract:

* `build_cross_encoder_config(settings)` — None for the default
  ``RAG_RERANKER="lexical"``; a validated config for ``"cross_encoder"``
  (endpoint + model both required, mirroring the ``embedding_model``
  doctrine: a model without a backend is a configuration error, never a
  silent downgrade; an unknown name is refused at boot).
* `CrossEncoderReranker(inner, config)` — on success the endpoint's
  normalized relevance scores drive the final ordering, with the lexical
  score kept as the BM25-magnitude floor so fusion-only chunks stay positive
  and everything that gates on ``Hit.score > 0`` keeps its meaning. On ANY
  failure (timeout, HTTP error, malformed body, protocol violation, open
  breaker) the inner scores are returned unchanged for that turn, a counter
  meters the fallback, and the breaker accumulates the failure — degrade,
  never lie, never refuse for reranker reasons.
* Egress discipline: the QUERY is student input and is PII-redacted before
  leaving the process (same discipline as the LLM path). Candidate documents
  are published textbook text — the same exposure class as the evidence the
  LLM already receives — and are sent as-is.

The HTTP contract is the standard rerank shape (TEI/Cohore-style):
``POST {endpoint}/rerank`` with ``{"model", "query", "documents"}`` →
``{"results": [{"index", "relevance_score"}]}``. No new dependencies: the
LLM providers' httpx stack is reused.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from bangla_gpt_api.metrics import RAG_LANE_LATENCY_SECONDS, RAG_RERANKER_FALLBACK_TOTAL
from bangla_gpt_api.retrieval.normalize import normalize_nfkc

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from bangla_gpt_api.curriculum.models import Chunk

logger = logging.getLogger(__name__)


class BreakerProtocol(Protocol):
    """The circuit-breaker surface this stage needs (injected, not imported:
    retrieval sits BELOW services in the import-linter layering)."""

    def allow_request(self) -> bool: ...  # pragma: no cover - protocol stub
    def record_failure(self) -> None: ...  # pragma: no cover - protocol stub
    def record_success(self) -> None: ...  # pragma: no cover - protocol stub


@dataclass(frozen=True)
class CrossEncoderConfig:
    endpoint: str
    model: str
    api_key: str | None
    timeout_seconds: float
    w_cross_encoder: float
    base_weight: float


class RerankerEndpointError(RuntimeError):
    """The rerank endpoint violated its contract (status, shape, indices)."""


def _endpoint_is_private_network(endpoint: str) -> bool:
    """True for the plain-HTTP deployments this stage permits (V4 S7).

    A self-hosted TEI box inside the operator's own network talks cleartext
    HTTP by design; the public internet must not. The RFC-1918 exception is
    granted only when the host IS a private/loopback/link-local IP *literal*
    (V4 review P1: matching the hostname string by prefix let public domains
    like `10.0.0.5.evil.test` or `10.com` classify as private). Explicit
    names (localhost, *.local) remain the only non-literal exceptions.
    """
    import ipaddress
    from urllib.parse import urlparse

    host = (urlparse(endpoint).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    if host.endswith(".local"):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def build_cross_encoder_config(settings: Any) -> CrossEncoderConfig | None:
    """The settings-to-stage bridge; None keeps the lexical default."""
    mode = (getattr(settings, "rag_reranker", "lexical") or "lexical").strip().lower()
    if mode == "lexical":
        return None
    if mode != "cross_encoder":
        raise ValueError(
            f"RAG_RERANKER={mode!r} is not an implemented reranker (lexical, cross_encoder)"
        )
    endpoint = (getattr(settings, "rag_reranker_endpoint", "") or "").strip()
    model = (getattr(settings, "rag_reranker_model", "") or "").strip()
    if not endpoint:
        raise ValueError(
            "RAG_RERANKER=cross_encoder requires RAG_RERANKER_ENDPOINT — a model "
            "without a backend is a configuration error, never a silent downgrade"
        )
    if not model:
        raise ValueError("RAG_RERANKER=cross_encoder requires RAG_RERANKER_MODEL")
    # Egress discipline (V4 S7): the student's query leaves the process for
    # this endpoint, so cleartext HTTP to the public internet is refused at
    # configuration time — not just in production. Plain HTTP stays legal
    # for the private-network deployments the stage documents.
    if not endpoint.lower().startswith("https://") and not _endpoint_is_private_network(endpoint):
        raise ValueError(
            f"RAG_RERANKER_ENDPOINT={endpoint!r} must use https — student queries "
            "egress to it; plain HTTP is allowed only for private-network hosts "
            "(localhost, RFC-1918 literals, *.local)"
        )
    return CrossEncoderConfig(
        endpoint=endpoint.rstrip("/"),
        model=model,
        api_key=(getattr(settings, "rag_reranker_api_key", "") or "").strip() or None,
        timeout_seconds=max(0.1, float(getattr(settings, "rag_reranker_timeout_seconds", 1.5))),
        w_cross_encoder=float(getattr(settings, "rag_w_cross_encoder", 1.0)),
        base_weight=float(getattr(settings, "rag_cross_encoder_base_weight", 0.15)),
    )


class CrossEncoderReranker:
    """Decorate the lexical ranker with the endpoint-driven ordering."""

    _inner: Callable[..., list[float]] | None

    def wrap(self, inner: Callable[..., list[float]]) -> None:
        """Attach the lexical ranker this stage decorates (index build)."""
        self._inner = inner

    def __init__(
        self,
        *,
        config: CrossEncoderConfig,
        redact: Callable[[str], str],
        transport: httpx.BaseTransport | None = None,
        breaker: BreakerProtocol | None = None,
    ) -> None:
        self._inner = None
        self._config = config
        # The egress redactor is INJECTED (services.pii sits above the
        # retrieval layer in the import-linter contracts); a required
        # parameter, so the stage cannot silently send a child's raw query.
        self._redact = redact
        # A per-instance client (connection reuse across turns); the
        # transport seam is what the tests point at (httpx.MockTransport).
        # The top-level httpx.post helper does not accept a transport.
        self._client = httpx.Client(transport=transport, timeout=config.timeout_seconds)
        # The breaker is injected too; without one the stage simply never
        # opens (every call attempts the endpoint, failures still fall back).
        self._breaker = breaker

    def rerank_remote(self, query: str, documents: Sequence[str]) -> list[float]:
        """Call the endpoint; raises `RerankerEndpointError` on any deviation."""
        redacted_query = self._redact(normalize_nfkc(query))
        payload: dict[str, Any] = {
            "model": self._config.model,
            "query": redacted_query,
            "documents": list(documents),
        }
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        try:
            response = self._client.post(
                f"{self._config.endpoint}/rerank",
                json=payload,
                headers=headers,
            )
        except Exception as exc:  # timeout, connect, TLS — one fallback class
            raise RerankerEndpointError(
                f"rerank endpoint unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise RerankerEndpointError(f"rerank endpoint status {response.status_code}")
        try:
            body = response.json()
            results = body["results"]
            pairs = ((int(r["index"]), float(r["relevance_score"])) for r in results)
            indexed = list(pairs)
        except Exception as exc:
            raise RerankerEndpointError(
                f"rerank endpoint malformed body: {type(exc).__name__}"
            ) from exc
        if len(indexed) != len(documents) or {i for i, _ in indexed} != set(range(len(documents))):
            raise RerankerEndpointError("rerank endpoint returned a mismatched result set")
        # results arrive in endpoint order; re-place them in DOCUMENT order
        scores = [0.0] * len(documents)
        for index, score in indexed:
            scores[index] = score
        return scores

    def __call__(self, query: str, candidates: list[tuple[Chunk, float, float]]) -> list[float]:
        if self._inner is None:  # pragma: no cover - wrap() runs at index build
            raise RuntimeError("CrossEncoderReranker.wrap() was never called")
        base = self._inner(query, candidates)
        if not candidates:
            return base
        if self._breaker is not None and not self._breaker.allow_request():
            return base
        started = time.perf_counter()
        try:
            raw = self.rerank_remote(query, [indexable_text_of(c) for c, _r, _b in candidates])
        except Exception as exc:
            if self._breaker is not None:
                self._breaker.record_failure()
            _meter_fallback(reason=type(exc).__name__)
            return base
        RAG_LANE_LATENCY_SECONDS.labels(lane="cross_encoder").observe(time.perf_counter() - started)
        if self._breaker is not None:
            self._breaker.record_success()
        return self._blend(base, raw)

    def _blend(self, base: list[float], raw: list[float]) -> list[float]:
        """Cross-encoder drives the ordering; the lexical score is the floor."""
        high, low = max(raw), min(raw)
        span = high - low
        normalized = [0.75] * len(raw) if span <= 0 else [(value - low) / span for value in raw]
        return [
            self._config.base_weight * base_value + self._config.w_cross_encoder * norm
            for base_value, norm in zip(base, normalized, strict=True)
        ]


def indexable_text_of(candidate: Chunk) -> str:
    """The text the endpoint sees — same text the lexical lane indexes."""
    from bangla_gpt_api.retrieval.bm25 import indexable_text

    return indexable_text(candidate)


def _meter_fallback(*, reason: str) -> None:
    RAG_RERANKER_FALLBACK_TOTAL.labels(reason=reason[:40]).inc()
