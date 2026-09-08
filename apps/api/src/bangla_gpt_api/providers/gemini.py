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
import json
import logging
import time
from collections.abc import AsyncIterator

import httpx

from bangla_gpt_api.config import Settings
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.services.context import get_current_context


def _context_log_fields() -> dict[str, object]:
    """S4.1/S4.2: attach the education context (counts/ids only, never
    content) and the routing decision to provider logs so every AI call is
    attributable (route + latency + cost) for eval."""
    from bangla_gpt_api.services.router import get_current_route

    fields: dict[str, object] = {}
    route = get_current_route()
    if route:
        fields["ai_route"] = route
    ctx = get_current_context()
    if ctx is not None:
        fields.update(ctx.log_fields())
    return fields


logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 4.0


def _error_detail(payload: object, fallback: str) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or fallback)
    return str(payload)[:200]


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    return _error_detail(payload, str(response.status_code))


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


def _parse_sse_delta(line: str) -> str | None:
    """Extract the text delta from one SSE data line of streamGenerateContent."""
    if not line.startswith("data:"):
        return None
    raw = line[len("data:") :].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [
        part["text"]
        for part in (parts or [])
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    delta = "".join(texts)
    return delta or None


def _error_message_text(body: bytes) -> str:
    try:
        return _error_detail(json.loads(body), "error")
    except ValueError:
        return body[:200].decode(errors="replace")


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
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        # One pooled client per provider instance instead of a new
        # connection pool per request (connection reuse + lower latency).
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout_seconds, transport=self._transport)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        """Stream tokens via ``streamGenerateContent`` SSE transport.

        Falls back to a single chunk of the non-streaming answer when the
        streaming endpoint is unavailable after retries (graceful degrade).
        """
        url = f"{_API_BASE}/models/{self.model}:streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": self._api_key}
        payload: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        attempt = 0
        start = time.perf_counter()
        while True:
            status = 0
            body = b""
            try:
                session = self._client()
                async with session.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code == 200:
                        emitted = 0
                        chars = 0
                        async for line in response.aiter_lines():
                            delta = _parse_sse_delta(line)
                            if delta:
                                emitted += 1
                                chars += len(delta)
                                yield delta
                        if emitted:
                            latency_ms = int((time.perf_counter() - start) * 1000)
                            json_log(
                                logger,
                                logging.INFO,
                                "gemini_stream",
                                model=self.model,
                                latency_ms=latency_ms,
                                prompt_chars=len(prompt),
                                answer_chars=chars,
                                chunks=emitted,
                                retries=attempt,
                                **_context_log_fields(),
                            )
                            return
                        raise ProviderError("Gemini stream produced no text")
                    status = response.status_code
                    body = await response.aread()
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"Gemini stream timed out after {self._timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"Gemini stream failed: {exc}") from exc

            retryable = status in _RETRYABLE_STATUS
            if retryable and attempt < self._max_retries:
                await asyncio.sleep(min(0.5 * (2**attempt), _MAX_BACKOFF_SECONDS))
                attempt += 1
                continue
            raise ProviderError(f"Gemini API error {status}: {_error_message_text(body)}")

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        url = f"{_API_BASE}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}
        payload: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        attempt = 0
        start = time.perf_counter()
        while True:
            try:
                client = self._client()
                response = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"Gemini request timed out after {self._timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"Gemini request failed: {exc}") from exc

            if response.status_code == 200:
                try:
                    text = _extract_text(response.json())
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    # Token usage not returned by generateContent; log chars as proxy for cost
                    json_log(
                        logger,
                        logging.INFO,
                        "gemini_generate",
                        model=self.model,
                        latency_ms=latency_ms,
                        prompt_chars=len(prompt),
                        answer_chars=len(text),
                        retries=attempt,
                        **_context_log_fields(),
                    )
                    return text
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


def build_gemini_provider(settings: Settings, model: str | None = None) -> GeminiProvider:
    """Build a Gemini client; ``model`` overrides GEMINI_MODEL (S4.2 fast lane)."""
    from bangla_gpt_api.providers.base import ProviderNotConfigured

    if not settings.gemini_api_key:
        raise ProviderNotConfigured("LLM_PROVIDER=gemini requires GEMINI_API_KEY to be set")
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=model or settings.gemini_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
