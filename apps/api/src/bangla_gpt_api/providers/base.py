from collections.abc import AsyncIterator
from typing import Protocol


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """Upstream LLM failed after applying timeout/retry policy."""


class LLMProvider(Protocol):
    name: str

    async def generate(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> str: ...

    def stream(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> AsyncIterator[str]: ...


class ProviderSettings(Protocol):
    """Minimal settings surface consumed by provider builders.

    Both the real :class:`Settings` and the lightweight fallback adapter
    satisfy this structurally, so mypy can verify the fallback chain
    without coupling providers to the full application config.
    """

    llm_provider: str
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_model: str
    openai_base_url: str | None
    llm_timeout_seconds: float
    llm_max_retries: int
