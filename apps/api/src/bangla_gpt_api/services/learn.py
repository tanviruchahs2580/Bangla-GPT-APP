"""Read-only Learn catalog service.

Builds a subject → chapter → section tree from the *actual loaded corpus*: the
same chunk list the tutor index serves (sample NCTB corpus, or the real corpus
when ``NCTB_CORPUS_DIR`` is configured). Content here is the real, grounded
text used by the tutor index — nothing is hallucinated.

The router hands in ``AppContext.index.chunks``, so the Learn flow
(Subjects → Chapter → Concept) lists exactly what the tutor can cite. Direct
callers that pass no chunks (unit tests, scripts) get the packaged sample
corpus — what an app without a configured corpus serves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import BaseModel

from bangla_gpt_api.data.loader import SAMPLE_DIR, SAMPLE_MANIFEST
from bangla_gpt_api.data.nctb_loader import SUBJECT_KEYS as _NCTB_SUBJECT_KEYS

if TYPE_CHECKING:
    from bangla_gpt_api.curriculum.models import Chunk

CHAPTER_PREFIX = "অধ্যায়:"

_SUBJECT_ALIASES: dict[str, str] = {
    "science": "science",
    "বিজ্ঞান": "science",
    "mathematics": "mathematics",
    "math": "mathematics",
    "গণিত": "mathematics",
    "bangla": "bangla",
    "বাংলা": "bangla",
    "বাংলা ব্যাকরণ": "bangla",
}

# The real corpus's subject keys (data/nctb_loader.SUBJECT_KEYS maps the
# official Bangla book titles onto them) must resolve exactly like the
# sample's do, or Learn 404s on a subject the tutor serves.
_SUBJECT_ALIASES.setdefault("general", "general")
for _book_title, _subject_key in _NCTB_SUBJECT_KEYS.items():
    _SUBJECT_ALIASES.setdefault(_book_title, _subject_key)
    _SUBJECT_ALIASES.setdefault(_subject_key, _subject_key)


# Required for fastapi JSON responses.
class SubjectOut(BaseModel):
    subject: str
    book: str
    class_levels: list[int]


class ChapterSummaryOut(BaseModel):
    chapter: str
    excerpt: str
    section_count: int


class SectionOut(BaseModel):
    section: str
    text: str


class ChapterContentOut(BaseModel):
    subject: str
    class_level: int
    book: str
    chapter: str
    sections: list[SectionOut]


@dataclass(frozen=True)
class _Section:
    section: str
    text: str


@dataclass(frozen=True)
class _ChapterDoc:
    subject: str
    class_level: int
    book: str
    chapter: str
    sections: tuple[_Section, ...]


def canonical_subject(subject: str | None) -> str | None:
    if not subject:
        return None
    key = subject.strip().lower()
    return _SUBJECT_ALIASES.get(key)


def _docs(chunks: Sequence[Chunk] | None) -> Sequence[_ChapterDoc]:
    """Catalog source: the loaded index chunks when given, else the sample."""
    if chunks is None:
        return _sample_docs()
    return _docs_from_chunks(chunks)


def _docs_from_chunks(chunks: Sequence[Chunk]) -> list[_ChapterDoc]:
    """Group index chunks into chapters, in corpus order.

    Chunks without a chapter cannot be browsed by chapter and are skipped;
    they stay tutor-served. A chunk without a section heading is labelled by
    its page (real-corpus chunks carry pages, sample chunks carry headings).
    """
    grouped: dict[tuple[str, int, str, str], list[_Section]] = {}
    for chunk in chunks:
        meta = chunk.meta
        chapter = (meta.chapter or "").strip()
        if not chapter:
            continue
        label = meta.section or (f"পৃষ্ঠা {meta.page}" if meta.page else "")
        key = (meta.subject, meta.class_level, meta.book or meta.subject, chapter)
        grouped.setdefault(key, []).append(_Section(section=label, text=chunk.text))
    return [
        _ChapterDoc(
            subject=subject,
            class_level=class_level,
            book=book,
            chapter=chapter,
            sections=tuple(sections),
        )
        for (subject, class_level, book, chapter), sections in grouped.items()
    ]


@lru_cache(maxsize=1)
def _sample_docs() -> tuple[_ChapterDoc, ...]:
    """[(chapter doc)] for every packaged sample corpus file."""
    from bangla_gpt_api.curriculum.models import CurriculumMeta

    out: list[_ChapterDoc] = []
    for filename, fields in SAMPLE_MANIFEST.items():
        meta = CurriculumMeta(
            curriculum_year=fields["curriculum_year"],
            class_level=fields["class_level"],
            subject=fields["subject"],
            book=fields["book"],
            source=filename,
        )
        text = (SAMPLE_DIR / filename).read_text(encoding="utf-8")
        for parsed in _parse(text):
            out.append(
                _ChapterDoc(
                    subject=meta.subject,
                    class_level=meta.class_level,
                    book=meta.book,
                    chapter=parsed["chapter"],
                    sections=tuple(
                        _Section(section=s["section"], text=s["text"]) for s in parsed["sections"]
                    ),
                )
            )
    return tuple(out)


def _parse(markdown: str) -> list[dict]:
    """Return [{chapter, sections:[{section, text}]}] using ingester markers."""
    book: list[dict] = []
    cur_chapter: dict | None = None
    cur_section = ""
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        buf = []
        if cur_chapter is None or not text:
            return
        cur_chapter["sections"].append({"section": cur_section, "text": text})

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(CHAPTER_PREFIX):
            flush()
            name = stripped[len(CHAPTER_PREFIX) :].strip()
            cur_chapter = {"chapter": name, "sections": []}
            book.append(cur_chapter)
            cur_section = ""
        elif stripped.startswith("#"):
            flush()
            cur_section = stripped.lstrip("#").strip()
        elif not stripped:
            flush()
        else:
            buf.append(stripped)
    flush()
    return book


def list_subjects(
    class_level: int | None = None, *, chunks: Sequence[Chunk] | None = None
) -> list[SubjectOut]:
    by_subject: dict[str, dict] = {}
    for doc in _docs(chunks):
        if class_level is not None and doc.class_level != class_level:
            continue
        entry = by_subject.setdefault(
            doc.subject,
            {"subject": doc.subject, "book": doc.book, "class_levels": set()},
        )
        entry["class_levels"].add(doc.class_level)
    out: list[SubjectOut] = []
    for entry in by_subject.values():
        out.append(
            SubjectOut(
                subject=entry["subject"],
                book=entry["book"],
                class_levels=sorted(entry["class_levels"]),
            )
        )
    return out


def subject_chapters(
    subject: str, class_level: int | None = None, *, chunks: Sequence[Chunk] | None = None
) -> list[ChapterSummaryOut]:
    canon = canonical_subject(subject)
    if canon is None:
        return []
    out: list[ChapterSummaryOut] = []
    seen: set[str] = set()
    for doc in _docs(chunks):
        if doc.subject != canon:
            continue
        if class_level is not None and doc.class_level != class_level:
            continue
        if doc.chapter in seen:
            continue
        seen.add(doc.chapter)
        excerpt = ""
        for sec in doc.sections:
            if sec.text:
                excerpt = sec.text[:180]
                break
        out.append(
            ChapterSummaryOut(
                chapter=doc.chapter,
                excerpt=excerpt,
                section_count=len(doc.sections),
            )
        )
    return out


def chapter_content(
    subject: str,
    class_level: int | None,
    chapter: str,
    *,
    chunks: Sequence[Chunk] | None = None,
) -> ChapterContentOut | None:
    canon = canonical_subject(subject)
    if canon is None:
        return None
    for doc in _docs(chunks):
        if doc.subject != canon:
            continue
        if class_level is not None and doc.class_level != class_level:
            continue
        if doc.chapter != chapter:
            continue
        return ChapterContentOut(
            subject=canon,
            class_level=doc.class_level,
            book=doc.book,
            chapter=doc.chapter,
            sections=[SectionOut(section=s.section, text=s.text) for s in doc.sections],
        )
    return None
