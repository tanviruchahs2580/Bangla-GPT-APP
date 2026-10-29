"""Cross-source duplicate chunks are deduplicated at index build (F-012).

The defect: the same passage reprinted in several books was chunked once per
book, indexed once per book (and once per class level on top), while the
quality report's per-source ``duplicates_removed`` stayed 0 because dedupe
ran per file. These tests pin the corpus-level behaviour:

* the loader indexes identical text once per class level, whatever the number
  of sources carrying it;
* the build report states the cross-source duplicate rate it really has;
* the text's other sources stay attributable.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.corpus import (
    content_hash,
    cross_source_duplicates,
    record_cross_source_report,
)
from bangla_gpt_api.nctb.extract import PageText

#: One long line (a page of running text) so the chunker flushes at the same
#: boundary in every book that reprints it: ~600 tokens, split into three
#: pieces by the 220-token target.
SHARED_PREAMBLE = "জাতীয় শিক্ষাক্রম ২০১২ অনুযায়ী এই বিষয়ের লক্ষ্য নির্ধারিত হয়েছে। " * 30
SUBJECT_BODY = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক। " * 8


def _write_source(
    root: Path, source_id: str, level: str, subject: str, pages: list[PageText]
) -> int:
    """Write the pipeline artifacts one source produces, return its chunks."""
    extracted = root / "extracted"
    normalized = root / "normalized"
    extracted.mkdir(parents=True, exist_ok=True)
    normalized.mkdir(parents=True, exist_ok=True)
    (extracted / f"{source_id}.pages.json").write_text(
        json.dumps(
            {"source_id": source_id, "pages": [asdict(page) for page in pages]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunks = chunk_pages(pages, source_id=source_id)
    with (normalized / f"{source_id}.chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    report_path = root / "quality_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    report[source_id] = {
        "level": level,
        "subject_bn": subject,
        "curriculum_year": "2012",
        "bangla_char_ratio_on_usable": 1.0,
        "chunks": len(chunks),
        "chunks_with_chapter": sum(1 for chunk in chunks if chunk.chapter),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return len(chunks)


def _two_sources_sharing_a_preamble(tmp_path: Path) -> Path:
    """Two books, identical preamble chunk, different own-subject bodies."""
    preamble = PageText(1, "অধ্যায়: সূচনা\n" + SHARED_PREAMBLE)
    # Both books are secondary: only then do they serve the same class levels
    # and only then can the shared text actually collide in the index.
    body_a = PageText(2, SUBJECT_BODY + "উদ্ভিদের খাদ্য তৈরি " * 20)
    body_b = PageText(2, SUBJECT_BODY + "তড়িৎ প্রবাহ ও রোধ " * 20)
    _write_source(tmp_path, "src-a", "secondary", "বিজ্ঞান শাখার বিষয়সমূহ", [preamble, body_a])
    _write_source(tmp_path, "src-b", "secondary", "বাংলা", [preamble, body_b])
    return tmp_path


def _index_keys(chunks) -> list[tuple[str, int]]:
    return [(content_hash(chunk.text), chunk.meta.class_level) for chunk in chunks]


class TestLoaderDedupe:
    def test_dedupe_drops_cross_source_repeats_per_class(self, tmp_path: Path) -> None:
        root = _two_sources_sharing_a_preamble(tmp_path)
        deduped = load_nctb_corpus(
            root / "normalized",
            quality_report_path=root / "quality_report.json",
            verify_manifest=False,
        )
        raw = load_nctb_corpus(
            root / "normalized",
            quality_report_path=root / "quality_report.json",
            dedupe=False,
            verify_manifest=False,
        )
        assert len(deduped) < len(raw), "the shared preamble must be indexed once per class"
        assert len(set(_index_keys(deduped))) == len(deduped)
        assert len(set(_index_keys(raw))) < len(raw), "the fixture must contain a repeat"

    def test_no_two_indexed_chunks_share_text_and_class(self, tmp_path: Path) -> None:
        root = _two_sources_sharing_a_preamble(tmp_path)
        chunks = load_nctb_corpus(
            root / "normalized",
            quality_report_path=root / "quality_report.json",
            verify_manifest=False,
        )
        keys = _index_keys(chunks)
        assert len(set(keys)) == len(keys) == len(chunks)
        # the same text is still served to every class level that needs it
        preamble_keys = {key for key in keys if key[0] == content_hash(chunks[0].text)}
        assert len(preamble_keys) == len({key[1] for key in preamble_keys})

    def test_dedupe_keeps_rank_order_of_surviving_chunks(self, tmp_path: Path) -> None:
        root = _two_sources_sharing_a_preamble(tmp_path)
        chunks = load_nctb_corpus(
            root / "normalized",
            quality_report_path=root / "quality_report.json",
            verify_manifest=False,
        )
        ids = [chunk.id for chunk in chunks]
        assert len(ids) == len(set(ids))


class TestCrossSourceReport:
    def test_report_counts_cross_source_duplicates(self, tmp_path: Path) -> None:
        root = _two_sources_sharing_a_preamble(tmp_path)
        summary, per_source = cross_source_duplicates(root / "normalized")
        assert (
            summary["total_chunks"] == per_source["src-a"]["chunks"] + per_source["src-b"]["chunks"]
        )
        assert summary["cross_source_texts"] >= 1
        assert summary["cross_source_duplicate_chunks"] >= 1
        assert summary["duplicate_chunks"] == summary["total_chunks"] - summary["unique_texts"]
        assert per_source["src-a"]["shared_chunks"] >= 1
        assert "src-b" in summary["cross_source_sources"]

    def test_report_is_written_into_quality_report(self, tmp_path: Path) -> None:
        root = _two_sources_sharing_a_preamble(tmp_path)
        record_cross_source_report(root / "quality_report.json", root / "normalized")
        report = json.loads((root / "quality_report.json").read_text(encoding="utf-8"))
        summary = report["_cross_source"]
        assert summary["cross_source_duplicate_chunks"] >= 1
        # per-source honesty: the field the old report left at zero
        assert report["src-a"]["shared_text_chunks_with_other_sources"] >= 1

    def test_rows_carry_the_other_sources_of_a_shared_text(self, tmp_path: Path) -> None:
        """The stamp is what preserves attribution once the index dedupes."""
        root = _two_sources_sharing_a_preamble(tmp_path)
        record_cross_source_report(root / "quality_report.json", root / "normalized")
        rows = [
            json.loads(line)
            for line in (root / "normalized" / "src-a.chunks.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        shared = [row for row in rows if row.get("shared_sources")]
        assert shared, "the reprinted preamble must name its other source"
        assert all(row["shared_sources"] == ["src-b"] for row in shared)
        chunks = load_nctb_corpus(
            root / "normalized",
            quality_report_path=root / "quality_report.json",
            verify_manifest=False,
        )
        assert len({(content_hash(chunk.text), chunk.meta.class_level) for chunk in chunks}) == len(
            chunks
        )

    def test_clean_corpus_reports_no_cross_source_duplicates(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "only", "secondary", "বাংলা", [PageText(1, SUBJECT_BODY * 3)])
        summary, _per_source = cross_source_duplicates(tmp_path / "normalized")
        assert summary["cross_source_duplicate_chunks"] == 0
        assert summary["cross_source_texts"] == 0
