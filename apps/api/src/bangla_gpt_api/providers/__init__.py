from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers.base import LLMProvider, ProviderError, ProviderNotConfigured
from bangla_gpt_api.providers.mock import MockLLMProvider

__all__ = [
    "LLMProvider",
    "ProviderError",
    "ProviderNotConfigured",
    "get_provider",
    "get_fast_provider",
]


def get_provider(settings: Settings) -> LLMProvider:
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "mock":
        return MockLLMProvider()
    if provider_name == "gemini":
        from bangla_gpt_api.providers.gemini import build_gemini_provider

        return build_gemini_provider(settings)
    raise ProviderNotConfigured(
        f"LLM_PROVIDER={provider_name!r} is not implemented yet. Set LLM_PROVIDER=mock or gemini."
    )


def get_fast_provider(settings: Settings) -> LLMProvider | None:
    """S4.2: separate client for SIMPLE routes. None -> the main provider
    serves every route (mock mode, or GEMINI_FAST_MODEL unset/equal)."""
    provider_name = settings.llm_provider.strip().lower()
    if provider_name != "gemini":
        return None
    fast = settings.gemini_fast_model.strip()
    if not fast or fast == settings.gemini_model:
        return None
    from bangla_gpt_api.providers.gemini import build_gemini_provider

    return build_gemini_provider(settings, model=fast)
