"""S6.2 content QA tests: check detection, gate behavior, sampling flow.

Source is kept pure ASCII: Bengali strings are built from code-point
escapes (glyph-corruption guard). The checks themselves are code-point
range based, so this matches exactly what production sees.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from bangla_gpt_api.nctb.content_qa import (
    build_review_sheet,
    qa_chunks,
    qa_text,
    summarize_review,
)

# "kosh holo jiber ekok" (cell is a unit of life) -- clean NFC Bangla.
CLEAN = "\u0995\u09cb\u09b7 \u09b9\u09b2\u09cb \u099c\u09c0\u09ac\u09c7\u09b0 \u098f\u0995\u0995."
# Correct Unicode multiplication sign -- must NOT be flagged.
GOOD_TIMES = "\u00d7"
# Mojibake form of U+00D7: UTF-8 bytes C3 97 read as two Latin-1 chars.
BAD_TIMES = "\u00c3\u0097"


def _chunk(i: int, text: str) -> dict:
    return {"chunk_id": f"c{i:04d}", "chapter": "ch", "text": text}


def test_clean_bangla_with_unicode_math_passes() -> None:
    assert qa_text(CLEAN) == []
    assert qa_text(f"{CLEAN} 2 {GOOD_TIMES} 3 = 6") == []


def test_non_nfc_flagged() -> None:
    decomposed = "e\u0301"  # e + combining acute, not in NFC form
    assert "not_nfc" in qa_text(decomposed)
    assert "not_nfc" not in qa_text("\u00e9")


def test_zero_width_flagged() -> None:
    assert "zero_width" in qa_text(CLEAN + "\u200c")  # ZWNJ
    assert "zero_width" in qa_text(CLEAN + "\ufeff")  # BOM


def test_math_mojibake_flagged_but_real_symbol_clean() -> None:
    assert "math_mojibake" in qa_text(f"4 {BAD_TIMES} 5 = 20")
    assert "math_mojibake" not in qa_text(f"4 {GOOD_TIMES} 5 = 20")


def test_replacement_and_pua_flagged() -> None:
    assert "replacement_char" in qa_text("k\ufffd")
    assert "pua_char" in qa_text("\ue000" + CLEAN)


def test_legacy_bijoy_flagged() -> None:
    # Signature token for "jatiyo" used by the pipeline's Bijoy detector.
    assert "legacy_bijoy" in qa_text("RvZxq 2012")


def _corpus(n_clean: int, bad_indices: set[int]) -> list[dict]:
    chunks = []
    for i in range(n_clean + len(bad_indices)):
        if i in bad_indices:
            chunks.append(_chunk(i, CLEAN + BAD_TIMES + "\u200c"))
        else:
            chunks.append(_chunk(i, CLEAN))
    return chunks


def test_report_catches_seeded_bad_chunk() -> None:
    report = qa_chunks(_corpus(99, {42}))
    assert report.total_chunks == 100
    assert report.flagged_chunks == 1
    assert report.issues["zero_width"] == 1
    assert report.issues["math_mojibake"] == 1
    assert report.worst == [{"chunk_id": "c0042", "issues": ["math_mojibake", "zero_width"]}]
    assert report.passed is True  # 1% <= 2% threshold: corpus still indexable


def test_report_gate_blocks_low_quality_corpus() -> None:
    report = qa_chunks(_corpus(90, set(range(10))))
    assert report.flagged_chunks == 10
    assert report.passed is False


def test_report_empty_corpus_is_not_a_pass() -> None:
    report = qa_chunks([])
    assert report.total_chunks == 0
    assert report.passed is False


def test_sample_is_ten_percent_and_deterministic() -> None:
    corpus = [_chunk(i, CLEAN) for i in range(50)]
    first = build_review_sheet(corpus, seed=7)
    second = build_review_sheet(corpus, seed=7)
    assert len(first) == 5
    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second]
    assert all(set(r) >= {"chunk_id", "excerpt", "qa_issues", "verdict"} for r in first)


def test_sample_never_empty_when_corpus_nonempty() -> None:
    assert len(build_review_sheet([_chunk(0, CLEAN)], seed=1)) == 1


def test_review_summary_counts_only_sampled_ids() -> None:
    sheet = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]
    verdicts = [
        {"chunk_id": "a", "verdict": "accept"},
        {"chunk_id": "b", "verdict": "accept"},
        {"chunk_id": "c", "verdict": "reject"},
        {"chunk_id": "zzz-not-sampled", "verdict": "reject"},  # ignored
    ]
    out = summarize_review(sheet, verdicts)
    assert out == {
        "sampled": 3,
        "reviewed": 3,
        "pending": 0,
        "accepted": 2,
        "rejected": 1,
        "reject_ratio": 0.3333,
        "complete": True,
    }
    empty = summarize_review(sheet, [])
    assert empty["pending"] == 3
    assert empty["complete"] is False


def test_cli_report_exits_three_on_gate_failure(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "content_qa.py"
    spec = importlib.util.spec_from_file_location("content_qa_cli", str(script))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    chunks_path = tmp_path / "src.chunks.jsonl"
    rows = []
    for i, text in enumerate([CLEAN, CLEAN, CLEAN + "\u200c"]):
        rows.append(
            {
                "chunk_id": f"c{i}",
                "parent_id": None,
                "text": text,
                "original_text": text,
                "chapter": "ch",
                "page_start": 1,
                "page_end": 1,
            }
        )
    chunks_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    assert mod.main(["report", str(chunks_path), "--out", str(out)]) == 3
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["pass"] is False
    assert payload["flagged_chunks"] == 1
