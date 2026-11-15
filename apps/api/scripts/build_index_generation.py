"""Build a pgvector index generation from the normalized NCTB corpus.

RAG V5.5: the operations runbook's next-wave item. The CLI is offline
tooling (import-linter contract 5) — it never serves traffic. It writes
only to the PostgreSQL URL given on the command line and REFUSES SQLite:
the pgvector DDL and operators do not exist there, and a silent in-memory
substitution is exactly what the V5 contract forbids.

Usage (staging lane):
    python scripts/build_index_generation.py \
        --database-url postgresql+psycopg://... \
        --data-dir ../../data/nctb --activate

Steps: corpus digest → GenerationManager.create_building (idempotent) →
batch embed (the configured embedder; default hash-ngram-local 384-d) →
PgVectorStore.upsert (idempotent, so an interrupted build is re-run
safely) → store.validate → mark_validated → optional --activate.
``bm25_artifact_sha256`` is recorded as NULL: the serving BM25 index is
rebuilt in-process at boot and no persisted artifact exists yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from bangla_gpt_api.config import get_settings  # noqa: E402
from bangla_gpt_api.db.session import make_engine, make_session_factory  # noqa: E402
from bangla_gpt_api.retrieval.embedding import build_embedder  # noqa: E402
from bangla_gpt_api.retrieval.generation import (  # noqa: E402
    GenerationManager,
    PgVectorStore,
)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    source_id: str
    class_level: int | None
    subject: str | None
    chapter: str | None


def validate_database_url(url: str) -> None:
    """Refuse anything but PostgreSQL — the pgvector lane has no SQLite
    substitute (V5 contract: never an in-memory substitution)."""
    if not url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        print(
            f"::error::--database-url must be PostgreSQL (got {url.split('://', 1)[0]}://…);"
            " the pgvector lane has no SQLite substitute.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def load_chunks(data_dir: Path) -> list[Chunk]:
    """Read the manifest for source metadata, then every normalized chunk
    file. A manifest source with no chunks file is a hard error — the
    digest must cover exactly what the manifest declares."""
    manifest_path = data_dir / "manifests" / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    for source in manifest["sources"]:
        sid = source["source_id"]
        path = data_dir / "normalized" / f"{sid}.chunks.jsonl"
        if not path.exists():
            raise SystemExit(f"::error::manifest declares {sid} but {path} is missing")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                detected = rec.get("detected_class")
                chunks.append(
                    Chunk(
                        chunk_id=str(rec["chunk_id"]),
                        text=rec["text"],
                        source_id=sid,
                        class_level=detected if isinstance(detected, int) else None,
                        subject=source.get("subject_bn") or None,
                        chapter=rec.get("chapter") or None,
                    )
                )
    return chunks


def load_chunks_serving(data_dir: Path) -> list[Chunk]:
    """Serving-parity chunk set: the same ``load_nctb_corpus`` recipe boot
    uses (dedupe, non-Bangla exclusion, class attribution). The raw-file
    path above indexes records the serving index would never hold, so this
    is the DEFAULT source for a generation meant to be compared with — or
    promoted to — serving."""
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

    served = load_nctb_corpus(
        data_dir / "normalized",
        quality_report_path=data_dir / "quality_report.json",
    )
    if not served:
        raise SystemExit(
            "::error::the serving loader produced 0 chunks — check the corpus"
            " and quality_report.json before building a generation"
        )
    return [
        Chunk(
            chunk_id=c.id,
            text=c.text,
            source_id=c.meta.source,
            class_level=c.meta.class_level,
            subject=c.meta.subject,
            chapter=c.meta.chapter or None,
        )
        for c in served
    ]


def corpus_digest(chunks: list[Chunk]) -> str:
    """sha256 over the sorted (source, chunk, text-hash) triples — changes
    iff any chunk text or the chunk set changes."""
    h = hashlib.sha256()
    for c in sorted(chunks, key=lambda c: (c.source_id, c.chunk_id)):
        h.update(f"{c.source_id}\x00{c.chunk_id}\x00".encode())
        h.update(hashlib.sha256(c.text.encode("utf-8")).digest())
    return h.hexdigest()


def chunk_rows(
    chunks: list[Chunk], embedder: object
) -> list[tuple[str, str, int | None, str | None, str | None, list[float]]]:
    vectors = embedder.embed([c.text for c in chunks])  # type: ignore[attr-defined]
    rows = []
    for c, vec in zip(chunks, vectors, strict=True):
        # The chunk record's `chapter` is extraction runoff as often as a
        # clean heading (real corpus: >1000-char values), while the store
        # column is varchar(200) — filter metadata, not display text. Cap
        # it to the column width so the value stays a stable equality key.
        chapter = c.chapter[:200] if c.chapter else None
        rows.append((c.chunk_id, c.source_id, c.class_level, c.subject, chapter, vec))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data" / "nctb",
        help="corpus root (manifests/ + normalized/)",
    )
    parser.add_argument("--generation-id", default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--activate",
        action="store_true",
        help="activate after validation (staging use; production activation"
        " is an owner decision recorded separately)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="index the raw chunk files instead of the serving-parity loader"
        " output (dedupe, non-Bangla exclusion, class attribution) — for"
        " debugging the pipeline, not for promotable generations",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute the digest and count chunks; write nothing",
    )
    args = parser.parse_args(argv)
    validate_database_url(args.database_url)

    chunks = load_chunks(args.data_dir) if args.raw else load_chunks_serving(args.data_dir)
    digest = corpus_digest(chunks)
    generation_id = args.generation_id or f"gen-{digest[:12]}"
    print(f"chunks: {len(chunks)}  corpus_digest: {digest}  generation: {generation_id}")
    if args.dry_run:
        return 0

    settings = get_settings()
    embedder = build_embedder(settings)
    probe = embedder.embed(["probe"])[0]
    dimension = len(probe)
    print(f"embedder: {embedder.name}  dimension: {dimension}")

    engine = make_engine(type("S", (), {"database_url": args.database_url})())
    manager = GenerationManager(make_session_factory(engine))
    manager.create_building(
        generation_id=generation_id,
        corpus_digest=digest,
        embedder_name=embedder.name,
        dimension=dimension,
    )
    store = PgVectorStore(engine, generation_id)
    rows = chunk_rows(chunks, embedder)
    for i in range(0, len(rows), args.batch_size):
        store.upsert(rows[i : i + args.batch_size])
        print(f"upserted {min(i + args.batch_size, len(rows))}/{len(rows)}")
    problems = store.validate(expected_count=len(rows), dimension=dimension)
    if problems:
        manager.mark_failed(generation_id)
        for p in problems:
            print(f"::error::{p}", file=sys.stderr)
        return 1
    manager.mark_validated(generation_id, chunk_count=len(rows))
    print(f"validated: {generation_id} ({len(rows)} chunks)")
    if args.activate:
        manager.activate(generation_id)
        print(f"activated: {generation_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
