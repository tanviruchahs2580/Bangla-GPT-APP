from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers.base import (
    LLMProvider,
    ProviderError,
    ProviderNotConfigured,
    ProviderSettings,
)
from bangla_gpt_api.providers.mock import MockLLMProvider

__all__ = [
    "LLMProvider",
    "ProviderError",
    "ProviderNotConfigured",
    "get_provider",
    "get_fast_provider",
    "get_fallback_provider",
]


def _build_provider(settings: ProviderSettings) -> LLMProvider:
    """Build an LLM provider from settings (single provider)."""
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "mock":
        return MockLLMProvider()
    if provider_name == "gemini":
        from bangla_gpt_api.providers.gemini import build_gemini_provider

        return build_gemini_provider(settings)
    if provider_name == "openai":
        from bangla_gpt_api.providers.openai import build_openai_provider

        return build_openai_provider(settings)
    raise ProviderNotConfigured(
        f"LLM_PROVIDER={provider_name!r} is not implemented yet. Set LLM_PROVIDER to mock, gemini, or openai."
    )


def get_provider(settings: Settings) -> LLMProvider:
    """Get the primary LLM provider from settings."""
    return _build_provider(settings)


def get_fast_provider(settings: Settings) -> LLMProvider:
    """Get the fast/lite provider for SIMPLE routes.

    Uses ``gemini_fast_model`` (or the provider's fast model) when the
    primary provider is Gemini; delegates to ``get_provider`` for OpenAI
    (OpenAI has no separate fast model — it uses the same client).
    Raises ProviderNotConfigured when the fast model is not set.
    """
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "gemini":
        fast_model = (settings.gemini_fast_model or "").strip()
        if not fast_model:
            raise ProviderNotConfigured(
                "GEMINI_FAST_MODEL is not set. "
                "Set GEMINI_FAST_MODEL to a model id (e.g. gemini-2.5-flash-lite) "
                "or leave LLM_PROVIDER=mock for single-model mode."
            )
        from bangla_gpt_api.providers.gemini import build_gemini_provider

        return build_gemini_provider(settings, model=fast_model)
    if provider_name == "openai":
        # OpenAI providers have no separate "fast" model; fall back to the
        # main provider (same client, same model) — the router still logs
        # the SIMPLE route and uses the same provider.
        from bangla_gpt_api.providers.openai import build_openai_provider

        return build_openai_provider(settings)
    if provider_name == "mock":
        return MockLLMProvider()
    raise ProviderNotConfigured(
        f"LLM_PROVIDER={provider_name!r} does not support fast model routing."
    )


def get_fallback_provider(settings: Settings) -> LLMProvider | None:
    """Get the fallback LLM provider if configured.

    Returns None when llm_fallback_provider is empty or when the fallback
    provider is the same as the primary (no point falling back to self).
    """
    fallback_name = (settings.llm_fallback_provider or "").strip().lower()
    primary_name = settings.llm_provider.strip().lower()
    if not fallback_name or fallback_name == primary_name:
        return None
    # Rebuild settings with the fallback provider and appropriate API key
    # We create a lightweight adapter that swaps the provider name and its
    # corresponding API key/model settings.
    fallback_settings = _adapt_settings_for_fallback(settings, fallback_name)
    if fallback_settings is None:
        return None
    return _build_provider(fallback_settings)


def _adapt_settings_for_fallback(settings: Settings, fallback_name: str) -> ProviderSettings | None:
    """Create a Settings-like object with the fallback provider configured.

    This copies the core settings (timeout, retries) but swaps the provider-
    specific fields (API key, model) for the fallback provider.
    """
    if fallback_name == "gemini":
        if not settings.gemini_api_key:
            return None
        return _FallbackSettings(
            llm_provider="gemini",
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_model,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            llm_max_retries=settings.llm_max_retries,
        )
    if fallback_name == "openai":
        if not settings.openai_api_key:
            return None
        return _FallbackSettings(
            llm_provider="openai",
            openai_api_key=settings.openai_api_key,
            openai_model=settings.openai_model,
            openai_base_url=settings.openai_base_url,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            llm_max_retries=settings.llm_max_retries,
        )
    return None


class _FallbackSettings:
    """Lightweight settings adapter for fallback provider building.

    Only the fields that _build_provider and provider constructors access
    are present, keeping this self-contained.
    """

    def __init__(
        self,
        llm_provider: str,
        gemini_api_key: str | None = None,
        gemini_model: str = "",
        openai_api_key: str | None = None,
        openai_model: str = "",
        openai_base_url: str | None = None,
        llm_timeout_seconds: float = 30.0,
        llm_max_retries: int = 2,
    ) -> None:
        self.llm_provider = llm_provider
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_base_url = openai_base_url
        self.llm_timeout_seconds = llm_timeout_seconds
        self.llm_max_retries = llm_max_retries

    @property
    def is_production(self) -> bool:
        return False  # fallback is never "production"

    @property
    def cors_origins(self) -> list[str]:
        return []
