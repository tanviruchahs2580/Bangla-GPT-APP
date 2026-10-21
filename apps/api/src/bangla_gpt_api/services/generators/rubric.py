"""rubric generator: criteria rows with three level descriptors.

Contract: one row per assessment criterion; every row names the criterion,
carries positive max_marks and gives non-empty descriptors for excellent /
good / needs_improvement; total_marks equals the sum of the row marks.
"""

from bangla_gpt_api.providers.base import LLMProvider, ProviderError
from bangla_gpt_api.retrieval.base import RankingIndex
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.context import RequestContext, set_current_context
from bangla_gpt_api.services.generators._json import (
    extract_json_object,
    generate_validated,
    require_echo,
    sources_from_hits,
)
from bangla_gpt_api.services.prompt_registry import load_prompt
from bangla_gpt_api.services.router import Route, set_current_route
from bangla_gpt_api.services.tutor import EVIDENCE_CLOSE, EVIDENCE_OPEN, sanitize_evidence

RUBRIC_JSON_MARKER = "RUBRIC_JSON_V1"

RUBRIC_LEVELS: tuple[str, ...] = ("excellent", "good", "needs_improvement")

RUBRIC_SYSTEM_PROMPT_SPEC = load_prompt("rubric_system")
RUBRIC_SYSTEM_PROMPT = RUBRIC_SYSTEM_PROMPT_SPEC.text


def build_rubric_prompt(class_level: int, subject: str, chapter: str, hits: list) -> str:
    blocks = "\n".join(
        f"{EVIDENCE_OPEN}\n{sanitize_evidence(hit.chunk.text)}\n{EVIDENCE_CLOSE}" for hit in hits
    )
    return (
        f"{RUBRIC_JSON_MARKER}\n"
        f"Target: class_level={class_level}, subject={subject}, chapter={chapter}.\n"
        "Create one marking rubric for this chapter/topic as a single JSON "
        "object with criteria rows and three achievement levels each.\n\n"
        f"Textbook passages:\n{blocks}"
    )


def parse_rubric_payload(text: str, *, class_level: int, subject: str) -> dict:
    """Extract and validate the rubric rows from a raw completion."""
    data = extract_json_object(text)
    require_echo(data, class_level=class_level, subject=subject, label="rubric")
    criteria_raw = data.get("criteria")
    if not isinstance(criteria_raw, list) or not criteria_raw:
        raise ProviderError("rubric payload must carry a non-empty 'criteria' list")
    criteria: list[dict] = []
    total = 0
    for i, row in enumerate(criteria_raw, start=1):
        if not isinstance(row, dict):
            raise ProviderError("rubric criterion must be an object")
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProviderError(f"rubric criterion {i} needs a non-empty 'name'")
        max_marks = row.get("max_marks")
        if not isinstance(max_marks, int) or max_marks < 1:
            raise ProviderError(f"rubric criterion '{name}' max_marks must be positive")
        levels = row.get("levels")
        if not isinstance(levels, dict):
            raise ProviderError(f"rubric criterion '{name}' needs a 'levels' object")
        clean_levels: dict[str, str] = {}
        for level in RUBRIC_LEVELS:
            desc = levels.get(level)
            if not isinstance(desc, str) or not desc.strip():
                raise ProviderError(f"rubric criterion '{name}' lacks '{level}' descriptor")
            clean_levels[level] = desc.strip()
        total += max_marks
        criteria.append({"name": name.strip(), "max_marks": max_marks, "levels": clean_levels})
    total_marks = data.get("total_marks")
    if not isinstance(total_marks, int) or total_marks != total:
        raise ProviderError("rubric total_marks must equal the sum of criteria marks")
    chapter = data.get("chapter")
    return {
        "subject": subject,
        "class_level": class_level,
        "chapter": chapter.strip() if isinstance(chapter, str) else None,
        "criteria": criteria,
        "total_marks": total,
    }


async def generate_rubric(
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
    prompt = build_rubric_prompt(class_level, subject, chapter, hits)
    if context is not None:
        prompt = f"{context.render_block()}\n\n{prompt}"
        set_current_context(context)
    set_current_route(Route.TOOL)
    payload = await generate_validated(
        provider,
        prompt,
        system=RUBRIC_SYSTEM_PROMPT,
        parse=lambda text: parse_rubric_payload(text, class_level=class_level, subject=subject),
        label="rubric",
        prompt_version=RUBRIC_SYSTEM_PROMPT_SPEC.trace_version,
    )
    sources = sources_from_hits(hits)
    return payload, sources
