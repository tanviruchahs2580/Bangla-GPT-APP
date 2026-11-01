"""F-049 / RAG-06: class attribution is derived from a real signal, never invented.

Class detection returned None for every source of the corpus on disk, so the
loader silently spread each source across its whole declared level range
(5x expansion: 423 chunks per secondary class) and per-class metadata was
fabrication. The fix:

* ``detect_class_levels`` reads the book-level class statement from the
  cover/title page, including the RANGE forms real NCTB books print
  ("একাদশ ও দ্বাদশ শ্রেণি") that the old single-class detector rejected as
  ambiguous — the real signal present on every HSC cover;
* the loader resolves classes in the documented ladder (cover statement ->
  declared level range -> refuse) and only the explicit
  ``multi_class_fallback`` flag allows the level-range attribution;
* a source with no class signal at all is refused with a warning.

The real-corpus leg (skipped when the untracked corpus is absent) pins the
measured cover statements of the nine books.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from bangla_gpt_api.data.nctb_loader import (
    COVER_PAGES,
    attach_detected_classes,
    detect_source_classes,
    load_nctb_corpus,
    resolve_class_targets,
)
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.normalize import detect_class_level, detect_class_levels

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CORPUS = REPO_ROOT.parent / "data" / "nctb"
REAL_CORPUS_AVAILABLE = (REAL_CORPUS / "quality_report.json").exists() and any(
    (REAL_CORPUS / "extracted").glob("*.pages.json")
)

#: Cover lines measured on the corpus on disk (extracted page 1 of each HSC
#: book): all four declare classes 11 AND 12, which the old detector saw as
#: "ambiguous" and turned into None.
HSC_COVERS = {
    "nctb-hsc-28d03c592c2c": "জাতীয় শিক্ষাক্রম ২০১২ পদার্থবিদ্যা একাদশ ও দ্বাদশ শ্রেণি",
    "nctb-hsc-9c44bb8ff649": "জাতীয় শিক্ষাক্রম ২০১২ উচ্চতর গণিত একাদশ-দ্বাদশ শ্রেণি",
    "nctb-hsc-a513203336f6": "জাতীয় শিক্ষাক্রম ২০১২ রসায়ন একাদশ ও দ্বাদশ শ্রেণি",
    "nctb-hsc-ca39e5957513": "জাতীয় শিক্ষাক্রম ২০১২ জীববিজ্ঞান একাদশ ও দ্বাদশ শ্রেণি",
}

#: Front-matter policy prose that is NOT a statement about the book (page 4 of
#: the secondary curriculum documents). Reading this as book metadata would
#: fabricate classes 6-12 for every secondary source.
POLICY_PROSE = (
    "শিক্ষাক্রম উন্নয়ন প্রক্রিয়ার বিভিন্ন ধাপ অনুসরণ করে ষষ্ঠ থেকে অষ্টম শ্রেণির ১৭টি "
    "এবং নবম ও দশম শ্রেণির ২৭টি বিষয়ের শিক্ষাক্রম উন্নয়ন করা হয়েছে। ৬.১ ষষ্ঠ-দ্বাদশ "
    "শ্রেণির শিক্ষার লক্ষ্য ও উদ্দেশ্য নির্ধারণ করা হয়েছে।"
)


def test_range_cover_statement_is_detected() -> None:
    assert detect_class_levels(HSC_COVERS["nctb-hsc-28d03c592c2c"]) == (11, 12)
    assert detect_class_levels(HSC_COVERS["nctb-hsc-9c44bb8ff649"]) == (11, 12)
    assert detect_class_levels("নবম-দশম শ্রেণি গণিত") == (9, 10)
    assert detect_class_levels("ষষ্ঠ থেকে অষ্টম শ্রেণি বিজ্ঞান") == (6, 7, 8)
    assert detect_class_levels("দশম শ্রেণি") == (10,)


def test_old_single_class_detector_misreads_the_range_cover() -> None:
    """The failing side of the regression, measured on the real cover string.

    The old detector looked for "<ordinal> শ্রেণি" substrings, so the cover
    line "একাদশ ও দ্বাদশ শ্রেণি" yielded a single, WRONG class (12 — it only
    saw দ্বাদশ শ্রেণি). Over a 12-page window the other front-matter mentions
    made it ambiguous instead, which is how every source ended up UNDETECTED
    and the loader expanded all of them to the whole level range.
    """
    cover = HSC_COVERS["nctb-hsc-28d03c592c2c"]
    assert detect_class_level(cover) == 12  # wrong: the book covers 11 and 12
    assert detect_class_levels(cover) == (11, 12)
    # the 12-page window the old caller used mixes in policy mentions -> None
    assert detect_class_level(f"দ্বাদশ শ্রেণি {POLICY_PROSE}") is None


def test_policy_prose_is_not_a_book_level_statement() -> None:
    """Prose parses to a policy range; the loader only reads the cover pages."""
    payload = {
        "source_id": "src1",
        "pages": [
            {"page_number": 1, "text": " "},
            {"page_number": 2, "text": "জাতীয় শিক্ষাক্রম ২০১২ র"},
            {"page_number": 3, "text": POLICY_PROSE},
        ],
    }
    # the parser CAN read the prose range (a caller must not feed it) ...
    assert detect_class_levels(POLICY_PROSE) == (6, 7, 8)
    # ... and two SEPARATE class statements are not a book-level statement
    assert detect_class_levels("ষষ্ঠ শ্রেণি ও সপ্তম শ্রেণি") == ()
    # ... but the loader reads only the cover pages (COVER_PAGES) and detects none.
    assert COVER_PAGES == 2
    assert detect_source_classes(payload) == ()


def test_resolve_class_targets_ladder() -> None:
    assert resolve_class_targets("hsc", (11, 12), multi_class_fallback=False) == (
        [11, 12],
        "detected",
    )
    assert resolve_class_targets("secondary", None, multi_class_fallback=True) == (
        [6, 7, 8, 9, 10],
        "level-range",
    )
    assert resolve_class_targets("secondary", None, multi_class_fallback=False) == ([], "refused")


def test_detected_classes_outside_the_level_range_are_refused() -> None:
    """A disagreement between signals is a refusal, never a silent clip."""
    assert resolve_class_targets("secondary", (11, 12), multi_class_fallback=True) == (
        [],
        "refused",
    )


def _write_corpus(
    tmp_path: Path, cover: str, detected_ratio: float = 0.9
) -> tuple[Path, Path, Path]:
    extracted = tmp_path / "extracted"
    normalized = tmp_path / "normalized"
    extracted.mkdir(parents=True)
    normalized.mkdir(parents=True)
    pages = [
        PageText(1, cover, "unicode"),
        PageText(2, "অধ্যায়: বল ও গতি", "unicode"),
        PageText(3, "বলের প্রভাবে গতির পরিবর্তন হয়। " * 12, "unicode"),
    ]
    (extracted / "src1.pages.json").write_text(
        json.dumps({"source_id": "src1", "pages": [asdict(p) for p in pages]}, ensure_ascii=False),
        encoding="utf-8",
    )
    chunks = chunk_pages(pages, source_id="src1")
    with (normalized / "src1.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    report = tmp_path / "quality_report.json"
    report.write_text(
        json.dumps(
            {
                "src1": {
                    "level": "secondary",
                    "subject_bn": "পদার্থবিদ্যা",
                    "curriculum_year": "2012",
                    "bangla_char_ratio_on_usable": detected_ratio,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return extracted, normalized, report


def test_cover_statement_decides_the_indexed_classes(tmp_path: Path) -> None:
    """HSC-shaped cover at load time -> exactly classes 11 and 12, no expansion."""
    extracted, normalized, report = _write_corpus(tmp_path, HSC_COVERS["nctb-hsc-ca39e5957513"])
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["src1"]["level"] = "hsc"
    report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    chunks = load_nctb_corpus(normalized, report, multi_class_fallback=True)
    assert chunks
    assert {c.meta.class_level for c in chunks} == {11, 12}


def test_no_class_signal_is_refused_not_expanded(tmp_path: Path) -> None:
    """A source with neither a cover statement nor the opt-in is not indexed."""
    extracted, normalized, report = _write_corpus(tmp_path, " ")  # broken/empty cover
    assert load_nctb_corpus(normalized, report, multi_class_fallback=False) == []


def test_level_range_attribution_requires_the_explicit_flag(tmp_path: Path) -> None:
    extracted, normalized, report = _write_corpus(tmp_path, " ")
    chunks = load_nctb_corpus(normalized, report, multi_class_fallback=True)
    assert {c.meta.class_level for c in chunks} == set(range(6, 11))


def test_attach_detected_classes_stamps_both_fields(tmp_path: Path) -> None:
    extracted, normalized, report = _write_corpus(tmp_path, HSC_COVERS["nctb-hsc-a513203336f6"])
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["src1"]["level"] = "hsc"
    report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    results = attach_detected_classes(extracted, normalized)
    assert results["src1"] is None  # legacy single-class field: ambiguous, stays None
    row = json.loads((normalized / "src1.chunks.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["detected_classes"] == [11, 12]
    assert row["detected_class"] is None
    chunks = load_nctb_corpus(normalized, report, multi_class_fallback=False)
    assert {c.meta.class_level for c in chunks} == {11, 12}


@pytest.mark.skipif(not REAL_CORPUS_AVAILABLE, reason="real NCTB corpus not present")
def test_real_covers_detect_the_declared_classes() -> None:
    """Every HSC book on disk declares its classes on the cover (measured)."""
    for source_id, expected in (
        ("nctb-hsc-28d03c592c2c", (11, 12)),
        ("nctb-hsc-9c44bb8ff649", (11, 12)),
        ("nctb-hsc-a513203336f6", (11, 12)),
        ("nctb-hsc-ca39e5957513", (11, 12)),
    ):
        payload = json.loads(
            (REAL_CORPUS / "extracted" / f"{source_id}.pages.json").read_text(encoding="utf-8")
        )
        assert detect_source_classes(payload) == expected, source_id
    # The secondary curriculum documents' covers are legacy-font garbled, so
    # they stay undetected -- the loader must not invent a class for them.
    for source_id in (
        "nctb-secondary-3ce5065b7a32",
        "nctb-secondary-be50d8aff8d5",
        "nctb-secondary-ca0d6bd886b7",
        "nctb-secondary-e39c58d35764",
    ):
        payload = json.loads(
            (REAL_CORPUS / "extracted" / f"{source_id}.pages.json").read_text(encoding="utf-8")
        )
        assert detect_source_classes(payload) == (), source_id


@pytest.mark.skipif(not REAL_CORPUS_AVAILABLE, reason="real NCTB corpus not present")
def test_real_corpus_loads_the_same_scope_after_the_fix() -> None:
    """HSC sources use their detected cover classes; the total stays 2599."""
    chunks = load_nctb_corpus(
        REAL_CORPUS / "normalized",
        quality_report_path=REAL_CORPUS / "quality_report.json",
        multi_class_fallback=True,
    )
    assert chunks, "expected an indexable corpus build"
    by_source: dict[str, set[int]] = {}
    for chunk in chunks:
        by_source.setdefault(chunk.meta.source, set()).add(chunk.meta.class_level)
    for source in ("nctb-hsc-28d03c592c2c", "nctb-hsc-a513203336f6"):
        assert by_source[source] == {11, 12}, source
