"""worksheet generator: one grounded RAG call (plus one bounded repair on
validation failure, A6-03) -> three-tier practice sheet.

Contract: tiers basic -> intermediate -> advanced, each a non-empty list of
MCQ items, plus a printable answer sheet. The validation gate rejects any
payload whose tiers/answer sheet are empty or whose subject/class_level do
not echo the request (mirrors the S2.x generator discipline).
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

WORKSHEET_JSON_MARKER = "WORKSHEET_JSON_V1"

WORKSHEET_TIERS: tuple[str, ...] = ("basic", "intermediate", "advanced")

WORKSHEET_SYSTEM_PROMPT_SPEC = load_prompt("worksheet_system")
WORKSHEET_SYSTEM_PROMPT = WORKSHEET_SYSTEM_PROMPT_SPEC.text


def build_worksheet_prompt(class_level: int, subject: str, chapter: str, hits: list) -> str:
    blocks = "\n".join(
        f"{EVIDENCE_OPEN}\n{sanitize_evidence(hit.chunk.text)}\n{EVIDENCE_CLOSE}" for hit in hits
    )
    return (
        f"{WORKSHEET_JSON_MARKER}\n"
        f"Target: class_level={class_level}, subject={subject}, chapter={chapter}.\n"
        "Create one practice worksheet as a single JSON object: a basic, an "
        "intermediate and an advanced tier of MCQ questions plus an answer "
        "sheet, difficulty rising across tiers.\n\n"
        f"Textbook passages:\n{blocks}"
    )


def _validate_mcq(item: object, label: str) -> dict:
    if not isinstance(item, dict):
        raise ProviderError(f"{label} item must be an object")
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError(f"{label} item needs a non-empty 'text'")
    options = item.get("options")
    if not isinstance(options, list) or len(options) != 4:
        raise ProviderError(f"{label} item needs exactly four options")
    if not all(isinstance(o, str) and o.strip() for o in options):
        raise ProviderError(f"{label} options must be non-empty strings")
    answer_index = item.get("answer_index")
    # bool is an int subclass: `True` must never pass as answer option b.
    if (
        not isinstance(answer_index, int)
        or isinstance(answer_index, bool)
        or not 0 <= answer_index <= 3
    ):
        raise ProviderError(f"{label} answer_index must be 0-3")
    marks = item.get("marks")
    if not isinstance(marks, int) or isinstance(marks, bool) or marks < 1:
        raise ProviderError(f"{label} marks must be a positive integer")
    return {
        "text": text.strip(),
        "options": [str(o).strip() for o in options],
        "answer_index": answer_index,
        "marks": marks,
    }


def parse_worksheet_payload(text: str, *, class_level: int, subject: str) -> dict:
    """Extract and validate the three-tier worksheet from a raw completion."""
    data = extract_json_object(text)
    require_echo(data, class_level=class_level, subject=subject, label="worksheet")
    tiers_raw = data.get("tiers")
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise ProviderError("worksheet payload must carry a non-empty 'tiers' list")
    tiers: list[dict] = []
    seen: set[str] = set()
    for entry in tiers_raw:
        if not isinstance(entry, dict):
            raise ProviderError("worksheet tier must be an object")
        name = entry.get("tier")
        if name not in WORKSHEET_TIERS:
            raise ProviderError(f"worksheet tier must be one of {WORKSHEET_TIERS}")
        questions_raw = entry.get("questions")
        if not isinstance(questions_raw, list) or not questions_raw:
            raise ProviderError(f"worksheet tier '{name}' must be non-empty")
        tiers.append(
            {
                "tier": str(name),
                "questions": [_validate_mcq(q, f"worksheet tier '{name}'") for q in questions_raw],
            }
        )
        seen.add(str(name))
    missing = [t for t in WORKSHEET_TIERS if t not in seen]
    if missing:
        raise ProviderError(f"worksheet payload is missing tiers: {', '.join(missing)}")
    sheet = data.get("answer_sheet")
    if not isinstance(sheet, list) or not sheet:
        raise ProviderError("worksheet payload must carry a non-empty 'answer_sheet'")
    if not all(isinstance(row, dict) and str(row.get("answer", "")).strip() for row in sheet):
        raise ProviderError("worksheet answer sheet rows need a non-empty 'answer'")
    chapter = data.get("chapter")
    return {
        "subject": subject,
        "class_level": class_level,
        "chapter": chapter.strip() if isinstance(chapter, str) else None,
        "tiers": tiers,
        "answer_sheet": [dict(row) for row in sheet],
    }


async def generate_worksheet(
    index: RankingIndex,
    provider: LLMProvider,
    *,
    class_level: int,
    subject: str,
    chapter: str,
    top_k: int = 6,
    context: RequestContext | None = None,
) -> tuple[dict, list[SourceRef]]:
    """One retrieval + one provider call (one bounded repair on invalid JSON).

    A6-03: a reply that fails validation triggers exactly ONE repair call
    carrying the validation error; a second failure raises ProviderError and
    nothing invalid is returned to the caller."""
    hits = index.search(chapter, class_level=class_level, subject=subject, top_k=top_k)
    if not hits:
        raise ProviderError("no textbook evidence found for this chapter")
    prompt = build_worksheet_prompt(class_level, subject, chapter, hits)
    if context is not None:
        prompt = f"{context.render_block()}\n\n{prompt}"
        set_current_context(context)
    set_current_route(Route.TOOL)
    payload = await generate_validated(
        provider,
        prompt,
        system=WORKSHEET_SYSTEM_PROMPT,
        parse=lambda text: parse_worksheet_payload(text, class_level=class_level, subject=subject),
        label="worksheet",
        prompt_version=WORKSHEET_SYSTEM_PROMPT_SPEC.trace_version,
    )
    sources = sources_from_hits(hits)
    return payload, sources
