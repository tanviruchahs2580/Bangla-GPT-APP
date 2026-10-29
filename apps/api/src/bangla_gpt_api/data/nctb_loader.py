"""Load the built NCTB corpus into the retrieval Chunk model.

The JSONL produced by ``nctb.corpus`` is converted into
``curriculum.models.Chunk`` objects consumable by BM25Index/TutorService.

Class-level attribution is DERIVED, never invented (F-049/RAG-06). For every
source the loader resolves one of three bases, in order:

1. **detected** — a book-level class statement ("একাদশ ও দ্বাদশ শ্রেণি") read
   from the cover/title page, either stamped at build time
   (:func:`attach_detected_classes`) or read from the sibling ``extracted/``
   pages at load time;
2. **level-range** — the acquisition listing's declared level to class range
   (``LEVEL_CLASS_RANGE``: the official secondary/HSC listing headings); used
   only with ``multi_class_fallback=True``, because it attributes a whole
   level to a book, not a class;
3. **refused** — neither signal exists, so the source is skipped with a
   warning instead of being spread across an assumed range.

The former behaviour made basis 2 the silent default for every source (class
detection returned None for all nine books), which fabricated per-class
metadata by 5x expansion and made class totals artificially equal.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.services.safety import strip_injections

logger = logging.getLogger(__name__)

LEVEL_CLASS_RANGE = {
    "secondary": (6, 10),
    "hsc": (11, 12),
}

#: Book-level class statements are printed on the cover / title page. Later
#: front-matter pages carry curriculum policy prose that names many classes
#: ("ষষ্ঠ থেকে অষ্টম শ্রেণির ১৭টি বিষয় ... নবম ও দশম শ্রেণির ২৭টি"), which is
#: not a statement about the book and must not become per-book metadata.
COVER_PAGES = 2

# Subject mapping from official Bangla listing titles to API subject keys.
SUBJECT_KEYS = {
    "বাংলা": "bangla",
    "ইংরেজি": "english",
    "ইংরেজ": "english",
    "গণিত ও উচ্চতর গণিত": "mathematics",
    "উচ্চতর গণিত": "higher-mathematics",
    "বিজ্ঞান শাখার বিষয়সমূহ": "science",
    "পদার্থবিদ্যা": "physics",
    "রসায়ন": "chemistry",
    "জীববিজ্ঞান": "biology",
    "আইসিটি ও ক্যারিয়ার এডুকেশন": "ict",
    "তথ্য ও যোগাযোগ প্রযুক্তি": "ict",
    "আইসিটি (ষষ্ঠ শ্রেণি)": "ict",
}


def _subject_key(subject_bn: str) -> str:
    return SUBJECT_KEYS.get(subject_bn, "general")


def cover_text(pages_payload: dict) -> str:
    """The cover/title-page text of one extracted source (see COVER_PAGES)."""
    pages = pages_payload.get("pages") or []
    return "\n".join(str(page.get("text", "")) for page in pages[:COVER_PAGES])


def detect_source_classes(pages_payload: dict) -> tuple[int, ...]:
    """Book-level class levels from an extracted ``*.pages.json`` payload."""
    from bangla_gpt_api.nctb.normalize import detect_class_levels

    return detect_class_levels(cover_text(pages_payload))


def resolve_class_targets(
    level: str,
    detected: tuple[int, ...] | None,
    *,
    multi_class_fallback: bool,
) -> tuple[list[int], str]:
    """Class levels to index one source under, with the attribution basis.

    Returns ``(targets, basis)`` where basis is ``"detected"``,
    ``"level-range"`` or ``"refused"`` (empty targets). A detected set that
    falls outside the declared level range is refused rather than clipped:
    the disagreement means one of the two signals is wrong, and indexing
    under either would be a guess.
    """
    low, high = LEVEL_CLASS_RANGE[level]
    if detected:
        in_range = sorted({int(cls) for cls in detected if low <= int(cls) <= high})
        if len(in_range) == len(set(detected)) and in_range:
            return in_range, "detected"
        logger.warning(
            "nctb_loader: detected classes %s are outside the declared %s level range "
            "%s-%s; refusing to index rather than guess",
            sorted(set(detected)),
            level,
            low,
            high,
        )
        return [], "refused"
    if multi_class_fallback:
        return list(range(low, high + 1)), "level-range"
    return [], "refused"


def _stamped_classes(row: dict, source_id: str, pages_dir: Path | None) -> tuple[int, ...]:
    """Detected classes for one source: build-time stamp, else its cover page."""
    stamped = row.get("detected_classes")
    if stamped:
        return tuple(int(cls) for cls in stamped)
    legacy_single = row.get("detected_class")
    if legacy_single is not None:
        return (int(legacy_single),)
    if pages_dir is not None:
        pages_path = pages_dir / f"{source_id}.pages.json"
        if pages_path.exists():
            return detect_source_classes(json.loads(pages_path.read_text(encoding="utf-8")))
    return ()


def _resolve_year(report: dict) -> int:
    """Resolve curriculum year honestly: recorded edition or a safe bucket.

    The secondary listing page publishes 'প্রকাশকাল -২০১২'; HSC pages do not
    state a year, so UNKNOWN years fall back to the acquisition year of the
    artifact set (2026) purely as a versioning bucket — recorded as such.
    """
    year_text = str(report.get("curriculum_year", "")).strip()
    if year_text.isdigit():
        return int(year_text)
    return 2026


def load_nctb_corpus(
    chunks_dir: Path,
    quality_report_path: Path | None = None,
    *,
    multi_class_fallback: bool = True,
    version: str = "nctb-v1",
    pages_dir: Path | None = None,
) -> list[Chunk]:
    """Convert pipeline chunk files into index-ready Chunks.

    ``pages_dir`` (default: the sibling ``extracted/`` directory of
    ``chunks_dir`` when it exists) lets the loader read a source's cover page
    for its book-level class statement, so a build that predates the
    ``detected_classes`` stamp still gets truthful class attribution.
    """
    reports: dict[str, dict] = {}
    if quality_report_path is not None and quality_report_path.exists():
        reports = json.loads(quality_report_path.read_text(encoding="utf-8"))
    if pages_dir is None:
        candidate = chunks_dir.parent / "extracted"
        pages_dir = candidate if candidate.is_dir() else None

    chunks: list[Chunk] = []
    injection_drops_total = 0
    refused_sources: list[str] = []
    level_derived_sources: list[str] = []
    for path in sorted(chunks_dir.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        report = reports.get(source_id, {})
        level = report.get("level")
        if level not in LEVEL_CLASS_RANGE:
            continue  # unknown provenance → never guess
        # Safety gate: sources whose text is not predominantly Bangla Unicode
        # (e.g., failed legacy-Bijoy conversion) never reach the tutor index.
        if report.get("bangla_char_ratio_on_usable", 0.0) < 0.5:
            continue
        subject_bn = report.get("subject_bn", "")
        year = _resolve_year(report)
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not rows:
            continue
        # Detection is stamped identically on every chunk of a source, so one
        # row decides the attribution for the whole source.
        detected = _stamped_classes(rows[0], source_id, pages_dir)
        targets, basis = resolve_class_targets(
            level, detected, multi_class_fallback=multi_class_fallback
        )
        if not targets:
            refused_sources.append(source_id)
            continue
        if basis == "level-range":
            level_derived_sources.append(source_id)
        meta_kwargs = dict(
            curriculum_year=year,
            subject=_subject_key(subject_bn),
            book=subject_bn,
            section=None,
            language="bn",
            version=version,
            content_type="nctb",
            source=source_id,
        )
        for data in rows:
            text = data["text"]
            if not text:
                continue
            # Same ingest-time injection filter the sample corpus gets
            # (services/safety.py documents it as the first of the two
            # injection defenses) — without it the production corpus
            # path would skip the filter entirely.
            text, injection_drops = strip_injections(text)
            injection_drops_total += injection_drops
            if not text:
                continue
            for class_level in targets:
                chunks.append(
                    Chunk(
                        id=f"{data['chunk_id']}-c{class_level}",
                        text=text,
                        meta=CurriculumMeta(
                            class_level=class_level,
                            chapter=data.get("chapter", ""),
                            page=data.get("page_start"),
                            **meta_kwargs,
                        ),
                    )
                )
    if refused_sources:
        # Never silent: a source with no class signal is not indexed at all,
        # so the served corpus's scope is visible in the boot log.
        logger.warning(
            "nctb_loader: refused %d source(s) with no class signal (no cover statement, "
            "level-range fallback disabled): %s",
            len(refused_sources),
            refused_sources,
        )
    if level_derived_sources:
        logger.warning(
            "nctb_loader: %d source(s) indexed under their DECLARED LEVEL's class range "
            "(no book-level class statement on the cover): %s",
            len(level_derived_sources),
            level_derived_sources,
        )
    if injection_drops_total:
        logger.warning(
            "nctb_loader: dropped %d prompt-injection sentences at load time",
            injection_drops_total,
        )
    return chunks


def attach_detected_classes(pages_json_dir: Path, chunks_dir: Path) -> dict[str, int | None]:
    """Detect class levels from front-matter pages and stamp chunk files.

    Stamps the range-aware ``detected_classes`` (the cover's book-level
    statement) plus the legacy single-class ``detected_class`` field, whose
    value is the lone class only when the cover declares exactly one.
    Returns per-source detection results in the legacy single-class form.
    Detection output is derived metadata (master §13); undetected sources stay
    undetected.
    """
    results: dict[str, int | None] = {}
    for pages_path in sorted(pages_json_dir.glob("*.pages.json")):
        source_id = pages_path.name.removesuffix(".pages.json")
        payload = json.loads(pages_path.read_text(encoding="utf-8"))
        detected = detect_source_classes(payload)
        results[source_id] = detected[0] if len(detected) == 1 else None
        chunks_path = chunks_dir / f"{source_id}.chunks.jsonl"
        if not chunks_path.exists():
            continue
        lines = []
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            data["detected_classes"] = list(detected) if detected else None
            data["detected_class"] = detected[0] if len(detected) == 1 else None
            lines.append(json.dumps(data, ensure_ascii=False))
        chunks_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results
