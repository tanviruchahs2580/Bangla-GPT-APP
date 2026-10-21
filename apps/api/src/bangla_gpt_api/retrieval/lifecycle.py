"""Index lifecycle: immutable versioned snapshots, atomic swap, rollback.

AUD-A1-11: the index was rebuilt in memory per worker at boot, with no
version identity, no atomic swap and no rollback — a rebuild that produced a
worse index had no path back, and two workers could not be told apart by
what they served. This module adds the missing lifecycle *around* the
existing in-memory indexes; it does not change how they are built.

Design:

* an :class:`IndexSnapshot` is immutable once published: it carries the
  corpus/config version string, the chunk count, the build timestamp and the
  index object itself;
* :class:`IndexRegistry` holds exactly one *active* snapshot plus a bounded
  history; ``publish`` swaps the active pointer in one bytecode-level
  assignment (atomic under the GIL, so a concurrent reader sees either the
  old or the new snapshot, never a half-built one);
* ``rollback`` re-activates a previous version, so the "rebuild made it
  worse" drill ends with the previous index serving again;
* the registry records an audit trail of ``publish``/``rollback`` events with
  the version strings, which is what a rollback drill asserts on.

The version string is the corpus fingerprint (the same value the cache keys
on) plus the retrieval configuration; a rebuild that changes either is a new
version by construction.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import Hit

#: How many superseded snapshots stay rollback-able. Two is the drill
#: requirement (current + previous); more is memory for little value since
#: an in-memory index holds its whole corpus.
DEFAULT_HISTORY = 2


def corpus_version(chunks: list[Chunk], config: Mapping[str, Any] | None = None) -> str:
    """Content-addressed version of a snapshot: corpus fingerprint + config.

    Uses the chunk ids in order (plus the config the index was built with),
    so the same corpus built with different retrieval parameters is a
    different version — exactly the case a rollback has to distinguish.
    """
    digest = hashlib.sha256("|".join(chunk.id for chunk in chunks).encode("utf-8"))
    if config:
        digest.update("|".join(f"{key}={config[key]}" for key in sorted(config)).encode("utf-8"))
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class IndexSnapshot:
    """One immutable, versioned index generation."""

    version: str
    index: Any
    chunk_count: int
    config: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def search(self, query: str, **kwargs: Any) -> list[Hit]:
        """Serve through the snapshot, pinning the version it answered with."""
        hits: list[Hit] = self.index.search(query, **kwargs)
        return hits


class IndexRegistry:
    """Serves one active snapshot; swaps atomically; rolls back on demand."""

    def __init__(self, *, history: int = DEFAULT_HISTORY) -> None:
        self._active: IndexSnapshot | None = None
        self._superseded: list[IndexSnapshot] = []
        self._history = max(history, 1)
        #: (event, version, at) audit trail; asserted by the rollback drill.
        self.events: list[tuple[str, str, str]] = []

    @property
    def active(self) -> IndexSnapshot | None:
        return self._active

    @property
    def versions(self) -> list[str]:
        """Superseded versions oldest-first, then the active one."""
        versions = [snapshot.version for snapshot in self._superseded]
        if self._active is not None:
            versions.append(self._active.version)
        return versions

    def publish(self, snapshot: IndexSnapshot) -> IndexSnapshot:
        """Atomically make ``snapshot`` the active one; return it."""
        previous = self._active
        # Single attribute assignment: readers observe either snapshot.
        self._active = snapshot
        if previous is not None:
            self._superseded.append(previous)
            self._superseded = self._superseded[-self._history :]
        self.events.append(("publish", snapshot.version, snapshot.created_at))
        return snapshot

    def build_and_publish(
        self,
        chunks: list[Chunk],
        index_factory: Any,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> IndexSnapshot:
        """Build a snapshot off-line, then publish it in one swap."""
        index = index_factory(chunks)
        snapshot = IndexSnapshot(
            version=corpus_version(chunks, config),
            index=index,
            chunk_count=len(chunks),
            config=dict(config or {}),
        )
        return self.publish(snapshot)

    def rollback(self, version: str | None = None) -> IndexSnapshot:
        """Re-activate a superseded snapshot (default: the previous one).

        Raises ``ValueError`` for an unknown or already-active version —
        a rollback that silently did nothing would be worse than none.
        """
        if not self._superseded:
            raise ValueError("no superseded snapshot to roll back to")
        if version is None:
            restored = self._superseded.pop()
        else:
            matching = [s for s in self._superseded if s.version == version]
            if not matching:
                raise ValueError(f"unknown superseded version: {version}")
            restored = matching[-1]
            self._superseded.remove(restored)
        if self._active is not None:
            self._superseded.append(self._active)
            self._superseded = self._superseded[-self._history :]
        self._active = restored
        self.events.append(("rollback", restored.version, restored.created_at))
        return restored
