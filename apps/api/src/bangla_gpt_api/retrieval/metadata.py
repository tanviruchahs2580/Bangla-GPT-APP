"""One metadata-filter implementation for every retrieval lane.

The lanes used to each hand-roll the same five `if ... != ...: continue`
chain (class, subject, chapter, book, year). Beyond the duplication, the
chain pushed ``BM25Index.search`` past the complexity ratchet's ceiling
(radon: 23 > 20, CI guardrails, 2026-11-13). The predicate lives here so a
new filter dimension is one function, not one edit per lane.
"""

from __future__ import annotations

from bangla_gpt_api.curriculum.models import CurriculumMeta


def matches_metadata(
    meta: CurriculumMeta,
    *,
    class_level: int | None = None,
    subject: str | None = None,
    chapter: str | None = None,
    book: str | None = None,
    year: int | None = None,
) -> bool:
    """True when the chunk's metadata satisfies every requested filter."""
    mismatches = (
        (class_level is not None and meta.class_level != class_level)
        or (subject is not None and meta.subject != subject)
        or (chapter is not None and meta.chapter != chapter)
        or (book is not None and meta.book != book)
        or (year is not None and meta.curriculum_year != year)
    )
    return not mismatches
