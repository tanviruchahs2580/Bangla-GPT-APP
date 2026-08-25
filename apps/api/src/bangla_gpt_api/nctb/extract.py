"""PDF text extraction with per-page provenance and honest quality QC.

Uses pypdf (pure Python). NCTB Bangla PDFs frequently use custom CID
fonts; when text comes out unusable the QC report flags pages as
suspicious instead of silently indexing garbage (master §11/§75).
OCR is an explicitly separate future adapter — never faked here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bangla_gpt_api.nctb.bijoy import convert_bijoy_text, is_likely_legacy_bijoy
from bangla_gpt_api.nctb.normalize import bangla_char_ratio, looks_like_garbage


@dataclass
class PageText:
    page_number: int  # 1-based physical page
    text: str
    encoding: str = "unicode"  # unicode | bijoy-converted | unusable

    @property
    def usable(self) -> bool:
        return bool(self.text.strip()) and not looks_like_garbage(self.text)


@dataclass
class ExtractionResult:
    source_id: str
    pages: list[PageText] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def extract_pdf(path: Path, *, max_pages: int | None = None) -> ExtractionResult:
    """Extract page texts; legacy Bijoy pages are converted to Unicode.

    A hard failure yields error=... (never raises). Pages whose text is not
    detectably Bijoy and carries no Bangla are kept but flagged 'unusable'
    via the QC layer — nothing corrupt is silently indexed.
    """
    from pypdf import PdfReader  # imported lazily so tests can stub it

    result = ExtractionResult(source_id=path.stem)
    try:
        reader = PdfReader(str(path))
        total = len(reader.pages)
        limit = total if max_pages is None else min(total, max_pages)
        for index in range(limit):
            try:
                raw = reader.pages[index].extract_text() or ""
            except Exception:  # noqa: BLE001 - per-page robustness
                raw = ""
            encoding = "unusable"
            if raw.strip():
                if is_likely_legacy_bijoy(raw):
                    try:
                        raw = convert_bijoy_text(raw)
                        encoding = "bijoy-converted"
                    except Exception:  # noqa: BLE001 - one bad page never kills a book
                        encoding = "unusable"
                elif bangla_char_ratio(raw) > 0.2:
                    encoding = "unicode"
            result.pages.append(PageText(page_number=index + 1, text=raw, encoding=encoding))
    except Exception as exc:  # noqa: BLE001 - corrupt PDF must not crash pipeline
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def qc_pages(pages: list[PageText]) -> dict:
    """Quality-control metrics over extracted pages (master §46)."""
    total = len(pages)
    empty = sum(1 for p in pages if not p.text.strip())
    garbage = sum(1 for p in pages if p.text.strip() and looks_like_garbage(p.text))
    usable_pages = [p for p in pages if p.usable]
    all_text = "\n".join(p.text for p in usable_pages)
    encodings: dict[str, int] = {}
    for page in pages:
        encodings[page.encoding] = encodings.get(page.encoding, 0) + 1
    return {
        "total_pages": total,
        "empty_pages": empty,
        "garbage_pages": garbage,
        "usable_pages": len(usable_pages),
        "usable_ratio": round(len(usable_pages) / total, 4) if total else 0.0,
        "bangla_char_ratio_on_usable": round(bangla_char_ratio(all_text), 4),
        "total_chars_on_usable": len(all_text),
        "page_encodings": encodings,
    }
