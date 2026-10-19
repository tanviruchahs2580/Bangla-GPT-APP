"""homework generator: assignment brief with a parent-facing note.

Contract: items (non-empty), instructions, due_suggestion, a parent_note
written in simple Bangla for guardians, and an estimated_minutes integer.
"""

from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.context import RequestContext, set_current_context
from bangla_gpt_api.services.generators._json import (
    extract_json_object,
    generate_validated,
    require_echo,
    require_str,
    sources_from_hits,
)
from bangla_gpt_api.services.prompt_registry import load_prompt
from bangla_gpt_api.services.router import Route, set_current_route
from bangla_gpt_api.services.tutor import EVIDENCE_CLOSE, EVIDENCE_OPEN, sanitize_evidence

HOMEWORK_JSON_MARKER = "HOMEWORK_JSON_V1"

HOMEWORK_SYSTEM_PROMPT_SPEC = load_prompt("homework_system")
HOMEWORK_SYSTEM_PROMPT = HOMEWORK_SYSTEM_PROMPT_SPEC.text


def build_homework_prompt(class_level: int, subject: str, chapter: str, hits: list) -> str:
    blocks = "\n".join(
        f"{EVIDENCE_OPEN}\n{sanitize_evidence(hit.chunk.text)}\n{EVIDENCE_CLOSE}" for hit in hits
    )
    return (
        f"{HOMEWORK_JSON_MARKER}\n"
        f"Target: class_level={class_level}, subject={subject}, chapter={chapter}.\n"
        "Draft one homework assignment brief as a single JSON object.\n\n"
        f"Textbook passages:\n{blocks}"
    )


def parse_homework_payload(text: str, *, class_level: int, subject: str) -> dict:
    """Extract and validate the assignment brief from a raw completion."""
    data = extract_json_object(text)
    require_echo(data, class_level=class_level, subject=subject, label="homework")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ProviderError("homework payload must carry a non-empty 'items' list")
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise ProviderError("homework items must be non-empty strings")
    minutes = data.get("estimated_minutes")
    if not isinstance(minutes, int) or not 1 <= minutes <= 600:
        raise ProviderError("homework estimated_minutes must be 1-600")
    instructions = require_str(data, "instructions", "homework")
    due = require_str(data, "due_suggestion", "homework")
    parent_note = require_str(data, "parent_note", "homework")
    chapter = data.get("chapter")
    return {
        "subject": subject,
        "class_level": class_level,
        "chapter": chapter.strip() if isinstance(chapter, str) else None,
        "items": [item.strip() for item in items],
        "instructions": instructions,
        "due_suggestion": due,
        "parent_note": parent_note,
        "estimated_minutes": minutes,
    }


async def generate_homework(
    index: RankingIndex,
    provider: LLMProvider,
    *,
    class_level: int,
    subject: str,
    chapter: str,
    top_k: int = 6,
    context: RequestContext | None = None,
) -> tuple[dict, list[SourceRef]]:
    """One retrieval + one provider call (one bounded repair, A6-03)."""
    hits = index.search(chapter, class_level=class_level, subject=subject, top_k=top_k)
    if not hits:
        raise ProviderError("no textbook evidence found for this chapter")
    prompt = build_homework_prompt(class_level, subject, chapter, hits)
    if context is not None:
        prompt = f"{context.render_block()}\n\n{prompt}"
        set_current_context(context)
    set_current_route(Route.TOOL)
    payload = await generate_validated(
        provider,
        prompt,
        system=HOMEWORK_SYSTEM_PROMPT,
        parse=lambda text: parse_homework_payload(text, class_level=class_level, subject=subject),
        label="homework",
        prompt_version=HOMEWORK_SYSTEM_PROMPT_SPEC.trace_version,
    )
    sources = sources_from_hits(hits)
    return payload, sources
