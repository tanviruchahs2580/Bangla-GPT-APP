"""PDF export must shape Bengali, not just embed it (AUD-0045).

fpdf2 treats complex-script shaping as opt-in. With shaping off the PDF still
carries a correct text layer -- pypdf round-trips every Appendix C vector
after NFC -- but the rasterised glyphs are broken: ক্ষ -> কয়, জ্ঞান -> জুন্ঞেন,
with detached vowel signs. A text-extraction assertion cannot see that, so this
module pins the shaping switch itself plus an observable side effect.
"""

import pytest

from bangla_gpt_api.services import qp_pdf
from bangla_gpt_api.services.qp_pdf import render_document_pdf, render_qp_pdf

TITLE = "ক্ষমতা জ্ঞান প্রযুক্তি"

PAPER = {
    "exam_type": TITLE,
    "class_level": "৯-১০",
    "subject": "বিজ্ঞান",
    "marks": 1,
    "duration_min": 1,
    "chapters": ["কোষ বিভাজন"],
    "questions": [
        {"text": TITLE, "marks": 1, "options": ["ক", "খ"], "answer_index": 0},
    ],
}

DOC = {
    "kind": "worksheet",
    "title": TITLE,
    "class_level": "৯-১০",
    "subject": "বিজ্ঞান",
    "chapter": "কোষ বিভাজন",
    "payload": {"tiers": [{"name": "সহজ", "items": ["১. " + TITLE]}]},
}


@pytest.fixture
def shaping_calls(monkeypatch):
    """Record every set_text_shaping call made while rendering."""
    calls: list[bool] = []
    original = qp_pdf.FPDF.set_text_shaping

    def recorder(self, shaping):  # noqa: ANN001 - mirrors fpdf2 signature
        calls.append(shaping)
        return original(self, shaping)

    monkeypatch.setattr(qp_pdf.FPDF, "set_text_shaping", recorder)
    return calls


def test_render_qp_pdf_enables_text_shaping(shaping_calls):
    assert qp_pdf.font_available(), "bundled Bengali font missing"
    render_qp_pdf(PAPER, kind="paper")
    assert shaping_calls == [True], f"render_qp_pdf must enable shaping, got {shaping_calls}"


def test_render_document_pdf_enables_text_shaping(shaping_calls):
    assert qp_pdf.font_available(), "bundled Bengali font missing"
    render_document_pdf(DOC)
    assert shaping_calls == [True], f"render_document_pdf must enable shaping, got {shaping_calls}"


def test_shaping_actually_changes_the_output(monkeypatch):
    """Guard against a no-op: forcing shaping off must yield different bytes.

    If this ever fails, fpdf2 dropped or renamed the shaping switch and the two
    assertions above would be asserting a call that does nothing.
    """
    monkeypatch.setattr(qp_pdf.FPDF, "set_text_shaping", lambda self, shaping: None)
    unshaped = render_qp_pdf(PAPER, kind="paper")
    monkeypatch.undo()
    shaped = render_qp_pdf(PAPER, kind="paper")
    assert unshaped != shaped, "set_text_shaping had no effect on the rendered PDF"


def test_answer_key_also_shaped(shaping_calls):
    render_qp_pdf(PAPER, kind="answer")
    assert shaping_calls == [True]
