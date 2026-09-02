"""Read-only Learn catalog service.

Builds a subject → chapter → section tree from the *actual loaded corpus*
(sample NCTB corpus or the real corpus when configured). Content here is the
real, grounded text used by the tutor index — nothing is hallucinated.

The frontend Learn flow (Subjects → Chapter → Concept) is backed entirely by
these endpoints so the UI always reflects content the tutor can actually cite.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import BaseModel

from bangla_gpt_api.data.loader import SAMPLE_DIR, SAMPLE_MANIFEST

if TYPE_CHECKING:
    from bangla_gpt_api.curriculum.models import CurriculumMeta

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


def canonical_subject(subject: str | None) -> str | None:
    if not subject:
        return None
    key = subject.strip().lower()
    return _SUBJECT_ALIASES.get(key)


@lru_cache(maxsize=1)
def _loaded() -> list[tuple[CurriculumMeta, str]]:
    """[(meta, raw_markdown)] for every sample corpus file."""
    from bangla_gpt_api.curriculum.models import CurriculumMeta

    out: list[tuple[CurriculumMeta, str]] = []
    for filename, fields in SAMPLE_MANIFEST.items():
        meta = CurriculumMeta(
            curriculum_year=fields["curriculum_year"],
            class_level=fields["class_level"],
            subject=fields["subject"],
            book=fields["book"],
            source=filename,
        )
        text = (SAMPLE_DIR / filename).read_text(encoding="utf-8")
        out.append((meta, text))
    return out


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


def list_subjects(class_level: int | None = None) -> list[SubjectOut]:
    by_subject: dict[str, dict] = {}
    for meta, _ in _loaded():
        if class_level is not None and meta.class_level != class_level:
            continue
        entry = by_subject.setdefault(
            meta.subject,
            {"subject": meta.subject, "book": meta.book, "class_levels": set()},
        )
        entry["class_levels"].add(meta.class_level)
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


def subject_chapters(subject: str, class_level: int | None = None) -> list[ChapterSummaryOut]:
    canon = canonical_subject(subject)
    if canon is None:
        return []
    out: list[ChapterSummaryOut] = []
    seen: set[str] = set()
    for meta, text in _loaded():
        if meta.subject != canon:
            continue
        if class_level is not None and meta.class_level != class_level:
            continue
        for chapter in _parse(text):
            if chapter["chapter"] in seen:
                continue
            seen.add(chapter["chapter"])
            excerpt = ""
            for sec in chapter["sections"]:
                if sec["text"]:
                    excerpt = sec["text"][:180]
                    break
            out.append(
                ChapterSummaryOut(
                    chapter=chapter["chapter"],
                    excerpt=excerpt,
                    section_count=len(chapter["sections"]),
                )
            )
    return out


def chapter_content(
    subject: str, class_level: int | None, chapter: str
) -> ChapterContentOut | None:
    canon = canonical_subject(subject)
    if canon is None:
        return None
    for meta, text in _loaded():
        if meta.subject != canon:
            continue
        if class_level is not None and meta.class_level != class_level:
            continue
        for parsed in _parse(text):
            if parsed["chapter"] == chapter:
                return ChapterContentOut(
                    subject=canon,
                    class_level=meta.class_level,
                    book=meta.book,
                    chapter=chapter,
                    sections=[
                        SectionOut(section=s["section"], text=s["text"]) for s in parsed["sections"]
                    ],
                )
    return None
