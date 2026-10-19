"""Retrieval pre-filters (AUD-A1-11), in a leaf module so every lane can use
them without an import cycle (``retrieval/base.py`` imports ``bm25.Hit``).

Filter schema: ``class_level``/``subject``/``chapter`` were the only
pre-filters; ``content_type`` and ``version`` are added so callers can ask
for exercises only or for one corpus version. The two remaining metadata
fields named in the audit finding do not exist in this system by design:

* ``tenant`` — the corpus is single-tenant curriculum data with no tenant
  dimension on ``CurriculumMeta``; tenancy is enforced at the API/auth
  layer, never inside the index;
* ``visibility`` — chunk visibility is a route/role policy, not chunk
  metadata; there is no per-chunk private/public field to filter on.
"""

from __future__ import annotations

from dataclasses import dataclass

from bangla_gpt_api.curriculum.models import Chunk


@dataclass(frozen=True)
class SearchFilters:
    """Pre-query filters, applied before scoring (cheap, index-wide)."""

    class_level: int | None = None
    subject: str | None = None
    chapter: str | None = None
    content_type: str | None = None
    version: str | None = None

    def matches(self, chunk: Chunk) -> bool:
        meta = chunk.meta
        return not (
            (self.class_level is not None and meta.class_level != self.class_level)
            or (self.subject is not None and meta.subject != self.subject)
            or (self.chapter is not None and meta.chapter != self.chapter)
            or (self.content_type is not None and meta.content_type != self.content_type)
            or (self.version is not None and meta.version != self.version)
        )


def chunk_matches_filters(
    chunk: Chunk,
    *,
    class_level: int | None = None,
    subject: str | None = None,
    chapter: str | None = None,
    content_type: str | None = None,
    version: str | None = None,
) -> bool:
    """Boolean form of :class:`SearchFilters` for the lane search loops."""
    return SearchFilters(
        class_level=class_level,
        subject=subject,
        chapter=chapter,
        content_type=content_type,
        version=version,
    ).matches(chunk)


__all__ = ["SearchFilters", "chunk_matches_filters"]
