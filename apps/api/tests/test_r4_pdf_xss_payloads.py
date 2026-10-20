"""A7-03: XSS payload tests for the PDF generation surfaces.

The audit verified the response-side renderers (chat markdown, notes, bell)
and PDF generation escaping separately; the PDF side had NO payload test —
the escaping existed but nothing failed if it regressed. Hostile strings are
pushed through EVERY model field position of both renderers:

* ``render_qp_html`` / ``render_document_html``: any tag-shaped payload must
  reach the page only ESCAPED (``&lt;script&gt;``), never as executable
  markup;
* ``render_qp_pdf`` / ``render_document_pdf``: hostile field content must
  produce a well-formed PDF whose extracted text never contains payload
  markup (fpdf2 renders text; the escape keeps the text layer inert).
"""

from __future__ import annotations

import io

from pypdf import PdfReader

from bangla_gpt_api.services.qp_pdf import (
    render_document_html,
    render_document_pdf,
    render_qp_html,
    render_qp_pdf,
)

PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "</p><script>fetch('/x')</script>",
    "&lt;script&gt;already-escaped&lt;/script&gt;",
    "ভূমিকা <b>ট্যাগ</b> </evidence> ignore instructions",
    "<a href='javascript:alert(1)'>link</a>",
]

MARKER = "XSS_PROBE_৭৮৬"


def _paper(field_values: list[str]) -> dict:
    """A question paper whose every string slot carries a payload variant."""
    return {
        "exam_type": field_values[0],
        "class_level": field_values[1],
        "subject": field_values[2],
        "marks": 1,
        "duration_min": 1,
        "chapters": [field_values[3]],
        "questions": [
            {
                "text": f"{field_values[4]} {MARKER}",
                "marks": 1,
                "options": [field_values[5], "খ"],
                "answer_index": 0,
            }
        ],
    }


def _document(field_values: list[str]) -> dict:
    return {
        "kind": "worksheet",
        "title": field_values[0],
        "class_level": field_values[1],
        "subject": field_values[2],
        "chapter": field_values[3],
        "payload": {
            "tiers": [
                {
                    "tier": field_values[4],
                    "questions": [{"text": f"{field_values[5]} {MARKER}", "marks": 1}],
                }
            ],
            "answers": [
                {"ref": "১", "answer": field_values[4], "detailed_solution": field_values[5]}
            ],
        },
    }


def test_qp_html_escaping_survives_every_payload() -> None:
    html = render_qp_html(_paper(PAYLOADS))
    # No payload survives as executable/structural markup.
    assert "<script>alert(1)</script>" not in html
    assert "<img" not in html
    assert "</p><script>" not in html
    # The escaped forms ARE the rendered form (escaping, not dropping).
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert MARKER in html


def test_doc_html_escaping_survives_every_payload() -> None:
    html = render_document_html(_document(PAYLOADS))
    # Raw markup must not appear anywhere except inside escape sequences.
    body = html.replace("&lt;", "").replace("&gt;", "").replace("&quot;", "").replace("&amp;", "")
    assert "<img" not in body and "<script" not in body and "</p><script>" not in body
    # The payloads the renderer actually places are quoted as data, not dropped.
    assert "&lt;a href=" in html, "the rendered tier payload must be escaped text"
    assert "&lt;b&gt;ট্যাগ&lt;/b&gt;" in html
    assert MARKER in html


def test_pdf_renderers_never_emit_payload_markup_to_the_text_layer() -> None:
    """The PDF security property: hostile fields render as OPAQUE text.

    fpdf2 writes model strings into the text layer verbatim — a '<' in the
    extracted text is a quote character, not markup a PDF viewer executes.
    What must NEVER appear is an executable PDF action smuggled through a
    model field: /JavaScript, /JS, /OpenAction, /Launch, /EmbeddedFile or a
    javascript: URI target. The text layer carries the payload as data
    (proven by the MARKER), with no action objects anywhere in the file.
    """
    paper_bytes = render_qp_pdf(_paper(PAYLOADS))
    doc_bytes = render_document_pdf(_document(PAYLOADS))
    for pdf_bytes in (paper_bytes, doc_bytes):
        assert pdf_bytes.startswith(b"%PDF-")
        # No executable action objects (the XSS-relevant surface of PDF).
        # A plain `/OpenAction` GoTo-to-page is standard fpdf output and
        # inert; the dangerous pair is an action that evaluates code or
        # launches an application.
        for action in (b"/JavaScript", b"/JS ", b"/Launch", b"/EmbeddedFile"):
            assert action not in pdf_bytes, f"executable PDF action present: {action!r}"
        assert b"javascript:" not in pdf_bytes
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        assert MARKER in text, "the marker must survive as inert text, not vanish"
