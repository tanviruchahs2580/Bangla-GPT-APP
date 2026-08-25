from typing import Protocol


class ProviderNotConfigured(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    async def generate(self, prompt: str, *, system: str | None = None) -> str: ...
