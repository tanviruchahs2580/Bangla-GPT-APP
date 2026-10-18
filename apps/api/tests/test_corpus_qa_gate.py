"""The index must only ever serve corpus text that passes content QA.

Before this guard the loader filtered whole sources by their Bangla
character ratio, so private-use glyph residue (symbol-font bullets) and
legacy-Bijoy ASCII chunks flowed into the tutor index — 907 of 2508
served chunks carried ``pua_char``/``legacy_bijoy`` flags (AUD-A1-01,
AUD-A1-03). These tests pin the repair: loading strips the residue,
drops chunks that are still unreadable legacy encodings, and the served
set passes ``qa_chunks`` with the default threshold.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.nctb.content_qa import qa_chunks
from bangla_gpt_api.nctb.normalize import normalize_bangla

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CORPUS = REPO_ROOT.parent / "data" / "nctb"

CLEAN = "নিউটনের প্রথম সূত্র অনুযায়ী গতির অবস্থা পরিবর্তনে বাহ্যিক বল প্রয়োজন।"
DECORATED = "প্রথম অধ্যায়\uf0b7নিউটনের সূত্র"  # U+F0B7 bullet residue
LEGACY = "RvZxq wk¶vµg 2012 cÖ‡ek cixÿvi Aby‡”Q`"


def _real_corpus_available() -> bool:
    normalized = REAL_CORPUS / "normalized"
    return (
        (REAL_CORPUS / "quality_report.json").exists()
        and normalized.is_dir()
        and any(normalized.glob("*.chunks.jsonl"))
    )


def _write_source(tmp_path: Path, texts: list[str]) -> tuple[Path, Path]:
    normalized = tmp_path / "normalized"
    normalized.mkdir(parents=True)
    rows = [
        {"chunk_id": f"chunk-{i}", "text": text, "page_start": i + 1}
        for i, text in enumerate(texts)
    ]
    (normalized / "synthetic-nctb.chunks.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    report = tmp_path / "quality_report.json"
    report.write_text(
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
    return normalized, report


def test_normalize_bangla_strips_private_use_glyphs() -> None:
    cleaned = normalize_bangla(DECORATED)
    assert "\uf0b7" not in cleaned
    assert cleaned == "প্রথম অধ্যায় নিউটনের সূত্র"


def test_loader_strips_pua_and_drops_legacy_bijoy_chunks(tmp_path: Path) -> None:
    normalized, report = _write_source(tmp_path, [CLEAN, DECORATED, LEGACY])

    chunks = load_nctb_corpus(normalized, report)
    served_texts = {chunk.text for chunk in chunks}

    assert CLEAN in served_texts
    assert DECORATED.replace("\uf0b7", " ") in served_texts
    assert LEGACY not in served_texts  # unreadable legacy encoding: dropped
    assert all("\uf0b7" not in text for text in served_texts)


@pytest.mark.skipif(not _real_corpus_available(), reason="real NCTB corpus not present")
def test_served_corpus_passes_content_qa_gate() -> None:
    chunks = load_nctb_corpus(REAL_CORPUS / "normalized", REAL_CORPUS / "quality_report.json")
    assert chunks, "loader returned no chunks although the corpus is present"

    report = qa_chunks([{"chunk_id": chunk.id, "text": chunk.text} for chunk in chunks])
    assert report.passed, f"served corpus fails the QA gate: {report.issues}"
    assert "pua_char" not in report.issues
    assert "legacy_bijoy" not in report.issues


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
