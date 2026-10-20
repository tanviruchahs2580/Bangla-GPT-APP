"""Knowledge Graph v1 -- concepts, prerequisite edges, per-concept mastery.

Three layers, kept deliberately boring and deterministic:

1. Concepts are chapter-derived roots (one per class/subject/chapter in the
   active curriculum index), optionally enriched by LLM extraction
   (:func:`extract_chapter_concepts`). Extraction output is only trusted when
   the name occurs VERBATIM in the chapter text -- a corpus-verification
   grounding guard so an LLM cannot invent graph nodes.
2. Prerequisite edges are curated pedagogy, shipped as data
   (data/kg/prerequisites.json, corpus-verified). Aliases map colloquial
   spellings (Bijgonit -> Bijgonitiyo Rashi) onto canonical concept names.
3. Mastery is per-student per-concept graded-answer counts, updated from
   quiz submissions. The graph gap rule (spec PASS): a weak concept surfaces
   any prerequisite with missing or below-threshold mastery -- weak algebra
   surfaces missing fractions.

Name note: concepts are addressed by NAME for edges/gaps (one name may have
roots in several class levels; counts aggregate across them), while DB rows
stay per class/subject/chapter.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.exc import IntegrityError

from bangla_gpt_api.db.models import Concept, ConceptMastery, ConceptPrerequisite
from bangla_gpt_api.services.prompt_registry import load_prompt

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable, Mapping, Sequence

    from sqlalchemy.orm import Session

    from bangla_gpt_api.curriculum.models import Chunk
    from bangla_gpt_api.providers.base import LLMProvider
    from bangla_gpt_api.schemas import ReviewItem

KG_DATA = Path(__file__).parent.parent / "data" / "kg" / "prerequisites.json"

#: mastery percent below which a practiced concept counts as weak
WEAK_THRESHOLD_PCT = 50.0
#: fewer graded answers than this = "not enough evidence", never a gap
MIN_ATTEMPTS = 3


def _load_kg_data() -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    raw = json.loads(KG_DATA.read_text(encoding="utf-8"))
    edges = {k: tuple(v) for k, v in raw["prerequisites"].items()}
    aliases = {k: tuple(v) for k, v in raw["aliases"].items()}
    return edges, aliases


PREREQUISITE_EDGES, CONCEPT_ALIASES = _load_kg_data()

#: reverse alias lookup: colloquial spelling -> canonical concept name
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical for canonical, aliases in CONCEPT_ALIASES.items() for alias in aliases
}


def canonical(name: str) -> str:
    """Map an alias onto its canonical concept name (idempotent)."""
    return _ALIAS_TO_CANONICAL.get(name.strip(), name.strip())


@dataclass(frozen=True)
class ConceptSeed:
    """A concept to insert: name, curriculum position, provenance."""

    name: str
    class_level: int
    subject: str
    chapter: str
    source: str = "chapter"
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Gap:
    """A learning gap: weak concept + prerequisite that is missing/weak."""

    concept: str
    prereq: str
    prereq_pct: float | None  # None = never practiced
    prereq_total: int
    depth: int  # 1 = direct prerequisite


# --- pure graph layer (unit-testable, no DB) --------------------------------


def build_concept_seeds(chunks: Iterable[Chunk]) -> list[ConceptSeed]:
    """Deterministic chapter-derived roots for an active curriculum index."""
    seen: set[tuple[str, int, str]] = set()
    seeds: list[ConceptSeed] = []
    for chunk in chunks:
        chapter = chunk.meta.chapter
        if not chapter:
            continue
        key = (chapter, chunk.meta.class_level, chunk.meta.subject)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(
            ConceptSeed(
                name=chapter,
                class_level=chunk.meta.class_level,
                subject=chunk.meta.subject,
                chapter=chapter,
                source="chapter",
                aliases=CONCEPT_ALIASES.get(chapter, ()),
            )
        )
    seeds.sort(key=lambda s: (s.class_level, s.subject, s.name))
    return seeds


def build_edge_pairs(seeds: Sequence[ConceptSeed]) -> list[tuple[int, int]]:
    """Curated edge names -> (child_idx, prereq_idx) seed-index pairs.

    A name used by several chapter roots (same chapter across classes) is
    pinned to the LOWEST class level -- prerequisites always point at the
    earliest occurrence. Unknown names are skipped silently (corpus-driven).
    """
    by_name: dict[str, list[int]] = {}
    for idx, seed in enumerate(seeds):
        by_name.setdefault(seed.name, []).append(idx)

    def resolve(name: str) -> int | None:
        idxs = by_name.get(canonical(name))
        if not idxs:
            return None
        return min(idxs, key=lambda i: (seeds[i].class_level, seeds[i].subject))

    pairs: set[tuple[int, int]] = set()
    for child, prereqs in PREREQUISITE_EDGES.items():
        child_idx = resolve(child)
        if child_idx is None:
            continue
        for prereq in prereqs:
            prereq_idx = resolve(prereq)
            if prereq_idx is None or prereq_idx == child_idx:
                continue
            pairs.add((child_idx, prereq_idx))
    return sorted(pairs)


def prereq_closure(name: str, edges: Mapping[str, tuple[str, ...]]) -> dict[str, int]:
    """Transitive prerequisite names reachable from `name` -> min depth."""
    found: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque([(canonical(name), 0)])
    while queue:
        current, depth = queue.popleft()
        for prereq in edges.get(current, ()):
            prereq = canonical(prereq)
            if prereq not in found:
                found[prereq] = depth + 1
                queue.append((prereq, depth + 1))
    return found


def resolve_gaps(
    mastery: Mapping[str, tuple[int, int]],
    edges: Mapping[str, tuple[str, ...]],
    *,
    weak_threshold_pct: float = WEAK_THRESHOLD_PCT,
    min_attempts: int = MIN_ATTEMPTS,
) -> list[Gap]:
    """Spec PASS rule: weak concepts surface missing/weak prerequisites.

    `mastery` maps concept name -> (correct, total) graded answers. Names are
    canonicalized first (counts merged), so a mastery keyed by a colloquial
    alias like "বীজগণিত" behaves exactly like the canonical chapter root.
    A concept is WEAK with >= min_attempts and pct < weak_threshold_pct. Each
    weak concept surfaces every transitive prerequisite that was never
    practiced or is itself weak, nearest first.
    """
    canon: dict[str, tuple[int, int]] = {}
    for raw_name, (correct, total) in mastery.items():
        name = canonical(raw_name)
        prev_c, prev_t = canon.get(name, (0, 0))
        canon[name] = (prev_c + correct, prev_t + total)

    def pct_of(name: str) -> tuple[float, int] | None:
        entry = canon.get(name)
        if entry is None or entry[1] == 0:
            return None
        return round(100.0 * entry[0] / entry[1], 1), entry[1]

    def is_weak(name: str) -> bool:
        entry = canon.get(name)
        return (
            entry is not None
            and entry[1] >= min_attempts
            and 100.0 * entry[0] / entry[1] < weak_threshold_pct
        )

    weak_names = sorted(name for name in canon if is_weak(name))
    gaps: dict[tuple[str, str], Gap] = {}
    for weak in weak_names:
        for prereq, depth in prereq_closure(weak, edges).items():
            entry = pct_of(prereq)
            missing = entry is None or entry[0] < weak_threshold_pct
            if not missing:
                continue
            key = (weak, prereq)
            if key not in gaps or depth < gaps[key].depth:
                gaps[key] = Gap(
                    concept=weak,
                    prereq=prereq,
                    prereq_pct=None if entry is None else entry[0],
                    prereq_total=0 if entry is None else entry[1],
                    depth=depth,
                )
    return sorted(gaps.values(), key=lambda g: (g.concept, g.depth, g.prereq))


# --- LLM extraction (corpus-verified) ----------------------------------------
#
# A1-04 finding fixed here: this call site used to send the raw corpus text
# with an INLINE instruction and no system prompt, no delimiter policy, no
# trace and no prompt-version record. It is admin-triggered
# (``POST /admin/kg/rebuild?llm=true``) but it is still an LLM call: the
# instruction now lives in the prompt registry, the corpus text is wrapped as
# delimited data (it is untrusted too -- a poisoned textbook must not steer
# the extractor), and every call emits a generation trace. Token accounting
# for this route stays with its owner (routers/learn.py) -- see the handoff.

_EXTRACTION_SPEC = load_prompt("knowledge_extract_system")
EXTRACTION_SYSTEM_PROMPT = _EXTRACTION_SPEC.text

EXTRACTION_PROMPT_TEMPLATE = "Chapter: {chapter}\nText:\n<evidence>\n{text}\n</evidence>"


def parse_concept_names(raw: str, *, chapter: str, text: str, limit: int = 6) -> list[str]:
    """Parse + validate an extractor response (pure, deterministic).

    A candidate survives only if it is a string of sane length, differs from
    the chapter title, and occurs VERBATIM in the chapter text (grounding
    guard: the model may select, never invent).
    """
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if 2 <= len(name) <= 40 and name != chapter and name in text and name not in out:
            out.append(name)
        if len(out) >= limit:
            break
    return out


async def extract_chapter_concepts(
    provider: LLMProvider,
    *,
    chapter: str,
    text: str,
    limit: int = 6,
    usage: tuple[Session, int] | None = None,
) -> list[str]:
    """LLM chapter extraction, corpus-verified. Any failure -> [] (never raise
    into a rebuild: the deterministic chapter roots always exist).

    A1-04: registry system prompt + delimited untrusted corpus text + one
    generation trace per call, exactly like every other provider call site.

    ``usage=(db, user_id)`` (A1-04) funnels the call into the same ai_usage
    ledger every AI-bearing route writes via ``record_ai_usage`` -- spend is
    spend even when the parsed result is empty (the admin kg/rebuild?llm=true
    route was the one un-accounted call site). The row is added to the
    caller's session; the rebuild's own commit persists it.
    """
    # trace_event lives in logging_config (the wave-1 helper every other
    # stage uses); tracing.py imports logging_config lazily, so importing
    # it back from there would close a cycle (c2 handoff).
    from bangla_gpt_api.logging_config import trace_event
    from bangla_gpt_api.services.costs import estimate_tokens, record_ai_usage
    from bangla_gpt_api.services.tutor import sanitize_evidence

    prompt = EXTRACTION_PROMPT_TEMPLATE.format(chapter=chapter, text=sanitize_evidence(text[:4000]))
    started = time.perf_counter()
    try:
        raw = await provider.generate(prompt, system=EXTRACTION_SYSTEM_PROMPT)
    except Exception:
        return []
    if usage is not None:
        usage_db, usage_user_id = usage
        record_ai_usage(
            usage_db,
            user_id=usage_user_id,
            route="kg.rebuild",
            model=getattr(provider, "model", None) or getattr(provider, "name", None),
            prompt_text=prompt,
            answer_text=raw,
        )
    trace_event(
        "generation",
        route="knowledge_extraction",
        model=getattr(provider, "model", None) or getattr(provider, "name", "unknown"),
        prompt_version=_EXTRACTION_SPEC.trace_version,
        prompt_tokens=estimate_tokens(prompt),
        completion_tokens=estimate_tokens(raw),
        answer_chars=len(raw),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return parse_concept_names(raw, chapter=chapter, text=text, limit=limit)


# --- DB layer ----------------------------------------------------------------


def _seed_concepts(db: Session, chunks: Sequence[Chunk]) -> int:
    seeds = build_concept_seeds(chunks)
    pairs = build_edge_pairs(seeds)
    rows = [
        Concept(
            name=seed.name,
            class_level=seed.class_level,
            subject=seed.subject,
            chapter=seed.chapter,
            source=seed.source,
            aliases=list(seed.aliases),
        )
        for seed in seeds
    ]
    db.add_all(rows)
    db.flush()
    ids = [row.id for row in rows]
    db.add_all(
        ConceptPrerequisite(concept_id=ids[child], prereq_id=ids[prereq]) for child, prereq in pairs
    )
    db.commit()
    return len(rows)


def ensure_concepts(db: Session, chunks: Sequence[Chunk]) -> int:
    """Idempotent: seed chapter roots + curated edges when the graph is empty.
    Returns the number of concepts now present."""
    if db.execute(select(Concept.id).limit(1)).first() is not None:
        return int(db.execute(select(func.count(Concept.id))).scalar_one())
    return _seed_concepts(db, chunks)


async def rebuild_concepts(
    db: Session,
    chunks: Sequence[Chunk],
    provider: LLMProvider | None = None,
    *,
    llm: bool = False,
    usage_user_id: int | None = None,
) -> dict[str, int]:
    """Full re-seed. With llm=True AND a provider, also run corpus-verified
    LLM extraction per chapter (mock providers fail validation -> roots only,
    which keeps local/dev honest).

    ``usage_user_id`` (A1-04): when the caller can attribute the spend (the
    admin route passes the acting admin's id), every LLM extraction call is
    written to the ai_usage ledger with route ``kg.rebuild`` -- the last
    provider call site that used to bypass token accounting.
    """
    db.execute(delete(ConceptMastery))
    db.execute(delete(ConceptPrerequisite))
    db.execute(delete(Concept))
    db.commit()
    concepts = _seed_concepts(db, chunks)

    def _edge_count() -> int:
        return int(db.execute(select(func.count(ConceptPrerequisite.concept_id))).scalar_one())

    edges = _edge_count()
    llm_added = 0
    if llm and provider is not None:
        by_chapter: dict[tuple[int, str, str], list[str]] = {}
        for chunk in chunks:
            if chunk.meta.chapter:
                key = (chunk.meta.class_level, chunk.meta.subject, chunk.meta.chapter)
                by_chapter.setdefault(key, []).append(chunk.text)
        for (class_level, subject, chapter), texts in sorted(by_chapter.items()):
            joined = "\n".join(texts)
            names = await extract_chapter_concepts(
                provider,
                chapter=chapter,
                text=joined,
                # A1-04: attribute the extraction spend to the acting admin.
                usage=(db, usage_user_id) if usage_user_id is not None else None,
            )
            existing = {
                name
                for (name,) in db.execute(
                    select(Concept.name).where(
                        Concept.class_level == class_level, Concept.subject == subject
                    )
                )
            }
            for name in names:
                if name in existing:
                    continue
                db.add(
                    Concept(
                        name=name,
                        class_level=class_level,
                        subject=subject,
                        chapter=chapter,
                        source="llm",
                        aliases=[],
                    )
                )
                llm_added += 1
                existing.add(name)
        db.commit()
        edges = _edge_count()
    return {"concepts": concepts + llm_added, "llm_concepts": llm_added, "edges": edges}


def _bump_mastery(
    db: Session, student_id: int, concept_id: int, correct_add: int, total_add: int
) -> None:
    """Add to a mastery cell with ONE atomic statement (no lost updates).

    The previous read-modify-write (``row.correct += n``) lost updates when
    two quiz submissions for the same student overlapped: both sessions read
    the same row, the second commit overwrote the first increment. The
    conditional UPDATE moves the arithmetic into the database, which is the
    only place it is serialized. The INSERT fallback races too -- the loser's
    INSERT violates the composite primary key, and its retry finds the row
    the winner created.
    """
    updated = cast(
        CursorResult,
        db.execute(
            update(ConceptMastery)
            .where(
                ConceptMastery.student_id == student_id,
                ConceptMastery.concept_id == concept_id,
            )
            .values(
                correct=ConceptMastery.correct + correct_add,
                total=ConceptMastery.total + total_add,
            )
        ),
    )
    if updated.rowcount:
        return
    try:
        with db.begin_nested():
            db.add(
                ConceptMastery(
                    student_id=student_id,
                    concept_id=concept_id,
                    correct=correct_add,
                    total=total_add,
                )
            )
    except IntegrityError:
        # Another submission created the row first: apply our delta to theirs.
        db.execute(
            update(ConceptMastery)
            .where(
                ConceptMastery.student_id == student_id,
                ConceptMastery.concept_id == concept_id,
            )
            .values(
                correct=ConceptMastery.correct + correct_add,
                total=ConceptMastery.total + total_add,
            )
        )


def record_quiz_result(
    db: Session,
    student_id: int,
    review: Sequence[ReviewItem],
    class_level: int,
) -> None:
    """Grade-answer counts per concept: questions carrying finer extracted
    concepts credit those; every question always credits its chapter root."""
    rows = list(db.execute(select(Concept)).scalars())
    if not rows:
        return
    by_chapter: dict[str, list[Concept]] = {}
    for concept in rows:
        by_chapter.setdefault(concept.chapter, []).append(concept)

    updates: dict[int, tuple[int, int]] = {}
    for item in review:
        candidates = by_chapter.get(item.chapter, [])
        if not candidates:
            continue
        named = [c for c in candidates if c.source == "llm" and c.name in item.question_text]
        roots = [c for c in candidates if c.name == c.chapter]
        for concept in named + roots:
            correct, total = updates.get(concept.id, (0, 0))
            updates[concept.id] = (correct + (1 if item.is_correct else 0), total + 1)
    for concept_id, (correct_add, total_add) in updates.items():
        _bump_mastery(db, student_id, concept_id, correct_add, total_add)
    db.commit()


def mastery_map(db: Session, student_id: int) -> dict[str, tuple[int, int]]:
    """Per-concept-name graded counts (same-name chapter roots aggregate)."""
    rows = db.execute(
        select(Concept.name, ConceptMastery.correct, ConceptMastery.total)
        .join(ConceptMastery, ConceptMastery.concept_id == Concept.id)
        .where(ConceptMastery.student_id == student_id)
    ).all()
    out: dict[str, tuple[int, int]] = {}
    for name, correct, total in rows:
        correct_old, total_old = out.get(name, (0, 0))
        out[name] = (correct_old + correct, total_old + total)
    return out


def edges_by_name(db: Session) -> dict[str, tuple[str, ...]]:
    rows = db.execute(
        select(Concept.name, ConceptPrerequisite.prereq_id).join(
            ConceptPrerequisite, ConceptPrerequisite.concept_id == Concept.id
        )
    ).all()
    prereq_names = {concept.id: concept.name for concept in db.execute(select(Concept)).scalars()}
    out: dict[str, set[str]] = {}
    for name, prereq_id in rows:
        prereq_name = prereq_names.get(prereq_id)
        if prereq_name is not None and prereq_name != name:
            out.setdefault(name, set()).add(prereq_name)
    return {name: tuple(sorted(values)) for name, values in out.items()}


def student_gaps(db: Session, student_id: int) -> list[Gap]:
    """The gap report: weak concepts -> missing/weak prerequisites."""
    return resolve_gaps(mastery_map(db, student_id), edges_by_name(db))
