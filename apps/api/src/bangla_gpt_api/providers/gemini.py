"""Google Gemini provider over the REST ``generateContent`` endpoint.

Contract verified against the official Gemini API documentation
(ai.google.dev, retrieved 2026-08):

- ``POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent``
- authentication via the ``x-goog-api-key`` request header
- request body ``{"contents": [{"parts": [{"text": ...}]}]}`` with the
  optional ``"systemInstruction": {"parts": [{"text": ...}]}`` field
- successful responses carry text in ``candidates[0].content.parts[*].text``
- failures return ``{"error": {"code", "message", "status"}}``

Live end-to-end behaviour requires a real ``GEMINI_API_KEY``; all request/
response handling is covered by tests against an ``httpx.MockTransport``.
"""

import asyncio

import httpx

from bangla_gpt_api.config import Settings
from bangla_gpt_api.providers.base import ProviderError

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 4.0


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or response.status_code)
    return str(payload)[:200]


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProviderError("Gemini returned no candidates (request may have been blocked)")
    candidate = candidates[0]
    content = candidate.get("content") if isinstance(candidate, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [
        part["text"]
        for part in (parts or [])
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    answer = "".join(texts).strip()
    if not answer:
        reason = candidate.get("finishReason", "UNKNOWN") if isinstance(candidate, dict) else "?"
        raise ProviderError(f"Gemini returned no text (finishReason={reason})")
    return answer


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._transport = transport

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        url = f"{_API_BASE}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}
        payload: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds, transport=self._transport
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"Gemini request timed out after {self._timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"Gemini request failed: {exc}") from exc

            if response.status_code == 200:
                try:
                    return _extract_text(response.json())
                except ValueError as exc:
                    raise ProviderError("Gemini returned malformed JSON") from exc

            retryable = response.status_code in _RETRYABLE_STATUS
            if retryable and attempt < self._max_retries:
                await asyncio.sleep(min(0.5 * (2**attempt), _MAX_BACKOFF_SECONDS))
                attempt += 1
                continue
            raise ProviderError(
                f"Gemini API error {response.status_code}: {_error_message(response)}"
            )


def build_gemini_provider(settings: Settings) -> GeminiProvider:
    from bangla_gpt_api.providers.base import ProviderNotConfigured

    if not settings.gemini_api_key:
        raise ProviderNotConfigured("LLM_PROVIDER=gemini requires GEMINI_API_KEY to be set")
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
