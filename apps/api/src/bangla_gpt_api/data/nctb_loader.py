"""Load the built NCTB corpus into the retrieval Chunk model.

The JSONL produced by ``nctb.corpus`` is converted into
``curriculum.models.Chunk`` objects consumable by BM25Index/TutorService.

Class-level detection is DERIVED from book front matter; sources where the
class cannot be determined are indexed under every class in their declared
level range ONLY when ``multi_class_fallback=True`` — otherwise they are
skipped. This keeps class filtering honest instead of inventing metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta

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
) -> list[Chunk]:
    """Convert pipeline chunk files into index-ready Chunks."""
    reports: dict[str, dict] = {}
    if quality_report_path is not None and quality_report_path.exists():
        reports = json.loads(quality_report_path.read_text(encoding="utf-8"))

    chunks: list[Chunk] = []
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
        low, high = LEVEL_CLASS_RANGE[level]
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                data = json.loads(line)
                text = data["text"]
                if not text:
                    continue
                meta_kwargs = dict(
                    curriculum_year=year,
                    subject=_subject_key(subject_bn),
                    book=subject_bn,
                    chapter=data.get("chapter", ""),
                    section=None,
                    page=data.get("page_start"),
                    language="bn",
                    version=version,
                    content_type="nctb",
                    source=source_id,
                )
                detected = data.get("detected_class")
                targets = (
                    [int(detected)]
                    if detected is not None and low <= int(detected) <= high
                    else list(range(low, high + 1))
                )
                if detected is None and not multi_class_fallback:
                    continue
                for class_level in targets:
                    chunks.append(
                        Chunk(
                            id=f"{data['chunk_id']}-c{class_level}",
                            text=text,
                            meta=CurriculumMeta(class_level=class_level, **meta_kwargs),
                        )
                    )
    return chunks


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
