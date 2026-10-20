"""textbook OCR ingestion adapter.

NCTB পাঠ্যপুস্তক e-books are copyrighted. This adapter exists so that, once
written permission (or an official licensed feed) is obtained, scanned
textbook pages can be ingested through a verified pipeline. It is
deliberately gated: ingestion refuses to run unless the operator sets
``BGPT_OCR_CONFIRMED=yes``, asserting that permission/rights are settled.

A2-09 additions (both additive):

* every image is scanned by the pluggable ``services.malware_scan`` seam
  before tesseract sees it (the default scanner is the documented no-op, so
  behaviour is unchanged until an operator wires an engine);
* :func:`ocr_image_to_prompt_block` is the ONE path by which OCR-derived text
  may enter a prompt: it renders the text through the A5-04
  ``<image_text>`` delimiters (``services.safety.render_image_text_block``),
  so a hostile caption cannot close its own block, open the evidence block or
  fake the user-question wrap.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bangla_gpt_api.services.malware_scan import MalwareScanner, ScanResult


class OcrUnavailable(RuntimeError):
    pass


class OcrPermissionDenied(PermissionError):
    pass


class OcrMalwareRefused(RuntimeError):
    """The image was flagged by the configured malware scanner (A2-09)."""


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def assert_ingest_permission() -> None:
    if os.environ.get("BGPT_OCR_CONFIRMED") != "yes":
        raise OcrPermissionDenied(
            "Textbook OCR ingestion requires documented permission from the "
            "rights holder. After obtaining it, set BGPT_OCR_CONFIRMED=yes."
        )


def scan_ocr_image(image_path: str | Path, *, scanner: MalwareScanner | None = None) -> ScanResult:
    """Run the malware-scan seam over one image; raise when it is flagged.

    The scan runs BEFORE the OCR engine (a scanner exists to keep hostile
    bytes away from the parser, not after it). Returns the (clean) result so a
    caller can log which scanner ran.
    """
    from bangla_gpt_api.services.malware_scan import scan_file

    result = scan_file(image_path, scanner=scanner)
    if result.flagged:
        raise OcrMalwareRefused(
            f"image refused by {result.scanner}: {result.signature or 'flagged'}"
        )
    return result


def ocr_image_to_text(
    image_path: str | Path,
    *,
    lang: str = "ben",
    psm: str = "6",
    runner: Callable[[list[str]], None] | None = None,
    scanner: MalwareScanner | None = None,
) -> str:
    """OCR a single page image with the Tesseract binary.

    ``runner`` injects the subprocess call for tests. The real invocation is
    ``tesseract <in> <out_base> -l <lang> --psm <psm>`` producing
    ``<out_base>.txt``. ``scanner`` overrides the configured malware scanner
    (A2-09); a flagged image raises :class:`OcrMalwareRefused` before tesseract
    is invoked.
    """
    if not tesseract_available():
        raise OcrUnavailable(
            "tesseract binary not found; install tesseract-ocr plus the 'ben' "
            "language pack to enable OCR ingestion"
        )
    image = Path(image_path)
    if not image.exists():
        raise FileNotFoundError(image)
    scan_ocr_image(image, scanner=scanner)
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
            subprocess.run(command, check=True, capture_output=True)  # noqa: S603 - fixed argv with no shell, binary path is a module constant
        else:
            # Test seam: materialise the expected output file.
            out_base.with_suffix(".txt").write_text("[fixture]", encoding="utf-8")
            runner(command)
        return out_base.with_suffix(".txt").read_text(encoding="utf-8")


def ocr_image_to_prompt_block(
    image_path: str | Path,
    *,
    lang: str = "ben",
    psm: str = "6",
    runner: Callable[[list[str]], None] | None = None,
    scanner: MalwareScanner | None = None,
) -> str:
    """OCR one page image and render it as delimited, data-only prompt text.

    The ONE sanctioned entry point for OCR-derived text entering a prompt
    (A5-04/A2-09): the recognised text is wrapped in ``<image_text>``
    delimiters by ``services.safety.render_image_text_block``, which escapes
    every delimiter-shaped sequence inside it first. An empty page renders
    empty — no labels for text that does not exist.
    """
    text = ocr_image_to_text(image_path, lang=lang, psm=psm, runner=runner, scanner=scanner)
    from bangla_gpt_api.services.safety import render_image_text_block

    return render_image_text_block(text)
