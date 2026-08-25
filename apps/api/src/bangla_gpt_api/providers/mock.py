class MockLLMProvider:
    name = "mock"

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        prefix = f"[{system}] " if system else ""
        return f"{prefix}[mock] {prompt}"
