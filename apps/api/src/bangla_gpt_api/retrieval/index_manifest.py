"""Served-index identity: which corpus, embedder and mode produced the index.

F-129/RAG-11: the index is rebuilt in memory per worker at boot and nothing
recorded what it was built from -- a rebuilt corpus, a different embedder or
a changed loader were all invisible. The corpus side is pinned by the tracked
corpus manifest (``nctb.manifest``); this module derives the served index's
identity from the chunk artifacts and the embedder, and compares the two so
a mismatch is a diagnosed error instead of a silent behaviour change.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

#: Bump when the digest recipe changes (the recipe is part of the identity).
CORPUS_DIGEST_VERSION = 1


def chunk_files(corpus_root: Path) -> list[Path]:
    """The built chunk artifacts of a corpus, in stable order."""
    return sorted((corpus_root / "normalized").glob("*.chunks.jsonl"))


def corpus_digest(paths: Iterable[Path]) -> str:
    """Digest of the built chunk artifacts: name + content hash, ordered.

    Covers the served corpus exactly: two builds that produce the same files
    under the same names get the same digest regardless of timestamps.
    """
    digest = hashlib.sha256()
    digest.update(f"v{CORPUS_DIGEST_VERSION}\n".encode("ascii"))
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                file_digest.update(block)
        digest.update(file_digest.hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def index_identity(
    *,
    corpus_digest: str,
    chunk_count: int,
    embedder_name: str,
    embedder_dim: int | None,
    retrieval_mode: str,
) -> dict:
    """The identity record logged at boot and comparable across deployments."""
    return {
        "corpus_digest": corpus_digest,
        "chunks": chunk_count,
        "embedder": embedder_name,
        "embedder_dim": embedder_dim,
        "retrieval_mode": retrieval_mode,
    }


def embedder_problems(declared: dict | None, *, name: str, dim: int | None) -> list[str]:
    """Differences between the manifest's embedder identity and the live one.

    An empty list means the deployment serves the corpus with the embedder the
    corpus was measured with. ``declared`` None means the manifest predates
    the embedder record, which is not a mismatch.
    """
    if not declared:
        return []
    problems: list[str] = []
    if declared.get("name") != name:
        problems.append(f"embedder name: manifest {declared.get('name')!r} != configured {name!r}")
    declared_dim = declared.get("dim")
    if declared_dim is not None and dim is not None and int(declared_dim) != int(dim):
        problems.append(f"embedder dim: manifest {declared_dim} != configured {dim}")
    return problems
