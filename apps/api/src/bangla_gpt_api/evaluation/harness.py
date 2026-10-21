"""Shared hermetic evaluation harness builders (one definition, many callers).

The CLI, the targets report and the stage-latency harness all need the same
"hermetic tutor": Settings(env="test", llm_provider="mock"), the bundled
sample corpus, the hybrid index the product serves and the mock provider.
Building it in three places would let the three drift (a different top_k, a
different provider) while every report still claims to measure the same
thing, so it lives here once.
"""

from __future__ import annotations

from typing import Any

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus


def hermetic_settings(**overrides: Any) -> Settings:
    """Settings that can never reach a network: env=test, provider=mock.

    Explicit overrides win (the stage harness raises the rate limits or sets
    a deterministic seed), but the provider cannot be overridden to a live
    one by these callers -- a live run is a human action on the real app.
    """
    return Settings(env="test", llm_provider="mock", **overrides)


def build_hermetic_tutor(settings: Settings) -> Any:
    """The tutor exactly as the CLI builds it: sample corpus + hybrid + mock."""
    from bangla_gpt_api.providers import get_provider
    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
    from bangla_gpt_api.services.tutor import TutorService

    index = HybridIndex(load_sample_corpus(), build_embedder(settings))
    provider = get_provider(settings)
    return TutorService(index=index, provider=provider, fast_provider=None)
