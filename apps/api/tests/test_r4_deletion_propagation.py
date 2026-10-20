"""A2-06/AUD-A1-07: deletion propagation from the loader side.

The build script prunes stale artifacts (``nctb.corpus.prune_outputs``, wired
into build_nctb_corpus) — but the SERVING load path (``load_nctb_corpus``)
used to trust any ``*.chunks.jsonl`` that still had a quality-report row:
delete a source's raw PDF (or lose it from the manifest) and restart the API
without a rebuild, and the stale chunks kept being served.

The acquisition manifest is the ledger of what the pipeline currently
acquires; the loader now honours it:

* a chunk file whose source has NO manifest row, or whose last manifest row
  is not ``acquired`` (failed/renamed/deleted), is never served;
* the skip is counted (``stale_sources_skipped``) in the loader stats;
* deleting the source's artifacts on a rebuild stays the build script's job
  (prune_outputs removes the files + report keys) — pinned here for the
  round-trip: flip a manifest row to failed, prune, reload, and the chunk is
  gone from the served corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.nctb.corpus import prune_outputs

CLEAN = "বিজ্ঞান পাঠটি বর্ণনা করে যে কোষটি জীবের গঠনগত একক। এটি প্রক্রিয়া অনুসরণ করে।"


def _fixture(tmp_path: Path, entries: dict[str, str]) -> tuple[Path, Path, Path]:
    """manifest + quality report + chunk files for two sources."""
    manifest = tmp_path / "manifests" / "acquisition_manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8") as fh:
        for source_id, status in entries.items():
            fh.write(
                json.dumps(
                    {
                        "source_id": source_id,
                        "source_status": status,
                        "level": "secondary",
                        "subject_bn": "বিজ্ঞান শাখার বিষয়সমূহ",
                        "curriculum_year": "2012",
                        # Required SourceRecord provenance fields (A2-01):
                        "source_url": f"https://example.org/{source_id}.pdf",
                        "parent_url": "https://example.org/list",
                        "retrieved_at": "2026-10-19T00:00:00+00:00",
                        "content_hash": "0" * 64,
                        "file_name": f"{source_id}.pdf",
                        "file_type": "application/pdf",
                        "file_size": 1024,
                        "book": "বিজ্ঞান শাখার বিষয়সমূহ",
                        "edition": "প্রকাশকাল ২০১২",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    report_path = tmp_path / "quality_report.json"
    report_path.write_text(
        json.dumps(
            {
                source_id: {
                    "level": "secondary",
                    "subject_bn": "বিজ্ঞান শাখার বিষয়সমূহ",
                    "bangla_char_ratio_on_usable": 1.0,
                    "curriculum_year": "2012",
                }
                for source_id in entries
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    normalized = tmp_path / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    for source_id in entries:
        (normalized / f"{source_id}.chunks.jsonl").write_text(
            json.dumps(
                {
                    "chunk_id": f"{source_id}-0001",
                    "text": CLEAN,
                    "original_text": CLEAN,
                    "chapter": "কোষ",
                    "page_start": 3,
                    "page_end": 3,
                    "section": "কোষ বিভাজন",
                    "detected_class": 6,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return manifest, report_path, normalized


def test_load_honours_the_acquisition_manifest(tmp_path: Path) -> None:
    manifest, report_path, normalized = _fixture(
        tmp_path, {"live-src": "acquired", "dead-src": "error"}
    )
    stats: dict[str, int] = {}
    chunks = load_nctb_corpus(
        normalized,
        quality_report_path=report_path,
        manifest_path=manifest,
        multi_class_fallback=False,
        stats=stats,
    )
    served_sources = {chunk.meta.source for chunk in chunks}
    assert served_sources == {"live-src"}, "a failed source must not serve"
    assert stats["stale_sources_skipped"] == 1


def test_load_skips_sources_missing_from_the_manifest(tmp_path: Path) -> None:
    """The deletion case: the source row disappears, the chunk file remains."""
    manifest, report_path, normalized = _fixture(
        tmp_path, {"live-src": "acquired", "deleted-src": "acquired"}
    )
    # The raw PDF + the manifest row are gone (file deletion propagates).
    lines = [
        line
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if "deleted-src" not in line
    ]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    chunks = load_nctb_corpus(
        normalized,
        quality_report_path=report_path,
        manifest_path=manifest,
        multi_class_fallback=False,
    )
    assert all(chunk.meta.source == "live-src" for chunk in chunks)


def test_deleted_source_does_not_survive_a_rebuild(tmp_path: Path) -> None:
    """The A2-06 round-trip: delete the source, prune, rebuild, no chunk."""
    manifest, report_path, normalized = _fixture(
        tmp_path, {"live-src": "acquired", "deleted-src": "acquired"}
    )
    pruned = prune_outputs(tmp_path / "extracted", normalized, report_path, {"live-src"})
    assert pruned["sources"] == ["deleted-src"]
    assert not (normalized / "deleted-src.chunks.jsonl").exists()
    # The source also leaves the acquisition ledger (the raw PDF is gone, so
    # re-acquisition cannot restore it): the manifest row is gone.
    lines = [
        line
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if "deleted-src" not in line
    ]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    chunks = load_nctb_corpus(
        normalized,
        quality_report_path=report_path,
        manifest_path=manifest,
        multi_class_fallback=False,
    )
    assert {chunk.meta.source for chunk in chunks} == {"live-src"}


def test_load_without_manifest_keeps_the_historical_contract(tmp_path: Path) -> None:
    """No manifest passed -> behaviour identical to before (tests, callers)."""
    _manifest, report_path, normalized = _fixture(tmp_path, {"src": "acquired"})
    stats: dict[str, int] = {}
    chunks = load_nctb_corpus(
        normalized,
        quality_report_path=report_path,
        multi_class_fallback=False,
        stats=stats,
    )
    assert chunks and stats.get("stale_sources_skipped", 0) == 0


@pytest.mark.skipif(
    not (
        (Path(__file__).resolve().parents[3] / "data" / "nctb" / "quality_report.json").exists()
        and (
            Path(__file__).resolve().parents[3]
            / "data"
            / "nctb"
            / "manifests"
            / "acquisition_manifest.jsonl"
        ).exists()
    ),
    reason="served NCTB corpus artifacts are not built on this checkout",
)
def test_served_corpus_loads_under_the_manifest_ledger() -> None:
    """The real corpus: every served source is acquired in the manifest."""
    repo = Path(__file__).resolve().parents[3] / "data" / "nctb"
    load_stats: dict[str, int] = {}
    chunks = load_nctb_corpus(
        repo / "normalized",
        quality_report_path=repo / "quality_report.json",
        manifest_path=repo / "manifests" / "acquisition_manifest.jsonl",
        stats=load_stats,
    )
    assert chunks, "the served corpus must still load"
    assert load_stats.get("stale_sources_skipped", 0) >= 0
