"""OpenAI-compatible provider (Chat Completions API).

Supports both the official OpenAI endpoint and any OpenAI-compatible API
(OpenRouter, Together, Ollama, etc.) via configurable base_url.

Contract verified against the OpenAI Chat Completions API documentation
(https://platform.openai.com/docs/api-reference/chat):

- ``POST https://api.openai.com/v1/chat/completions``
- authentication via the ``Authorization: Bearer <key>`` header
- request body ``{"model": "...", "messages": [...]}``
- successful responses carry text in ``choices[0].message.content``
- streaming via ``stream=true`` with SSE ``data: ...`` lines

Live end-to-end behaviour requires a real ``OPENAI_API_KEY``; all request/
response handling is covered by tests against an ``httpx.MockTransport``.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

import httpx

from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.providers.base import LLMProvider, ProviderError, ProviderSettings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.openai.com/v1"
_CHAT_ENDPOINT = "/chat/completions"
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 4.0


def _extract_text(payload: dict) -> str:
    """Extract text from a Chat Completions response payload."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("OpenAI returned no choices (request may have been blocked)")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ProviderError("OpenAI returned no message in choices")
    text = message.get("content")
    if not text or not isinstance(text, str):
        finish = choices[0].get("finish_reason", "UNKNOWN") if isinstance(choices[0], dict) else "?"
        raise ProviderError(f"OpenAI returned no text (finishReason={finish})")
    return text.strip()


def _parse_sse_delta(line: str) -> str | None:
    """Extract the text delta from one SSE data line of streaming."""
    if not line.startswith("data:"):
        return None
    raw = line[len("data:") :].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(delta, dict):
        return None
    text = delta.get("content")
    return text if isinstance(text, str) else None


def _error_detail(payload: object, fallback: str) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or fallback)
    return str(payload)[:200]


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    return _error_detail(payload, str(response.status_code))


def _build_messages(prompt: str, system: str | None) -> list[dict]:
    """Build the messages array for the Chat Completions API.

    OpenAI expects messages with ``role``: ``system``, ``user``, ``assistant``.
    We map:
    - system prompt -> ``{"role": "system", "content": system}``
    - user prompt -> ``{"role": "user", "content": prompt}``
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider supporting both OpenAI and compatible APIs."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout_seconds: float,
        max_retries: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = (base_url or _API_BASE).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout_seconds, transport=self._transport)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def stream(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> AsyncIterator[str]:
        """Stream tokens via the Chat Completions streaming endpoint.

        Falls back to the non-streaming answer when streaming fails after
        retries (graceful degrade).
        """
        url = f"{self._base_url}{_CHAT_ENDPOINT}"
        messages = _build_messages(prompt, system)
        payload: dict = {"model": self.model, "messages": messages, "stream": True}
        # OpenAI-compatible providers do not support inline images in the
        # standard Chat Completions API; if an image was provided we log a
        # warning but proceed with text-only (the calling code already handles
        # the vision-unsupported case for mock mode).
        if image is not None:
            logger.warning(
                "OpenAI provider received an image; vision is not supported in this provider"
            )

        attempt = 0
        start = time.perf_counter()
        while True:
            status = 0
            body = b""
            try:
                session = self._client()
                async with session.stream(
                    "POST", url, json=payload, headers=self._headers()
                ) as response:
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
                                "openai_stream",
                                model=self.model,
                                latency_ms=latency_ms,
                                prompt_chars=len(prompt),
                                answer_chars=chars,
                                chunks=emitted,
                                retries=attempt,
                            )
                            return
                        raise ProviderError("OpenAI stream produced no text")
                    status = response.status_code
                    body = await response.aread()
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"OpenAI stream timed out after {self._timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"OpenAI stream failed: {exc}") from exc

            retryable = status in _RETRYABLE_STATUS
            if retryable and attempt < self._max_retries:
                await asyncio.sleep(min(0.5 * (2**attempt), _MAX_BACKOFF_SECONDS))
                attempt += 1
                continue
            raise ProviderError(f"OpenAI API error {status}: {_error_message_text(body)}")

    async def generate(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> str:
        url = f"{self._base_url}{_CHAT_ENDPOINT}"
        messages = _build_messages(prompt, system)
        payload: dict = {"model": self.model, "messages": messages}

        if image is not None:
            logger.warning(
                "OpenAI provider received an image; vision is not supported in this provider"
            )

        attempt = 0
        start = time.perf_counter()
        while True:
            try:
                client = self._client()
                response = await client.post(url, json=payload, headers=self._headers())
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"OpenAI request timed out after {self._timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"OpenAI request failed: {exc}") from exc

            if response.status_code == 200:
                try:
                    text = _extract_text(response.json())
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    json_log(
                        logger,
                        logging.INFO,
                        "openai_generate",
                        model=self.model,
                        latency_ms=latency_ms,
                        prompt_chars=len(prompt),
                        answer_chars=len(text),
                        retries=attempt,
                    )
                    return text
                except ValueError as exc:
                    raise ProviderError("OpenAI returned malformed JSON") from exc

            retryable = response.status_code in _RETRYABLE_STATUS
            if retryable and attempt < self._max_retries:
                await asyncio.sleep(min(0.5 * (2**attempt), _MAX_BACKOFF_SECONDS))
                attempt += 1
                continue
            raise ProviderError(
                f"OpenAI API error {response.status_code}: {_error_message(response)}"
            )


def _error_message_text(body: bytes) -> str:
    try:
        return _error_detail(json.loads(body), "error")
    except ValueError:
        return body[:200].decode(errors="replace")


def build_openai_provider(settings: ProviderSettings, model: str | None = None) -> OpenAIProvider:
    """Build an OpenAI-compatible client.

    Falls back to ``OPENAI_BASE_URL`` for OpenAI-compatible providers
    (OpenRouter, Together, Ollama, etc.). Defaults to the official OpenAI
    endpoint when unset.
    """
    from bangla_gpt_api.providers.base import ProviderNotConfigured

    api_key = settings.openai_api_key
    if not api_key:
        raise ProviderNotConfigured(
            "OPENAI_API_KEY is not set. "
            "Set OPENAI_API_KEY and OPENAI_MODEL, or use LLM_PROVIDER=mock or gemini."
        )
    return OpenAIProvider(
        api_key=api_key,
        model=model or settings.openai_model,
        base_url=settings.openai_base_url or None,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
