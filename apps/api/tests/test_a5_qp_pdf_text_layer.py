"""G-24: the question-paper PDF text layer, measured (wave-5 probe).

The wave-4 work fixed the literal ``None`` render and documented the
copy/paste limitation as a "MuPDF rendering property". The wave-5 probe (two
extractors, one generated paper) shows both halves of that record need
correcting:

* the ``None`` fix still holds — the answer-key PDF and its HTML fallback
  contain no literal ``None``;
* the text-layer defect is NOT an extractor property: pypdf and pypdfium2
  (PDFium) read the SAME wrong code points, so the corruption is written into
  the PDF by fpdf2 2.8.9 itself — a shaped run's glyph→Unicode map desyncs on
  Bangla cluster reordering, injecting control characters inside words
  (বিজ্ঞান -> "বি\\x02জ্ঞান"). With shaping off the text layer is exact but
  the visual output decomposes every conjunct (AUD-0045), so the two cannot be
  had together in this fpdf2 version.

These tests pin the properties that MUST hold (no literal None, shaping
stays on) and record the engine limit as a non-strict xfail: if a future
fpdf2 upgrade fixes the shaped-run ToUnicode map, the xfail turns into an
XPASS and the docstring note in ``services/qp_pdf.py`` gets revisited.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from bangla_gpt_api.services.qp_pdf import render_document_pdf, render_qp_pdf

PAPER = {
    "exam_type": "মডেল পরীক্ষা",
    "class_level": 6,
    "subject": "বিজ্ঞান",
    "marks": 50,
    "duration_min": 90,
    "chapters": ["প্রথম অধ্যায়"],
    "questions": [
        {
            "text": "নিচের কোনটি বিজ্ঞান?",
            "marks": 1,
            "options": ["ক্ষ", "জ্ঞান", "কার্যক্রম", "পুস্তক"],
            "answer_index": 1,
        }
    ],
}
DOCUMENT = {
    "kind": "answer_key",
    "title": "উত্তরপত্র",
    "class_level": 6,
    "subject": "বিজ্ঞান",
    "chapter": "প্রথম অধ্যায়",
    "payload": {
        "answers": [{"ref": "১", "marks": 1, "answer": "খ) জ্ঞান", "detailed_solution": None}],
        "marking_guide": {"total_marks": 3, "per_mark_note": None},
    },
}


def _extract(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_answer_key_never_renders_the_literal_none() -> None:
    """The wave-4 G-24 fix (absent optional fields render blank) still holds."""
    text = _extract(render_document_pdf(DOCUMENT))
    assert "None" not in text


def test_the_text_layer_keeps_the_words_that_need_no_reordering() -> None:
    """Text is not uniformly broken: runs without pre-base vowel reordering or
    conjunct ligation round-trip exactly (পরীক্ষা, the option labels, the
    answer text). The reordered cases are the xfail above."""
    text = _extract(render_qp_pdf(PAPER))
    assert "পরীক্ষা" in text
    assert "a) ক্ষ" in text
    assert "b) জ্ঞান" in text


@pytest.mark.xfail(
    reason=(
        "G-24 engine limit: fpdf2 2.8.9 builds the shaped-run glyph->Unicode map "
        "from harfbuzz clusters and loses the mapping for reordered Bangla "
        "clusters, injecting control characters into the text layer "
        "(বিজ্ঞান -> 'বি\\x02জ্ঞান'). Both pypdf and pypdfium2 read the same "
        "bytes, so it is written into the PDF, not an extractor artefact. "
        "Shaping is required for correct visuals (AUD-0045); with it off the "
        "text layer is exact but every conjunct decomposes."
    ),
    strict=False,
)
def test_the_bangla_text_layer_round_trips_exactly() -> None:
    text = _extract(render_qp_pdf(PAPER))
    assert "বিজ্ঞান" in text, "the shaped cluster lost its Unicode mapping"


def test_shaping_stays_on_so_the_visual_output_is_correct() -> None:
    """A regression guard for the limit above: the fix for the text layer must
    never be 'turn shaping off' (that would re-open AUD-0045)."""
    pdf_bytes = render_qp_pdf(PAPER)
    text = _extract(pdf_bytes)
    # with shaping on, the clustered word carries the desync signature; with
    # shaping off it would be exact ("বিজ্ঞান") and this test would fail —
    # read it as: the visual-correctness path is the one in use.
    assert "বিজ্ঞান" not in text or "\x02" in text
