"""B18 — textbook OCR ingestion adapter.

NCTB পাঠ্যপুস্তক e-books are copyrighted. This adapter exists so that, once
written permission (or an official licensed feed) is obtained, scanned
textbook pages can be ingested through a verified pipeline. It is
deliberately gated: ingestion refuses to run unless the operator sets
``BGPT_OCR_CONFIRMED=yes``, asserting that permission/rights are settled.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path


class OcrUnavailable(RuntimeError):
    pass


class OcrPermissionDenied(PermissionError):
    pass


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def assert_ingest_permission() -> None:
    if os.environ.get("BGPT_OCR_CONFIRMED") != "yes":
        raise OcrPermissionDenied(
            "Textbook OCR ingestion requires documented permission from the "
            "rights holder. After obtaining it, set BGPT_OCR_CONFIRMED=yes."
        )


def ocr_image_to_text(
    image_path: str | Path,
    *,
    lang: str = "ben",
    psm: str = "6",
    runner: Callable[[list[str]], None] | None = None,
) -> str:
    """OCR a single page image with the Tesseract binary.

    ``runner`` injects the subprocess call for tests. The real invocation is
    ``tesseract <in> <out_base> -l <lang> --psm <psm>`` producing
    ``<out_base>.txt``.
    """
    if not tesseract_available():
        raise OcrUnavailable(
            "tesseract binary not found; install tesseract-ocr plus the 'ben' "
            "language pack to enable OCR ingestion"
        )
    image = Path(image_path)
    if not image.exists():
        raise FileNotFoundError(image)
    with tempfile.TemporaryDirectory() as tmp:
        out_base = Path(tmp) / "page"
        command = [
            "tesseract",
            str(image),
            str(out_base),
            "-l",
            lang,
            "--psm",
            psm,
        ]
        if runner is None:
            subprocess.run(command, check=True, capture_output=True)
        else:
            # Test seam: materialise the expected output file.
            out_base.with_suffix(".txt").write_text("[fixture]", encoding="utf-8")
            runner(command)
        return out_base.with_suffix(".txt").read_text(encoding="utf-8")


def ingest_pdf_via_ocr(
    pdf_path: str | Path,
    render_pages: Callable[[Path, int], list[Path]],
    *,
    lang: str = "ben",
    dpi: int = 200,
) -> list[str]:
    """OCR every rendered page of a PDF.

    ``render_pages(pdf_path, dpi)`` must return page-image paths; wiring a
    concrete renderer (pdf2image/poppler or pdfium) stays an explicit,
    documented step because rendering tooling differs per platform.
    """
    assert_ingest_permission()
    pdf = Path(pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    pages: list[str] = []
    for image in render_pages(pdf, dpi):
        text = ocr_image_to_text(image, lang=lang)
        pages.append(text)
    return pages
