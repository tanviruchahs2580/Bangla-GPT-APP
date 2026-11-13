"""V4 G4 (S3): byte-identical re-ingestion idempotence.

Running the full pipeline twice over the same inputs must produce the same
artifacts. Anything else means the build is order-dependent or stateful, and
a later rebuild could silently change the served corpus.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText


def _write_corpus(target: Path) -> None:
    pages = [
        PageText(page_number=1, text="ভূমিকা\nবিজ্ঞান একটি প্রক্রিয়া।", encoding="unicode"),
        PageText(page_number=2, text="বল ও গতি\nনিউটনের প্রথম সূত্র জড়তার সূত্র।", encoding="unicode"),
        PageText(
            page_number=3,
            text="পরিমাপ\nদৈর্ঘ্য মাপার একক মিটার। আয়তন মাপার একক ঘনমিটার।",
            encoding="unicode",
        ),
    ]
    extracted = target / "extracted"
    normalized = target / "normalized"
    extracted.mkdir(parents=True)
    normalized.mkdir(parents=True)
    (extracted / "synthetic-nctb.pages.json").write_text(
        json.dumps({"source_id": "synthetic-nctb", "pages": [asdict(p) for p in pages]}),
        encoding="utf-8",
    )
    chunks = chunk_pages(pages, source_id="synthetic-nctb")
    with (normalized / "synthetic-nctb.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")


def _build(target: Path) -> str:
    """Run the ingest-side build twice-safe: return the loader's output."""
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

    _write_corpus(target)
    report_path = target / "quality_report.json"
    report_path.write_text(
        json.dumps(
            {
                "synthetic-nctb": {
                    "level": "secondary",
                    "subject_bn": "পদার্থবিদ্যা",
                    "curriculum_year": "2012",
                    "bangla_char_ratio_on_usable": 0.9,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunks = load_nctb_corpus(
        chunks_dir=target / "normalized",
        quality_report_path=report_path,
        verify_manifest=False,
    )
    # Serialization order is the contract: the same input set must list the
    # same chunks in the same order with the same payloads.
    return json.dumps([asdict(c) for c in chunks], ensure_ascii=False, sort_keys=True)


def test_rebuild_is_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "run1"
    second = tmp_path / "run2"
    assert _build(first) == _build(second)


def test_rebuild_artifacts_are_byte_identical(tmp_path: Path) -> None:
    """The chunks.jsonl artifact itself, not just the loader output, is stable."""
    import hashlib

    def build_artifact(target: Path) -> str:
        _write_corpus(target)
        data = (target / "normalized" / "synthetic-nctb.chunks.jsonl").read_bytes()
        return hashlib.sha256(data).hexdigest()

    assert build_artifact(tmp_path / "a") == build_artifact(tmp_path / "b")
