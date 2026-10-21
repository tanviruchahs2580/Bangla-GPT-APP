"""Load the built NCTB corpus into the retrieval Chunk model.

The JSONL produced by ``nctb.corpus`` is converted into
``curriculum.models.Chunk`` objects consumable by BM25Index/TutorService.

Class-level detection is DERIVED from book front matter; sources where the
class cannot be determined are indexed under every class in their declared
level range ONLY when ``multi_class_fallback=True`` — otherwise they are
skipped. This keeps class filtering honest instead of inventing metadata.

Served-text quality: private-use glyph residue (symbol-font bullets) is
replaced by spaces, and chunks whose text is still detectably legacy-Bijoy
ASCII are dropped with a count — an index must never serve either
(AUD-A1-01/AUD-A1-03; content QA's ``qa_text`` is the contract).

Load-time structure (AUD-A1-05/AUD-A1-06):

* identical passages are deduplicated on ``(class_level, normalized text)``
  — per-source dedupe cannot see the committee/front-matter pages the NCTB
  documents share, and the class-range fallback copies each raw chunk into
  every class of the level by construction;
* ``section`` comes from the chunk artifact (chunker), ``content_type`` is
  typed from the chunk's opening (exercise/assessment/example/table, else
  the historical ``nctb`` body-text label), and ``curriculum_year`` comes
  from the per-source report when the edition publishes one.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.nctb.bijoy import has_latin_residue, is_likely_legacy_bijoy
from bangla_gpt_api.nctb.normalize import strip_private_use
from bangla_gpt_api.services.safety import strip_injections

logger = logging.getLogger(__name__)

LEVEL_CLASS_RANGE = {
    "secondary": (6, 10),
    "hsc": (11, 12),
}

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


#: Opening-line signatures that type a chunk structurally. The marker must
#: sit in the first 10 characters of the chunk: the chunker flushes at a
#: section marker and appends it as the chunk's first line, while a
#: mid-paragraph mention of "উদাহরণ" is prose, not structure.
_CONTENT_TYPE_HINT_WINDOW = 10
#: The catalog's content_type vocabulary (master prompt A2-04): every chunk is
#: typed as one of these, or as the legacy ``nctb`` label for text that is
#: neither prose nor a detected structure (see infer_content_type).
CONTENT_TYPES = ("explanation", "example", "exercise", "table", "formula", "caption")
#: Pre-2026-10-20 artifacts label all prose ``nctb``; the loader still accepts
#: the value (filters use free strings) but no longer emits it for prose.
LEGACY_CONTENT_TYPE = "nctb"

_CONTENT_TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exercise", ("অনুশীলনী", "অনুশীলন", "নিজে করো", "নিজে কর")),
    ("assessment", ("সংক্ষিপ্ত প্রশ্ন", "বহু নির্বাচনি", "সৃজনশীল প্রশ্ন", "মূল্যায়ন")),
    ("example", ("উদাহরণ",)),
    ("table", ("সারণি", "ছক", "টেবিল")),
    ("caption", ("চিত্র", "ছবি", "লেখচিত্র", "ছকচিত্র")),
    ("formula", ("সমীকরণ", "সূত্র")),
)

#: Separator the chunker uses for a preserved table row (A2-04e): a chunk that
#: carries one holds tabular content even when its opening is not a "সারণি".
TABLE_CELL_SEPARATOR = " | "
#: Formula density: at least this share of the chunk's non-space characters
#: must be digits/operators, with at least this many of them, before a chunk
#: is typed ``formula`` without a marker. Measured conservatively: a prose
#: passage with a number in it never reaches it, a worked calculation does.
_FORMULA_DENSITY = 0.3
_FORMULA_MIN_CHARS = 12
_FORMULA_CHARS = frozenset(
    "0123456789=+-×÷·∗√∑∫≤≥≠≈±°^%<>/\\"
    "\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef"
    "\u00d7\u00f7\u2212\u2211\u222b\u2264\u2265\u2260\u2248\u00b1\u00b2\u00b3\u221a"
)
#: Prose needs at least this many letters (Bangla or Latin: the English
#: curriculum volume is prose too) and one sentence ender before it is typed
#: ``explanation``; anything shorter or thinner (number tables, stubs) stays
#: untyped.
_PROSE_MIN_LETTERS = 40
_SENTENCE_ENDERS = ("।", "?", "!", ".")


def _is_prose(text: str) -> bool:
    letters = sum(1 for char in text if char.isalpha())
    return letters >= _PROSE_MIN_LETTERS and any(ender in text for ender in _SENTENCE_ENDERS)


def _formula_density(text: str) -> float:
    compact = [char for char in text if not char.isspace()]
    if not compact:
        return 0.0
    formula = sum(1 for char in compact if char in _FORMULA_CHARS)
    if formula < _FORMULA_MIN_CHARS:
        return 0.0
    return formula / len(compact)


def infer_content_type(text: str) -> str:
    """Structural type of a chunk in the catalog's content_type vocabulary.

    Order (most specific first): an opening marker (exercise/assessment/
    example/table/caption/formula), a preserved table row, formula density,
    then prose — which is the catalog's ``explanation`` class, the body text of
    a curriculum document. ``nctb`` is the legacy label, now emitted only for
    text that is none of the above (administrative stubs, bare number tables),
    so old artifacts and the sample corpus stay distinguishable.
    """
    head = text[:80]
    for label, hints in _CONTENT_TYPE_HINTS:
        if any(0 <= head.find(hint) < _CONTENT_TYPE_HINT_WINDOW for hint in hints):
            return label
    if TABLE_CELL_SEPARATOR in text:
        return "table"
    if _formula_density(text) >= _FORMULA_DENSITY:
        return "formula"
    if _is_prose(text):
        return "explanation"
    return LEGACY_CONTENT_TYPE


def _resolve_year(report: dict) -> int:
    """Resolve curriculum year honestly: recorded edition or a safe bucket.

    The secondary listing page publishes 'প্রকাশকাল -২০১২' (stamped into the
    per-source report by the build); HSC pages do not state a year, so
    UNKNOWN editions fall back to the artifact set's build year purely as a
    versioning bucket — recorded as such, never presented as the edition.
    """
    year_text = str(report.get("curriculum_year", "")).strip()
    if year_text.isdigit():
        return int(year_text)
    built_at = str(report.get("built_at", ""))
    if built_at[:4].isdigit():
        return int(built_at[:4])
    return 2026


def load_nctb_corpus(
    chunks_dir: Path,
    quality_report_path: Path | None = None,
    *,
    multi_class_fallback: bool = True,
    version: str = "nctb-v1",
    stats: dict | None = None,
    manifest_path: Path | None = None,
) -> list[Chunk]:
    """Convert pipeline chunk files into index-ready Chunks.

    ``stats`` (optional, additive) receives ``duplicates_dropped``,
    ``injection_drops``, ``legacy_drops``, ``latin_residue_drops``,
    ``stale_sources_skipped`` and ``served_chunks`` for observability/reporting.

    ``manifest_path`` (A2-06/AUD-A1-07, optional for compatibility): the
    acquisition manifest is the ledger of what the pipeline currently
    acquires. When given, a chunk file whose source has no manifest row — or
    whose LAST row is not ``acquired`` (failed/renamed/deleted raw PDF) — is
    skipped and counted in ``stale_sources_skipped``: deleting a source must
    propagate to serving, not only to the next build (the build script's
    prune_outputs removes the artifacts; the loader check covers a serving
    process restarted on a half-pruned data dir).
    """
    reports = _load_quality_reports(quality_report_path)
    acquired_source_ids = _acquired_source_ids(manifest_path)

    chunks: list[Chunk] = []
    totals = _LoadTotals()
    seen_pairs: set[tuple[int, str]] = set()
    for path in sorted(chunks_dir.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        if not _source_is_current(source_id, acquired_source_ids):
            totals.stale_sources += 1
            logger.warning(
                "nctb_loader: skipped stale source %s (not acquired in the manifest)",
                source_id,
            )
            continue
        report: dict = reports.get(source_id, {})
        level = report.get("level")
        low_high = LEVEL_CLASS_RANGE.get(level) if level is not None else None
        if low_high is None:
            continue  # unknown provenance: never guess
        if report.get("bangla_char_ratio_on_usable", 0.0) < 0.5:
            continue  # failed legacy-Bijoy conversion never reaches the index
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                ingested = _ingest_line(
                    line,
                    report,
                    source_id,
                    low_high,
                    totals,
                    seen_pairs,
                    multi_class_fallback=multi_class_fallback,
                    version=version,
                )
                if ingested is not None:
                    chunks.extend(ingested)
    totals.log()
    if stats is not None:
        stats.update(totals.as_stats(served=len(chunks)))
    return chunks


def _load_quality_reports(path: Path | None) -> dict[str, dict]:
    if path is not None and path.exists():
        parsed: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        return parsed
    return {}


def _acquired_source_ids(manifest_path: Path | None) -> set[str] | None:
    """A2-06: the acquisition manifest is the ledger of what is served."""
    if manifest_path is None or not manifest_path.exists():
        return None
    from bangla_gpt_api.nctb.manifest import load_manifest

    return {
        source_id
        for source_id, record in load_manifest(manifest_path).items()
        if record.source_status == "acquired"
    }


def _source_is_current(source_id: str, acquired: set[str] | None) -> bool:
    return acquired is None or source_id in acquired


@dataclass
class _LoadTotals:
    """Per-load drop counters, logged once and reported through `stats`."""

    injection_drops: int = 0
    legacy_drops: int = 0
    residue_drops: int = 0
    duplicates: int = 0
    stale_sources: int = 0

    def log(self) -> None:
        if self.injection_drops:
            logger.warning(
                "nctb_loader: dropped %d prompt-injection sentences at load time",
                self.injection_drops,
            )
        if self.legacy_drops:
            logger.warning(
                "nctb_loader: dropped %d legacy-Bijoy chunks; rebuild the affected sources",
                self.legacy_drops,
            )
        if self.residue_drops:
            logger.warning(
                "nctb_loader: dropped %d Latin-residue chunks in Bangla-rated sources",
                self.residue_drops,
            )
        if self.duplicates:
            logger.info(
                "nctb_loader: dropped %d duplicate (class_level, text) pairs at load time",
                self.duplicates,
            )

    def as_stats(self, served: int) -> dict:
        return {
            "duplicates_dropped": self.duplicates,
            "injection_drops": self.injection_drops,
            "legacy_drops": self.legacy_drops,
            "latin_residue_drops": self.residue_drops,
            "stale_sources_skipped": self.stale_sources,
            "served_chunks": served,
        }


def _chunk_meta(
    data: dict,
    report: dict,
    source_id: str,
    low_high: tuple[int, int],
    text: str,
    version: str,
    *,
    multi_class_fallback: bool,
):
    """Metadata kwargs plus the class targets for one chunk; targets None when
    the class is undetected and the multi-class fallback is disabled."""
    subject_bn = report.get("subject_bn", "")
    low, high = low_high
    section = str(data.get("section") or "").strip()
    page_start = data.get("page_start")
    page_end = data.get("page_end")
    meta_kwargs = dict(
        curriculum_year=_resolve_year(report),
        subject=_subject_key(subject_bn),
        book=subject_bn,
        chapter=data.get("chapter", ""),
        section=section or None,
        page=page_start,
        # A2-04c: the raw chunk's page range is carried whole. The loader used
        # to drop page_end, so a chunk spanning pages 12-13 served only "12".
        page_end=page_end if page_end is not None else page_start,
        language="bn",
        version=version,
        content_type=infer_content_type(text),
        source=source_id,
    )
    detected = data.get("detected_class")
    if detected is None and not multi_class_fallback:
        return meta_kwargs, None
    targets = (
        [int(detected)]
        if detected is not None and low <= int(detected) <= high
        else list(range(low, high + 1))
    )
    return meta_kwargs, targets


def _ingest_line(
    line,
    report,  # noqa: ANN001 - internal pipeline payloads are dict-shaped
    source_id: str,
    low_high: tuple[int, int],
    totals: _LoadTotals,
    seen_pairs: set[tuple[int, str]],
    *,
    multi_class_fallback: bool,
    version: str,
):
    """Convert one chunk-file line into served Chunks; None when dropped."""
    if not line.strip():
        return None
    data = json.loads(line)
    text = strip_private_use(data["text"])
    if not text.strip():
        return None
    if is_likely_legacy_bijoy(text):
        totals.legacy_drops += 1
        return None
    # This source already passed the Bangla-ratio gate, so an ASCII-Latin
    # dominant chunk is an unconverted legacy passage, not English prose.
    if has_latin_residue(text):
        totals.residue_drops += 1
        return None
    # Same ingest-time injection filter the sample corpus gets.
    text, injection_drops = strip_injections(text)
    totals.injection_drops += injection_drops
    if not text:
        return None
    meta_kwargs, targets = _chunk_meta(
        data,
        report,
        source_id,
        low_high,
        text,
        version,
        multi_class_fallback=multi_class_fallback,
    )
    if targets is None:
        return None
    out = []
    fingerprint = " ".join(text.split())
    for class_level in targets:
        pair = (class_level, fingerprint)
        if pair in seen_pairs:
            totals.duplicates += 1
            continue
        seen_pairs.add(pair)
        out.append(
            Chunk(
                id=f"{data['chunk_id']}-c{class_level}",
                text=text,
                meta=CurriculumMeta(class_level=class_level, **meta_kwargs),
            )
        )
    return out


def attach_detected_classes(pages_json_dir: Path, chunks_dir: Path) -> dict[str, int | None]:
    """Detect class levels from front-matter pages and stamp chunk files.

    Returns per-source detection results. Detection output is derived
    metadata (master §13); undetected sources stay undetected.
    """
    from bangla_gpt_api.nctb.normalize import detect_class_level

    results: dict[str, int | None] = {}
    for pages_path in sorted(pages_json_dir.glob("*.pages.json")):
        source_id = pages_path.name.removesuffix(".pages.json")
        payload = json.loads(pages_path.read_text(encoding="utf-8"))
        front_matter = "\n".join(page["text"] for page in payload.get("pages", [])[:12])
        detected = detect_class_level(front_matter)
        results[source_id] = detected
        chunks_path = chunks_dir / f"{source_id}.chunks.jsonl"
        if not chunks_path.exists():
            continue
        lines = []
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            data["detected_class"] = detected
            lines.append(json.dumps(data, ensure_ascii=False))
        chunks_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results
