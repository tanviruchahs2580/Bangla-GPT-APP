from collections.abc import AsyncIterator
from typing import Protocol


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """Upstream LLM failed after applying timeout/retry policy."""


class LLMProvider(Protocol):
    name: str

    async def generate(self, prompt: str, *, system: str | None = None) -> str: ...

    def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]: ...
