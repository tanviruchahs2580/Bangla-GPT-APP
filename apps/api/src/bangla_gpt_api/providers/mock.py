import re
from collections.abc import AsyncIterator

_CHUNK_SIZE = 48

_EVIDENCE_RE = re.compile(r"<evidence>(.*?)</evidence>", re.DOTALL)


class MockLLMProvider:
    name = "mock"

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        # AUD-01: never echo `system` (internal prompt) or raw markup back to users.
        # For grounded prompts, quote the retrieved textbook evidence cleanly.
        evidences = _EVIDENCE_RE.findall(prompt)
        if evidences:
            quoted = " ".join(e.strip() for e in evidences[:2])
            return f"[mock] পাঠ্যবই অনুযায়ী: {quoted}"
        return f"[mock] {prompt}"

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        """Yield the mock answer in small chunks to exercise SSE consumers."""
        answer = await self.generate(prompt, system=system)
        for i in range(0, len(answer), _CHUNK_SIZE):
            yield answer[i : i + _CHUNK_SIZE]
