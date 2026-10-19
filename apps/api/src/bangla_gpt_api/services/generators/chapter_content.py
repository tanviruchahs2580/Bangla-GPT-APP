"""content engine: one grounded RAG call produces all chapter sections."""

import json
import re

from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.context import RequestContext, set_current_context
from bangla_gpt_api.services.generators._json import generate_validated, sources_from_hits
from bangla_gpt_api.services.prompt_registry import load_prompt
from bangla_gpt_api.services.router import Route, set_current_route
from bangla_gpt_api.services.tutor import EVIDENCE_CLOSE, EVIDENCE_OPEN, sanitize_evidence

# Marker embedded in the prompt so deterministic/mock providers can recognize
# the content-generation contract and reply with the JSON payload.
CONTENT_JSON_MARKER = "CONTENT_JSON_V1"

CONTENT_KEYS = (
    "summary",
    "notes",
    "key_points",
    "examples",
    "practice_qs",
    "homework",
    "exam_tips",
)
_STRING_KEYS = ("summary", "notes")
_LIST_KEYS = ("key_points", "examples", "practice_qs", "homework", "exam_tips")

CONTENT_SYSTEM_PROMPT_SPEC = load_prompt("content_system")
CONTENT_SYSTEM_PROMPT = CONTENT_SYSTEM_PROMPT_SPEC.text

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$")


def build_content_prompt(class_level: int, subject: str, chapter: str, hits: list) -> str:
    """Single RAG context shared by every output section (spec 2.3)."""
    blocks = "\n".join(
        f"{EVIDENCE_OPEN}\n{sanitize_evidence(hit.chunk.text)}\n{EVIDENCE_CLOSE}" for hit in hits
    )
    return (
        f"{CONTENT_JSON_MARKER}\n"
        f"Target: class_level={class_level}, subject={subject}, chapter={chapter}.\n"
        "Generate complete chapter study material as one JSON object with the "
        "seven required keys.\n\n"
        f"Textbook passages:\n{blocks}"
    )


def parse_content_payload(text: str) -> dict[str, object]:
    """Extract and validate the seven-section JSON from a raw completion."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("provider returned no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"invalid JSON from provider: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("content payload is not an object")
    for key in _STRING_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProviderError(f"content payload key '{key}' must be a non-empty string")
    for key in _LIST_KEYS:
        value = data.get(key)
        if not isinstance(value, list) or not value:
            raise ProviderError(f"content payload key '{key}' must be a non-empty list")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ProviderError(f"content payload key '{key}' must contain strings")
    return {key: data[key] for key in CONTENT_KEYS}


def _content_sources(hits: list) -> list[SourceRef]:
    """Shared with every other generator (see _json.sources_from_hits)."""
    return sources_from_hits(hits)


async def generate_chapter_content(
    index: RankingIndex,
    provider: LLMProvider,
    *,
    class_level: int,
    subject: str,
    chapter: str,
    top_k: int = 6,
    context: RequestContext | None = None,
) -> tuple[dict[str, object], list[SourceRef]]:
    """One retrieval + one provider call (one bounded repair, A6-03)."""
    hits = index.search(chapter, class_level=class_level, subject=subject, top_k=top_k)
    if not hits:
        raise ProviderError("no textbook evidence found for this chapter")
    prompt = build_content_prompt(class_level, subject, chapter, hits)
    if context is not None:
        # trusted education-context block, ahead of the evidence.
        prompt = f"{context.render_block()}\n\n{prompt}"
        set_current_context(context)
    # teacher generation is always a TOOL route (main model + RAG).
    set_current_route(Route.TOOL)
    payload = await generate_validated(
        provider,
        prompt,
        system=CONTENT_SYSTEM_PROMPT,
        parse=parse_content_payload,
        label="chapter_content",
        prompt_version=CONTENT_SYSTEM_PROMPT_SPEC.trace_version,
    )
    return payload, _content_sources(hits)
