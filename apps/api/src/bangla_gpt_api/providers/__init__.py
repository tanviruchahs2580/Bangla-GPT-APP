from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers.base import LLMProvider, ProviderNotConfigured
from bangla_gpt_api.providers.mock import MockLLMProvider

__all__ = ["LLMProvider", "ProviderNotConfigured", "get_provider"]


def get_provider(settings: Settings) -> LLMProvider:
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "mock":
        return MockLLMProvider()
    raise ProviderNotConfigured(
        f"LLM_PROVIDER={provider_name!r} is not implemented yet. "
        "Set LLM_PROVIDER=mock or configure a supported provider."
    )
