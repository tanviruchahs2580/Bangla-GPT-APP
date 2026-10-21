"""A2-04: structure metadata for the served NCTB corpus (wave-5).

Four residuals, each pinned by test:

* (a) chapter headings — the real volumes write "<ordinal> অধ্যায় [: title]"
  (with the legacy-conversion artifact "চতুথর্" for চতুর্থ), and a chapter
  REFERENCE inside a curriculum table row ("ষষ্ঠ শ্রেণি প্রথম অধ্যায় …") is not
  a heading. Before the widening, 98 of 797 raw chunks carried a chapter;
  657 were empty although the pages are full of headings;
* (b) content_type — one constant ("nctb") before, while the catalog's
  vocabulary is explanation/example/exercise/table/formula/caption;
* (c) page_end was dropped at load time, so a chunk spanning pages 12-13
  served page=12 only;
* (d) curriculum_year must come from the source's published edition (2012 for
  the secondary listing), the build year only as the documented fallback.

The tests are hermetic: synthetic pages + a synthetic quality report.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import (
    CONTENT_TYPES,
    LEGACY_CONTENT_TYPE,
    infer_content_type,
    load_nctb_corpus,
)
from bangla_gpt_api.nctb.chunking import (
    TABLE_CELL_SEPARATOR,
    chunk_pages,
)
from bangla_gpt_api.nctb.extract import PageText

BODY = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক এবং এটি প্রতিটি জীবের দেহে থাকে। " * 6
FORMULA_PAGE = (
    "শক্তির সমীকরণ ব্যবহার করে সমস্যার সমাধান করা হয় এবং একক লিখতে হয়। " * 8
    + "\n"
    + "E = mc² = 3 × 10^8 × 2.5 = 7.5 × 10^16 J\n"
    + BODY
)
TABLE_PAGE = "সারণি ১: শিক্ষাক্রম কাঠামো\nশ্রেণি    বিষয়    পিরিয়ড\nষষ্ঠ     বিজ্ঞান    ৮০\n" + BODY


def _chunk_texts(pages: list[PageText], **kwargs: object) -> list[str]:
    stats: dict = {}
    chunks = chunk_pages(pages, source_id="src-a", stats=stats, **kwargs)  # type: ignore[arg-type]
    _chunk_texts.stats = stats  # type: ignore[attr-defined]
    return [chunk.text for chunk in chunks]


def _write_source(
    tmp_path: Path,
    source_id: str,
    level: str,
    pages: list[str],
    *,
    detected_class: int | None = 6,
    **report_extra: object,
) -> None:
    normalized = tmp_path / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    chunks = chunk_pages(
        [PageText(i + 1, text) for i, text in enumerate(pages)], source_id=source_id
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
    return load_nctb_corpus(tmp_path / "normalized", tmp_path / "quality_report.json", **kwargs)  # type: ignore[arg-type]


# ── (a) chapter headings ──────────────────────────────────────────────────


def test_ordinal_chapter_headings_are_recognised_with_and_without_a_colon() -> None:
    """The shapes the real volumes use (measured on data/nctb/extracted)."""
    page = PageText(
        1,
        "প্রথম অধ্যায়: ভৌতজগত ও পরিমাপ (পিরিয়ড ১৬)\n"
        + BODY
        + "\nদ্বিতীয় অধ্যায় ভেক্টর (পিরিয়ড ১০)\n"
        + BODY,
    )
    chapters = [chunk.chapter for chunk in chunk_pages([page], source_id="s1")]
    assert "প্রথম অধ্যায়: ভৌতজগত ও পরিমাপ" in chapters
    assert "দ্বিতীয় অধ্যায়: ভেক্টর" in chapters


def test_the_documented_conjunct_artifact_in_the_ordinal_is_repaired() -> None:
    """ "চতুথর্" is the extraction artifact of চতুর্থ (docs/NCTB_DATA_PIPELINE.md
    §3); the label carries the real spelling, the title stays verbatim."""
    page = PageText(1, "চতুথর্ অধ্যায় ৪ : নিউটনিয়ান বলবিদ্যা\n" + BODY)
    chapters = [chunk.chapter for chunk in chunk_pages([page], source_id="s1")]
    assert chapters == ["চতুর্থ অধ্যায়: নিউটনিয়ান বলবিদ্যা"]


def test_a_curriculum_table_reference_is_not_a_chapter_heading() -> None:
    """Rows of the class-wise tables cite chapters as cells; the text after
    the citation is the next column, so the row must not become a label."""
    page = PageText(
        1,
        "ষষ্ঠ শ্রেণি প্রথম অধ্যায় অষ্টম শ্রেণি প্রান্ত্মিক শিখনফল প্রত্যাশা করা যায় যে, "
        "অধ্যায় শেষে শিক্ষার্থীরা বুদ্ধিবৃত্তিক ক্ষেত্রে সক্ষম হবে। " * 3,
    )
    assert all(chunk.chapter == "" for chunk in chunk_pages([page], source_id="s1"))


def test_a_prose_sentence_starting_with_a_chapter_reference_is_not_a_heading() -> None:
    page = PageText(
        1,
        "প্রথম অধ্যায় থেকে কী কী জ্ঞান, দক্ষতা ও মূল্যবোধ অর্জিত হবে তা শিক্ষক আগেই জানিয়ে দেবেন। " * 6,
    )
    assert all(chunk.chapter == "" for chunk in chunk_pages([page], source_id="s1"))


def test_the_plain_textbook_form_keeps_the_bare_title() -> None:
    """Backwards compatibility: "অধ্যায়: কোষ" labels the chunk "কোষ"."""
    page = PageText(1, "অধ্যায়: কোষ\n" + BODY)
    assert [chunk.chapter for chunk in chunk_pages([page], source_id="s1")] == ["কোষ"]


# ── (e) faithful table / formula representation ───────────────────────────


def test_a_table_row_keeps_its_cells_separate() -> None:
    """A row with column geometry survives as a pipe/TSV-ish row, never as
    one prose sentence (A2-04e)."""
    texts = _chunk_texts([PageText(1, TABLE_PAGE)])
    joined = "\n".join(texts)
    assert "শ্রেণি | বিষয় | পিরিয়ড" in joined, joined
    assert "ষষ্ঠ | বিজ্ঞান | ৮০" in joined
    assert _chunk_texts.stats["table_rows_preserved"] >= 2


def test_a_formula_stays_one_unit_with_its_spacing() -> None:
    stats: dict = {}
    chunks = chunk_pages([PageText(1, FORMULA_PAGE)], source_id="s1", stats=stats)
    text = "\n".join(chunk.text for chunk in chunks)
    assert "E = mc² = 3 × 10^8 × 2.5 = 7.5 × 10^16 J" in text
    assert stats["formula_units_preserved"] >= 1


def test_a_table_row_is_never_split_by_the_size_target() -> None:
    """A preserved row is an indivisible unit even when it exceeds the target."""
    row = "শ্রেণি    বিষয়    পিরিয়ড\n" + "\n".join(
        f"শ্রেণি{i}    বিষয়{i}    {i * 10}" for i in range(1, 12)
    )
    texts = _chunk_texts([PageText(1, row + "\n" + BODY)], target_words=20)
    row_text = [text for text in texts if TABLE_CELL_SEPARATOR in text]
    assert row_text, f"no preserved table rows in {texts}"
    for text in row_text:
        for line in text.splitlines():
            if TABLE_CELL_SEPARATOR in line:
                assert line.count(TABLE_CELL_SEPARATOR) == 2, line


# ── (b) content_type vocabulary ───────────────────────────────────────────


def test_content_type_covers_the_catalog_classes() -> None:
    assert infer_content_type("অনুশীলনী ১। কোষ কী?") == "exercise"
    assert infer_content_type("সংক্ষিপ্ত প্রশ্ন: কোষ বিভাজন ব্যাখ্যা কর") == "assessment"
    assert infer_content_type("উদাহরণ ৩: লব ও হর") == "example"
    assert infer_content_type("সারণি ১: শিক্ষাক্রম কাঠামো") == "table"
    assert infer_content_type("চিত্র ২.১: উদ্ভিদ কোষের গঠন") == "caption"
    assert infer_content_type("সমীকরণ: E = mc² = 3 × 10^8") == "formula"
    assert infer_content_type(BODY) == "explanation"
    # the English curriculum volume is prose too (Latin letters, periods)
    assert (
        infer_content_type(
            "The curriculum describes the expected learning outcomes for each class. " * 3
        )
        == "explanation"
    )
    # a formula-dominant chunk is typed even without a marker
    assert infer_content_type("3 × 10^8 + 2.5 × 10^16 = 2.5 × 10^16") == "formula"
    # a marks/weight table row is a number row, not a formula
    assert infer_content_type("3 × 10^8 + 2.5 × 10^16 = 2.5 × 10^16") != "table"
    # a preserved table row is tabular content
    assert infer_content_type("শ্রেণি | বিষয় | পিরিয়ড") == "table"
    # neither prose nor structure: the legacy label survives, documented
    assert infer_content_type("১০ ২০ ৩০") == LEGACY_CONTENT_TYPE
    # a mid-sentence mention is not a structural signature
    assert infer_content_type("এখানে একটি উদাহরণ দিয়ে ব্যাখ্যা করা হলো যাতে বোঝা যায়।") != "example"
    assert set(CONTENT_TYPES) == {
        "explanation",
        "example",
        "exercise",
        "table",
        "formula",
        "caption",
    }


def test_the_loader_emits_only_catalog_types_on_a_real_shaped_source(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "src-a",
        "secondary",
        [
            "প্রথম অধ্যায়: কোষ\n"
            + "সারণি ১: কোষের অঙ্গাণু\n"
            + "অঙ্গাণু    কাজ\n"
            + "নিউক্লিয়াস    বংশগতি নিয়ন্ত্রণ\n"
            + BODY,
            "অনুশীলনী\n১। কোষ কী? বিস্তারিত ব্যাখ্যা কর এবং চিত্রসহ বর্ণনা দাও। " * 6,
        ],
    )
    types = {chunk.meta.content_type for chunk in _load(tmp_path)}
    assert "table" in types
    assert "exercise" in types
    assert types <= set(CONTENT_TYPES) | {LEGACY_CONTENT_TYPE}


# ── (c) page_end ──────────────────────────────────────────────────────────


def test_page_end_reaches_the_served_metadata(tmp_path: Path) -> None:
    """A passage continued across a page break serves its whole page range."""
    first = BODY
    second = BODY
    chunks = chunk_pages(
        [PageText(12, first), PageText(13, second)], source_id="src-a", min_words=1
    )
    assert len(chunks) == 1, "the buffer must span the page break"
    assert chunks[0].page_start == 12 and chunks[0].page_end == 13

    _write_source(tmp_path, "src-a", "secondary", [first, second])
    served = _load(tmp_path, multi_class_fallback=False)
    assert served
    assert served[0].meta.page == 1
    assert served[0].meta.page_end == 2, "page_end must survive the loader"


def test_page_end_defaults_to_page_for_single_page_chunks(tmp_path: Path) -> None:
    _write_source(tmp_path, "src-a", "secondary", [BODY])
    served = _load(tmp_path, multi_class_fallback=False)
    assert served and served[0].meta.page_end == served[0].meta.page


# ── (d) curriculum_year per source ────────────────────────────────────────


def test_curriculum_year_comes_from_the_published_edition(tmp_path: Path) -> None:
    _write_source(tmp_path, "src-a", "secondary", [BODY], curriculum_year="2012")
    _write_source(
        tmp_path,
        "src-b",
        "hsc",
        [BODY.replace("কোষ", "পরমাণু")],
        curriculum_year="UNKNOWN",
        built_at="2026-10-05T00:00:00+00:00",
    )
    years = {chunk.meta.source: chunk.meta.curriculum_year for chunk in _load(tmp_path)}
    assert years["src-a"] == 2012, "the published edition wins over the build year"
    assert years["src-b"] == 2026, "UNKNOWN editions fall back to the build year"
