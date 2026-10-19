"""AUD-A1-05/A1-06/A1-07: load-time structure metadata, dedupe and staleness.

Measured before the fix (real corpus, 2026-10-18): ``section=None`` for all
2504 served chunks, ``content_type='nctb'`` constant, ``curriculum_year=2026``
for every source although the secondary editions publish 2012, and 979
duplicated ``(class_level, text)`` pairs — the committee/front-matter pages
the NCTB volumes share, copied into every class by the level-range fallback.
Deleting a raw file left its previous ``*.chunks.jsonl`` indexable.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import infer_content_type, load_nctb_corpus
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.corpus import coverage_report, prune_outputs, rights_summary
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.manifest import SourceRecord

# Long enough (>= MIN_WORDS) that each text produces its own chunk: the
# chunker merges sub-minimum blocks instead of dropping them.
SHARED = "জাতীয় শিক্ষাক্রম ও পাঠ্যপুস্তক বোর্ডের সদস্য তালিকা প্রণয়ন এবং প্রকাশ। " * 10
OWN_A = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত একক এবং কার্যগত একক যা প্রতিটি জীবের দেহে থাকে। " * 8
OWN_B = "মাইটোসিস কোষ বিভাজনে সন্ততি কোষের ক্রোমোজোম সংখ্যা অপরিবর্তিত থাকে এবং গুণ থাকে। " * 8


def _write_source(
    tmp_path: Path,
    source_id: str,
    level: str,
    texts: list[str],
    *,
    detected_class: int | None = None,
    per_text_chapter: bool = False,
    **report_extra: object,
) -> None:
    normalized = tmp_path / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    if per_text_chapter:
        # One chunk per text: a chapter heading forces a flush, which is what
        # the real books do between chapters.
        texts = [f"অধ্যায়: পাঠ {i}\n{text}" for i, text in enumerate(texts, start=1)]
    chunks = chunk_pages(
        [PageText(i + 1, text) for i, text in enumerate(texts)], source_id=source_id
    )
    with (normalized / f"{source_id}.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            row = asdict(chunk)
            row["detected_class"] = detected_class
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    report_path = tmp_path / "quality_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    report[source_id] = {
        "level": level,
        "subject_bn": "বিজ্ঞান শাখার বিষয়সমূহ",
        "bangla_char_ratio_on_usable": 1.0,
        **report_extra,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _load(tmp_path: Path, **kwargs: object) -> list:
    stats: dict = {}
    chunks = load_nctb_corpus(
        tmp_path / "normalized",
        tmp_path / "quality_report.json",
        stats=stats,
        **kwargs,  # type: ignore[arg-type]
    )
    _load.stats = stats  # type: ignore[attr-defined]
    return chunks


def test_cross_source_duplicates_are_dropped_at_load(tmp_path: Path) -> None:
    """Two sources sharing a passage must not index it twice per class."""
    _write_source(
        tmp_path, "src-a", "secondary", [OWN_A, SHARED], detected_class=6, per_text_chapter=True
    )
    _write_source(
        tmp_path, "src-b", "secondary", [OWN_B, SHARED], detected_class=6, per_text_chapter=True
    )

    chunks = _load(tmp_path)

    texts = [chunk.text for chunk in chunks]
    assert texts.count(SHARED.strip()) == 1, "shared passage served once"
    assert _load.stats["duplicates_dropped"] == 1
    assert _load.stats["served_chunks"] == len(chunks) == 3


def test_class_range_fallback_duplicates_are_dropped(tmp_path: Path) -> None:
    """Without detection, the fallback fans one raw chunk into 5 classes; the
    pairs are distinct per class and must all survive."""
    _write_source(tmp_path, "src-a", "secondary", [OWN_A, SHARED], per_text_chapter=True)

    chunks = _load(tmp_path)

    assert {chunk.meta.class_level for chunk in chunks} == {6, 7, 8, 9, 10}
    # same text under different classes is NOT a duplicate
    assert _load.stats["duplicates_dropped"] == 0
    assert len(chunks) == 2 * 5


def test_section_and_content_type_are_carried_from_the_artifact(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "src-a",
        "secondary",
        [
            "অধ্যায়: কোষ\n" + "কোষ হলো জীবের গঠনগত একক এবং কার্যগত একক। " * 10,
            "অনুশীলনী\n" + "১। কোষ কী? বিস্তারিত ব্যাখ্যা কর এবং চিত্রসহ বর্ণনা দাও। " * 10,
        ],
        detected_class=6,
    )

    chunks = _load(tmp_path, multi_class_fallback=False)

    sections = {chunk.meta.section for chunk in chunks}
    assert "অনুশীলনী" in sections, "the exercise section marker must reach the metadata"
    types = {chunk.meta.content_type for chunk in chunks}
    assert "exercise" in types, f"exercise chunk must be typed, got {types}"


def test_content_type_inference_covers_structure_not_just_body() -> None:
    assert infer_content_type("অনুশীলনী ১। কোষ কী?") == "exercise"
    assert infer_content_type("সংক্ষিপ্ত প্রশ্ন: কোষ বিভাজন ব্যাখ্যা কর") == "assessment"
    assert infer_content_type("উদাহরণ ৩: লব ও হর") == "example"
    assert infer_content_type("সারণি ১: শিক্ষাক্রম কাঠামো") == "table"
    assert infer_content_type("কোষ হলো জীবের একক।") == "nctb"
    # a mid-sentence mention is not a structural signature
    assert infer_content_type("এখানে একটি উদাহরণ দিয়ে ব্যাখ্যা করা হলো যাতে বোঝা যায়") == "nctb"


def test_curriculum_year_comes_from_the_report_not_the_build_year(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "src-a",
        "secondary",
        [OWN_A],
        detected_class=6,
        curriculum_year="2012",
        built_at="2026-10-18T00:00:00+00:00",
    )
    _write_source(
        tmp_path,
        "src-b",
        "hsc",
        [OWN_B],
        detected_class=11,
        curriculum_year="UNKNOWN",
        built_at="2021-05-05T00:00:00+00:00",
    )

    chunks = _load(tmp_path)
    years = {chunk.meta.source: chunk.meta.curriculum_year for chunk in chunks}
    assert years["src-a"] == 2012, "published edition year must be served"
    # an unpublished edition falls back to the artifact set's build year —
    # never to the current year as if it were the edition.
    assert years["src-b"] == 2021


def test_missing_raw_file_drops_the_stale_chunks_artifact(tmp_path: Path) -> None:
    """AUD-A1-07: a source that cannot be reprocessed must not stay indexable."""
    from bangla_gpt_api.nctb.corpus import process_source

    _write_source(tmp_path, "src-a", "secondary", [OWN_A], detected_class=6)
    normalized = tmp_path / "normalized"
    extracted = tmp_path / "extracted"
    report = tmp_path / "quality_report.json"
    record = SourceRecord(
        source_id="src-a",
        source_url="https://example.invalid/a.pdf",
        parent_url="https://example.invalid/list",
        retrieved_at="2026-10-18T00:00:00+00:00",
        content_hash="0" * 64,
        file_name="a.pdf",
        file_type="application/pdf",
        file_size=10,
        level="secondary",
        subject_bn="বিজ্ঞান শাখার বিষয়সমূহ",
        book="বিজ্ঞান শাখার বিষয়সমূহ",
        curriculum_year="2012",
        edition="প্রকাশকাল ২০১২",
    )
    summary = process_source(
        record, tmp_path / "raw", extracted, normalized, report, max_pages=None
    )
    assert summary["error"] == "raw file missing"
    assert not (normalized / "src-a.chunks.jsonl").exists(), "stale chunks must be pruned"
    assert "src-a" in report.read_text(encoding="utf-8")


def test_prune_outputs_removes_no_longer_acquired_sources(tmp_path: Path) -> None:
    _write_source(tmp_path, "src-a", "secondary", [OWN_A], detected_class=6)
    _write_source(tmp_path, "src-b", "secondary", [OWN_B], detected_class=6)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "src-b.pages.json").write_text("{}", encoding="utf-8")

    pruned = prune_outputs(
        extracted, tmp_path / "normalized", tmp_path / "quality_report.json", {"src-a"}
    )

    assert pruned["sources"] == ["src-b"]
    assert not (tmp_path / "normalized" / "src-b.chunks.jsonl").exists()
    assert (tmp_path / "normalized" / "src-a.chunks.jsonl").exists()
    report = json.loads((tmp_path / "quality_report.json").read_text(encoding="utf-8"))
    assert set(report) == {"src-a"}


def test_coverage_report_lists_class_subject_chapters(tmp_path: Path) -> None:
    _write_source(tmp_path, "src-a", "secondary", ["অধ্যায়: কোষ\n" + OWN_A], detected_class=6)

    coverage = coverage_report(tmp_path / "normalized", tmp_path / "quality_report.json")

    assert set(coverage["classes"]) == {"6"}
    entry = coverage["classes"]["6"]["science"]
    assert entry["chapters"] == ["কোষ"]
    assert entry["sources"] == ["src-a"]
    assert coverage["unassigned_sources"] == []


def test_rights_summary_is_per_document_not_boilerplate() -> None:
    record = SourceRecord(
        source_id="src-a",
        source_url="https://example.invalid/a.pdf",
        parent_url="https://example.invalid/list",
        retrieved_at="2026-10-18T00:00:00+00:00",
        content_hash="0" * 64,
        file_name="a.pdf",
        file_type="application/pdf",
        file_size=10,
        level="secondary",
        subject_bn="বাংলা",
        book="বাংলা",
        curriculum_year="2012",
        edition="প্রকাশকাল ২০১২",
    )
    rights = rights_summary(record)
    assert rights["public_download_url"] == record.source_url
    assert rights["parent_page"] == record.parent_url
    assert rights["permission_status"] == "official-public-download"
    assert rights["redistribution"] == "not-granted-in-writing"
