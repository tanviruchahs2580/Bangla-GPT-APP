"""shared JSON-object extraction and the bounded repair loop for the
generic generator contracts (A6-03)."""

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Protocol, TypeVar

from bangla_gpt_api.logging_config import json_log, trace_event
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.costs import estimate_tokens
from bangla_gpt_api.services.tutor import sanitize_evidence

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$")

T = TypeVar("T")

#: One repair attempt, not a retry loop: a model that cannot produce the
#: contract twice will not produce it a third time, and every attempt is a
#: paid call. The instruction is TRUSTED APP TEXT and is prepended (ahead of
#: the untrusted evidence blocks) so it sits where the system prompt says
#: app instructions live; the validation error it quotes is app-generated and
#: never carries student content.
_REPAIR_PREFIX = (
    "যাচাই ব্যর্থ হয়েছে: {error}। "
    "আবার উত্তর দাও: শুধুমাত্র একটি বৈধ JSON অবজেক্ট, ঠিক আগের নির্দেশনা ও "
    "নির্ধারিত কাঠামো অনুযায়ী। কোনো অতিরিক্ত লেখা যোগ করো না।"
)
_MAX_ERROR_CHARS = 200


class SupportsGenerate(Protocol):
    """The slice of LLMProvider the repair loop needs."""

    async def generate(self, prompt: str, *, system: str | None = None) -> str: ...


def repair_prompt(prompt: str, error: str) -> str:
    """The second-attempt prompt: validation feedback ahead of the evidence."""
    detail = " ".join(str(error).split())[:_MAX_ERROR_CHARS]
    return f"{_REPAIR_PREFIX.format(error=detail)}\n\n{prompt}"


def extract_json_object(text: str) -> dict:
    """Pull the first JSON object out of a raw completion (fences tolerated)."""
    cleaned = _FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("provider returned no JSON object")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"invalid JSON from provider: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("generator payload is not an object")
    return data


def require_str(data: dict, key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProviderError(f"{label} key '{key}' must be a non-empty string")
    return value.strip()


def require_echo(data: dict, *, class_level: int, subject: str, label: str) -> None:
    """Validation gate: the payload must echo the requested subject/class."""
    if data.get("subject") != subject:
        raise ProviderError(f"{label} payload must echo subject {subject!r}")
    if data.get("class_level") != class_level:
        raise ProviderError(f"{label} payload must echo class_level {class_level}")


async def _traced_generate(
    provider: SupportsGenerate,
    prompt: str,
    *,
    system: str | None,
    label: str,
    prompt_version: str | None,
    repair: bool,
) -> str:
    """One provider call + one generation trace (A1-04: no untraced call)."""
    started = time.perf_counter()
    raw = await provider.generate(prompt, system=system)
    trace_event(
        "generation",
        route=f"generator:{label}",
        model=getattr(provider, "model", None) or getattr(provider, "name", "unknown"),
        prompt_version=prompt_version or "unregistered",
        prompt_tokens=estimate_tokens(prompt),
        completion_tokens=estimate_tokens(raw),
        answer_chars=len(raw),
        latency_ms=int((time.perf_counter() - started) * 1000),
        repair=repair,
    )
    return raw


async def generate_validated(
    provider: SupportsGenerate,
    prompt: str,
    *,
    system: str | None,
    parse: Callable[[str], T],
    label: str,
    prompt_version: str | None = None,
) -> T:
    """One provider call, then ONE bounded repair call on validation failure.

    A6-03: structured generation retries at most once, carrying the validation
    error back to the model (bounded repair with error feedback). If the
    repaired reply is also invalid, ``ProviderError`` propagates -- the caller
    maps it to a 502 and nothing invalid reaches the DB or the UI (the
    per-route tests pin that half). Every repair attempt is logged with its
    reason so a rising repair rate is visible without reading payloads.
    """
    raw = await _traced_generate(
        provider, prompt, system=system, label=label, prompt_version=prompt_version, repair=False
    )
    try:
        return parse(raw)
    except ProviderError as error:
        # `as error` is unbound after the except block; capture the message.
        first_error = str(error)
        json_log(
            logger,
            logging.WARNING,
            "generator_repair",
            payload=label,
            reason=first_error[:200],
        )
    repaired = await _traced_generate(
        provider,
        repair_prompt(prompt, first_error),
        system=system,
        label=label,
        prompt_version=prompt_version,
        repair=True,
    )
    try:
        return parse(repaired)
    except ProviderError as second_error:
        raise ProviderError(
            f"{label}: invalid payload persisted after one repair "
            f"(first: {first_error}; repair: {second_error})"
        ) from second_error


__all__ = [
    "extract_json_object",
    "generate_validated",
    "repair_prompt",
    "require_echo",
    "require_str",
    "sources_from_hits",
]


def sources_from_hits(hits: list) -> list[SourceRef]:
    """SourceRef list for retrieved hits (one implementation for every generator).

    Six generators carried the same comprehension with the same fields in the
    same order -- the duplication ratchet's block. The tutor's ``_sources``
    stays where it is (it is the request path's), this is the generator-side
    contract, and a future field addition lands here once.
    """
    return [
        SourceRef(
            book=hit.chunk.meta.book,
            chapter=hit.chunk.meta.chapter,
            section=hit.chunk.meta.section,
            page=hit.chunk.meta.page,
            score=hit.score,
            excerpt=sanitize_evidence(hit.chunk.text),
        )
        for hit in hits
    ]
