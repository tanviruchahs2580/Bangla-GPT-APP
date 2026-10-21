"""lesson plan copilot: one grounded RAG call -> eight printable sections.

The eight-section contract follows the master spec order exactly:
Objective -> Previous Knowledge -> Introduction -> Main Explanation ->
Activity -> Questions -> Assessment -> Homework. Every value stays a plain
multi-line string so the teacher can edit each block in a textarea before
printing.
"""

import json
import re

from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.context import RequestContext, set_current_context
from bangla_gpt_api.services.generators._json import (
    generate_validated,
    require_echo,
    sources_from_hits,
)
from bangla_gpt_api.services.prompt_registry import load_prompt
from bangla_gpt_api.services.router import Route, set_current_route
from bangla_gpt_api.services.tutor import EVIDENCE_CLOSE, EVIDENCE_OPEN, sanitize_evidence

# Prompt marker so deterministic/mock providers recognize the lesson contract.
LESSON_JSON_MARKER = "LESSON_JSON_V1"

LESSON_KEYS: tuple[str, ...] = (
    "objective",
    "previous_knowledge",
    "introduction",
    "main_explanation",
    "activity",
    "questions",
    "assessment",
    "homework",
)

LESSON_SYSTEM_PROMPT_SPEC = load_prompt("lesson_system")
LESSON_SYSTEM_PROMPT = LESSON_SYSTEM_PROMPT_SPEC.text

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$")


def build_lesson_prompt(
    class_level: int,
    subject: str,
    chapter: str,
    minutes: int,
    level: str,
    hits: list,
) -> str:
    """Single RAG context shared by all eight lesson sections."""
    blocks = "\n".join(
        f"{EVIDENCE_OPEN}\n{sanitize_evidence(hit.chunk.text)}\n{EVIDENCE_CLOSE}" for hit in hits
    )
    return (
        f"{LESSON_JSON_MARKER}\n"
        f"Target: class_level={class_level}, subject={subject}, chapter={chapter}, "
        f"minutes={minutes}, level={level}.\n"
        "Draft one classroom lesson plan as a single JSON object with the "
        "eight required keys, timed to fit the given minutes.\n\n"
        f"Textbook passages:\n{blocks}"
    )


def parse_lesson_payload(text: str, *, class_level: int, subject: str) -> dict[str, str]:
    """Extract and validate the eight-section JSON from a raw completion.

    A21: the payload must ALSO echo the requested subject/class_level — the
    same grounding gate every other generator applies — so a provider that
    ignored the prompt cannot silently serve a plan for the wrong class.
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("provider returned no JSON object")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"invalid JSON from provider: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("lesson payload is not an object")
    require_echo(data, class_level=class_level, subject=subject, label="lesson_plan")
    plan: dict[str, str] = {}
    for key in LESSON_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProviderError(f"lesson payload key '{key}' must be a non-empty string")
        plan[key] = value.strip()
    return plan


async def generate_lesson_plan(
    index: RankingIndex,
    provider: LLMProvider,
    *,
    class_level: int,
    subject: str,
    chapter: str,
    minutes: int,
    level: str,
    top_k: int = 6,
    context: RequestContext | None = None,
) -> tuple[dict[str, str], list[SourceRef]]:
    """One retrieval + one provider call (one bounded repair, A6-03)."""
    hits = index.search(chapter, class_level=class_level, subject=subject, top_k=top_k)
    if not hits:
        raise ProviderError("no textbook evidence found for this chapter")
    prompt = build_lesson_prompt(class_level, subject, chapter, minutes, level, hits)
    if context is not None:
        # trusted education-context block, ahead of the evidence.
        prompt = f"{context.render_block()}\n\n{prompt}"
        set_current_context(context)
    # teacher generation is always a TOOL route (main model + RAG).
    set_current_route(Route.TOOL)
    plan = await generate_validated(
        provider,
        prompt,
        system=LESSON_SYSTEM_PROMPT,
        parse=lambda text: parse_lesson_payload(text, class_level=class_level, subject=subject),
        label="lesson_plan",
        prompt_version=LESSON_SYSTEM_PROMPT_SPEC.trace_version,
    )
    sources = sources_from_hits(hits)
    return plan, sources
