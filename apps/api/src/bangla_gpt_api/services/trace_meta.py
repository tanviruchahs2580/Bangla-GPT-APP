"""Derived identities for observability records (A5-02 / I-03).

The tutor's trace records name the prompt and the corpus build that produced
an answer. Both identities are derived from content rather than maintained by
hand, so they can never drift from what actually ran.
"""

from __future__ import annotations

import hashlib

__all__ = ["index_fingerprint"]


def index_fingerprint(index: object) -> str:
    """A stable identity for a loaded corpus index.

    ``class:chunk_count:sha256(chunk ids)[:12]`` -- enough to tell two corpus
    builds apart in a trace record and to answer "which corpus produced this
    answer" during an incident, without hashing the chunk *text* (the ids are
    derived from content by the ingestion pipeline, and this runs once per
    process at Tutor construction, not per request).
    """
    chunks = list(getattr(index, "chunks", None) or [])
    ids = "|".join(str(getattr(chunk, "id", "")) for chunk in chunks)
    digest = hashlib.sha256(ids.encode("utf-8")).hexdigest()[:12]
    return f"{type(index).__name__}:{len(chunks)}:{digest}"
