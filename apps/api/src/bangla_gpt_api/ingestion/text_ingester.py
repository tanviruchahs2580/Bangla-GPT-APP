import hashlib
import re

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.services.safety import strip_injections

CHAPTER_PREFIX = "অধ্যায়:"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[।.!?])\s+")


class TextIngester:
    """Deterministic marker-based ingester for structured plain-text documents.

    Recognized markers:
      - Lines starting with 'অধ্যায়:' begin a new chapter.
      - Lines starting with '##' begin a new section.
      - Blank lines separate paragraphs (one chunk per paragraph, long ones split).
    PDF/OCR adapters remain pending until the real NCTB corpus is supplied.
    """

    def __init__(self, chunk_char_limit: int = 700) -> None:
        self.chunk_char_limit = chunk_char_limit
        # sentences removed by the ingest-time injection filter (count only).
        self.dropped_injections = 0

    def ingest(self, text: str, meta: CurriculumMeta) -> list[Chunk]:
        chunks: list[Chunk] = []
        seen: set[str] = set()
        chapter = ""
        section = ""
        buffer: list[str] = []

        def flush() -> None:
            raw = "\n".join(buffer).strip()
            buffer.clear()
            # untrusted corpus text first loses injection/leak sentences.
            paragraph, dropped = strip_injections(raw)
            self.dropped_injections += dropped
            if not paragraph:
                return
            for piece in self._split_paragraph(paragraph):
                # Content-addressed: the id folds (source, chapter, section,
                # text) and NOT a running sequence. The old seq-in-key design
                # remapped every later chunk onto other ids as soon as one
                # earlier paragraph was inserted. The seen-set makes the id
                # space additionally collision-free: a byte-identical passage
                # inside the same (chapter, section) scope is ingested once.
                digest = hashlib.sha256(
                    f"{meta.source}|{chapter}|{section}|{piece}".encode(),
                    usedforsecurity=False,
                ).hexdigest()[:16]
                if digest in seen:
                    continue
                seen.add(digest)
                chunk_meta = meta.model_copy(
                    update={"chapter": chapter, "section": section or None}
                )
                chunks.append(Chunk(id=digest, text=piece, meta=chunk_meta))

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(CHAPTER_PREFIX):
                flush()
                chapter = stripped[len(CHAPTER_PREFIX) :].strip()
                section = ""
            elif stripped.startswith("##"):
                flush()
                section = stripped.lstrip("#").strip()
            elif not stripped:
                flush()
            else:
                buffer.append(stripped)
        flush()
        return chunks

    def _split_paragraph(self, paragraph: str) -> list[str]:
        if len(paragraph) <= self.chunk_char_limit:
            return [paragraph]
        parts: list[str] = []
        current = ""
        for sentence in SENTENCE_SPLIT_RE.split(paragraph):
            if current and len(current) + len(sentence) + 1 > self.chunk_char_limit:
                parts.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            parts.append(current)
        return parts
