"""AI-001/AI-003: provider/lane wiring contracts.

- AI-001: HybridIndex accepts ANY Embedder (Protocol) — the hash embedder is
  the default, not a hard coupling. A stub embedder proves the seam.
- AI-003: GEMINI_FAST_MODEL selects the SIMPLE-lane client; empty keeps the
  main model on every route (logged, intentional). OpenAI reuses its client.
"""

from collections.abc import Sequence

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers import get_fast_provider
from bangla_gpt_api.retrieval.embedding import HashingEmbedder, build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex


class _ZeroEmbedder:
    """Minimal Embedder stand-in: every text maps to the same unit vector."""

    name = "zero-test"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0] * 8 for _ in texts]


def test_hybrid_index_accepts_any_embedder() -> None:
    # Structural conformance is enforced by mypy (Embedder Protocol);
    # runtime proof is construction + retrieval through the injected lane.
    corpus = load_sample_corpus()
    index = HybridIndex(corpus, _ZeroEmbedder())
    hits = index.search("কোষ কী", class_level=6, subject="science", top_k=3)
    assert hits  # BM25 lane still retrieves; vector lane is swappable


def test_default_embedder_is_hashing() -> None:
    emb = build_embedder(Settings())
    assert isinstance(emb, HashingEmbedder)


def test_fast_provider_uses_configured_fast_model() -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="dummy-key",
        gemini_model="gemini-3.1-flash-lite",
        gemini_fast_model="gemini-2.5-flash-lite",
    )
    fast = get_fast_provider(settings)
    assert fast.model == "gemini-2.5-flash-lite"


def test_fast_provider_unset_means_main_model_serves_all() -> None:
    import pytest

    from bangla_gpt_api.providers.base import ProviderNotConfigured

    settings = Settings(llm_provider="gemini", gemini_api_key="dummy-key", gemini_fast_model="")
    with pytest.raises(ProviderNotConfigured):
        get_fast_provider(settings)


def test_openai_fast_lane_reuses_main_client() -> None:
    settings = Settings(llm_provider="openai", openai_api_key="dummy-key")
    fast = get_fast_provider(settings)
    assert fast.model == "gpt-4o-mini"
