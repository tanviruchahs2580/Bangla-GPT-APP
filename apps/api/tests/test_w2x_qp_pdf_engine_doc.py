"""F-166: the qp_pdf contract names the engine that actually renders.

The module docstring claimed a WeasyPrint primary with an fpdf2 fallback, and
no WeasyPrint code ever existed -- a maintainer looking for the fallback path
found nothing. The docstring must name fpdf2 as the engine and must not claim
another one.
"""

from __future__ import annotations

from bangla_gpt_api.services import qp_pdf

_DOC = qp_pdf.__doc__ or ""


def test_the_docstring_does_not_claim_a_weasyprint_engine() -> None:
    assert "primary engine is weasyprint" not in _DOC.lower()


def test_the_docstring_names_fpdf2_as_the_engine() -> None:
    assert "fpdf2" in _DOC
