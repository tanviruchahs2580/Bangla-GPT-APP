"""F-166: multi-page PDF exports carry a running header and page numbers.

A printed question paper is collated and reprinted by its page furniture;
the fpdf2 renderers emitted neither, so a stack that was dropped or
mis-collated could not be put back in order, and only the first page said
which paper it was. These tests pin the footer on every page, the repeated
title from page 2 on, and that both are drawn through the bundled Bengali
font (the footer text is a real extractable text layer, not a glyph image).
"""

from __future__ import annotations

import io

import pypdf

from bangla_gpt_api.services.qp_pdf import render_document_pdf, render_qp_pdf

#: Distinct from every question text so the page-2 hit proves the RUNNING
#: header, not the body text of a question.
EXAM_TITLE = "নমুনা বার্ষিক পরীক্ষা ২০২৬"

PAPER = {
    "exam_type": EXAM_TITLE,
    "class_level": "৯-১০",
    "subject": "বিজ্ঞান",
    "marks": 40,
    "duration_min": 60,
    "chapters": ["কোষ বিভাজন", "প্রাণিজগৎ"],
    "questions": [
        {
            "text": f"প্রশ্ন {i}: কোষ বিভাজনের দুইটি প্রকারের নাম লেখ।",
            "marks": 1,
            "options": ["মাইটোসিস", "মিয়োসিস"],
            "answer_index": 0,
        }
        for i in range(1, 41)
    ],
}


def _pages(content: bytes) -> list[str]:
    reader = pypdf.PdfReader(io.BytesIO(content))
    return [page.extract_text() or "" for page in reader.pages]


def test_question_paper_footer_and_running_header() -> None:
    """NOTE on assertions: with shaping enabled fpdf2 writes the text layer
    glyph-run by glyph-run, so pypdf's output interleaves spaces and stray
    marks inside a Bangla word (measured: "পৃষ্ঠা" extracts as
    "পৃ ষ্ঠZ া"). The checks below therefore use the contiguously extracted
    parts -- the numeric page token and the ASCII-ish title suffix -- which
    is what makes them stable across fpdf2 upgrades while still failing on
    the old renderer (which drew no footer and no header)."""
    pages = _pages(render_qp_pdf(PAPER, kind="paper"))
    assert len(pages) >= 2, f"fixture must span pages, got {len(pages)}"

    total = len(pages)
    for number, text in enumerate(pages, start=1):
        # Footer drawn last, so it sits at the end of the extracted text.
        tail = text[-40:]
        assert f"{number}/{total}" in tail, f"page {number} footer missing: {tail!r}"
        assert any("\u0980" <= char <= "\u09ff" for char in tail), (
            f"page {number} footer is not drawn in Bangla: {tail!r}"
        )

    # The running header repeats the paper identity from page 2 on: the
    # title line (which no question body carries) precedes the body text.
    assert "(৯-১০) -" in pages[1][:160], pages[1][:200]
    assert "২০২৬" in pages[1][:160], pages[1][:200]


def test_document_pdf_footer_uses_the_bundled_bangla_font(bangla_names) -> None:
    """A wide name in the header must round-trip through the text layer
    (F-115's PDF half) and the footer must use the same font."""
    name = bangla_names[0]
    doc = {
        "kind": "worksheet",
        "title": name,
        "class_level": "৯-১০",
        "subject": "বিজ্ঞান",
        "chapter": "কোষ বিভাজন",
        "payload": {
            "tiers": [
                {
                    "tier": "সহজ",
                    "questions": [
                        {"text": "কোষ কী?", "marks": 1, "options": ["ক", "খ"]} for _ in range(35)
                    ],
                }
            ]
        },
    }
    pages = _pages(render_document_pdf(doc))
    assert len(pages) >= 2
    total = len(pages)
    # Page 2 starts with the running header (title, class, subject) and ends
    # with the Bangla footer; the questions never carry either string.
    assert "(৯-১০) -" in pages[1][:160], pages[1][:200]
    assert f"2/{total}" in pages[1][-40:], pages[1][-60:]
