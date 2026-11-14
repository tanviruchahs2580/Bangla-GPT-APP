"""RAG V5 — retrieval generation lifecycle and the pgvector store.

Two pieces of the V5 Master Prompt's generation contract (§3.3, §6.4–6.6):

* :class:`GenerationManager` — the state machine for one complete retrieval
  snapshot (``building → validated → active → retained → retired`` with
  ``failed`` terminal), backed by the ``rag_index_generations`` registry and
  the single-row ``rag_active_generation`` pointer. Activation is one
  transaction: a reader sees either the previous complete generation or the
  new one, never a mix.
* :class:`PgVectorStore` — persistent exact-cosine vector search over
  ``rag_vector_chunks`` (PostgreSQL + pgvector only; the migration creates
  the table and the extension). Metadata filters are applied in SQL, not
  after retrieval (§6.2). SQLite never touches this class: the local
  in-memory :class:`~bangla_gpt_api.retrieval.vector.VectorIndex` remains
  the local contract, and no test may claim pgvector semantics from SQLite.

Both are infrastructure, not the serving default: the production default
retrieval mode is unchanged until the benchmark and owner gates pass
(V5 §5.5, §12 W3 exit).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bangla_gpt_api.db.models import RagActiveGeneration, RagIndexGeneration
from bangla_gpt_api.logging_config import json_log

logger = logging.getLogger(__name__)

_ALLOWED_STATES = ("building", "validated", "active", "retained", "retired", "failed")


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GenerationStateError(RuntimeError):
    """An operation was attempted from the wrong generation state."""


class PgVectorUnavailable(RuntimeError):
    """pgvector (extension/table) is not available on this engine."""


class GenerationManager:
    """Registry state machine + the atomic active pointer."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def create_building(
        self,
        *,
        generation_id: str,
        corpus_digest: str,
        embedder_name: str,
        dimension: int,
        embedder_revision: str | None = None,
    ) -> RagIndexGeneration:
        with self._sf() as db:
            existing = db.get(RagIndexGeneration, generation_id)
            if existing is not None:
                # Idempotent resume: a failed/interrupted build may be retried
                # under the same id; an already-active id may never be reused.
                if existing.state == "active":
                    raise GenerationStateError(
                        f"generation {generation_id} is active; build ids are immutable"
                    )
                return existing
            row = RagIndexGeneration(
                generation_id=generation_id,
                state="building",
                corpus_digest=corpus_digest,
                embedder_name=embedder_name,
                embedder_revision=embedder_revision,
                dimension=dimension,
                created_at=_utcnow(),
            )
            db.add(row)
            db.commit()
            json_log(
                logger,
                logging.INFO,
                "rag_generation_created",
                generation_id=generation_id,
                embedder=embedder_name,
            )
            return row

    def mark_validated(
        self,
        generation_id: str,
        *,
        chunk_count: int,
        bm25_artifact_sha256: str | None = None,
    ) -> None:
        with self._sf() as db:
            row = db.get(RagIndexGeneration, generation_id)
            if row is None or row.state != "building":
                raise GenerationStateError(
                    f"generation {generation_id} must be 'building' to validate"
                )
            row.state = "validated"
            row.chunk_count = chunk_count
            row.bm25_artifact_sha256 = bm25_artifact_sha256
            row.validated_at = _utcnow()
            db.commit()

    def activate(self, generation_id: str) -> None:
        """Atomically point the active singleton at a validated generation.

        One transaction swaps the pointer and stamps both rows; the previous
        active generation (if any) moves to ``retained`` so rollback stays a
        pointer flip away. SQLite and PostgreSQL both give the singleton
        update full-transaction isolation at this scale (one row).
        """
        with self._sf() as db:
            row = db.get(RagIndexGeneration, generation_id)
            if row is None or row.state != "validated":
                raise GenerationStateError(
                    f"generation {generation_id} must be 'validated' to activate"
                )
            pointer = db.get(RagActiveGeneration, 1)
            if pointer is None:
                db.add(
                    RagActiveGeneration(
                        singleton=1, generation_id=generation_id, activated_at=_utcnow()
                    )
                )
            else:
                previous = db.get(RagIndexGeneration, pointer.generation_id)
                if previous is not None and previous.state == "active":
                    previous.state = "retained"
                    previous.retired_at = None
                pointer.generation_id = generation_id
                pointer.activated_at = _utcnow()
            row.state = "active"
            row.activated_at = _utcnow()
            db.commit()
            json_log(
                logger,
                logging.INFO,
                "rag_generation_activated",
                generation_id=generation_id,
            )

    def active_generation_id(self) -> str | None:
        with self._sf() as db:
            pointer = db.get(RagActiveGeneration, 1)
            return pointer.generation_id if pointer else None

    def get(self, generation_id: str) -> RagIndexGeneration | None:
        with self._sf() as db:
            return db.get(RagIndexGeneration, generation_id)

    def mark_failed(self, generation_id: str) -> None:
        with self._sf() as db:
            row = db.get(RagIndexGeneration, generation_id)
            if row is None or row.state == "active":
                return  # never fail an active generation from here
            row.state = "failed"
            db.commit()


class PgVectorStore:
    """Exact-cosine vector search over one generation's pgvector rows."""

    def __init__(self, engine: Engine, generation_id: str) -> None:
        self.engine = engine
        self.generation_id = generation_id
        with engine.connect() as conn:
            exists = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                    " WHERE table_name = 'rag_vector_chunks')"
                )
            ).scalar()
            if not exists:
                raise PgVectorUnavailable(
                    "rag_vector_chunks is missing — run migrations on PostgreSQL"
                    " with the vector extension; SQLite/local keeps the"
                    " in-memory VectorIndex"
                )

    def upsert(
        self,
        rows: list[tuple[str, str, int | None, str | None, str | None, list[float]]],
    ) -> int:
        """Idempotent batch upsert: (chunk_id, source_id, class, subject,
        chapter, embedding). One statement per row inside one transaction;
        failures roll the batch back and the caller retries the batch.
        """
        if not rows:
            return 0
        now = _utcnow()
        with self.engine.begin() as conn:
            for chunk_id, source_id, class_level, subject, chapter, vec in rows:
                literal = "[" + ",".join(f"{v:.8g}" for v in vec) + "]"
                conn.execute(
                    text(
                        "INSERT INTO rag_vector_chunks (generation_id, chunk_id,"
                        " source_id, class_level, subject, chapter, embedding, created_at)"
                        " VALUES (:g, :c, :s, :cl, :sub, :ch, CAST(:v AS vector), :t)"
                        " ON CONFLICT (generation_id, chunk_id) DO UPDATE SET"
                        " embedding = EXCLUDED.embedding, created_at = EXCLUDED.created_at"
                    ),
                    {
                        "g": self.generation_id,
                        "c": chunk_id,
                        "s": source_id,
                        "cl": class_level,
                        "sub": subject,
                        "ch": chapter,
                        "v": literal,
                        "t": now,
                    },
                )
        return len(rows)

    def count(self) -> int:
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    text("SELECT count(*) FROM rag_vector_chunks WHERE generation_id = :g"),
                    {"g": self.generation_id},
                ).scalar_one()
            )

    def validate(self, *, expected_count: int, dimension: int) -> list[str]:
        """Completeness/uniqueness/dimension checks (§6.6 step 8)."""
        problems: list[str] = []
        with self.engine.connect() as conn:
            count = self.count()
            if count != expected_count:
                problems.append(f"chunk count {count} != expected {expected_count}")
            dims = (
                conn.execute(
                    text(
                        "SELECT DISTINCT vector_dims(embedding) FROM rag_vector_chunks"
                        " WHERE generation_id = :g"
                    ),
                    {"g": self.generation_id},
                )
                .scalars()
                .all()
            )
            for d in dims:
                if int(d) != dimension:
                    problems.append(f"dimension {d} != expected {dimension}")
            orphans = conn.execute(
                text(
                    "SELECT count(*) FROM rag_vector_chunks v LEFT JOIN"
                    " rag_index_generations g ON g.generation_id = v.generation_id"
                    " WHERE v.generation_id = :g AND g.generation_id IS NULL"
                ),
                {"g": self.generation_id},
            ).scalar_one()
            if orphans:
                problems.append(f"{orphans} vector rows without a registry row")
        return problems

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        class_level: int | None = None,
        subject: str | None = None,
        chapter: str | None = None,
    ) -> list[tuple[str, float]]:
        """Exact cosine (``<=>``) with metadata filters in SQL.

        Returns ``[(chunk_id, cosine_distance)]`` ascending by distance.
        Bounded by ``top_k``; the connection is scoped to this call.
        """
        literal = "[" + ",".join(f"{v:.8g}" for v in query_embedding) + "]"
        clauses = ["generation_id = :g"]
        params: dict[str, object] = {
            "g": self.generation_id,
            "q": literal,
            "k": top_k,
        }
        if class_level is not None:
            clauses.append("class_level = :cl")
            params["cl"] = class_level
        if subject:
            clauses.append("subject = :sub")
            params["sub"] = subject
        if chapter:
            clauses.append("chapter = :ch")
            params["ch"] = chapter
        where = " AND ".join(clauses)
        # S608 is ignored file-wide (pyproject per-file-ignores): `where` is
        # assembled only from the fixed clause literals above — every
        # user-supplied value travels as a bound parameter.
        query = text(
            "SELECT chunk_id, embedding <=> CAST(:q AS vector) AS distance"
            f" FROM rag_vector_chunks WHERE {where}"
            " ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query, params).all()
        return [(str(r[0]), float(r[1])) for r in rows]

    def delete_generation(self, generation_id: str) -> int:
        """Retirement cleanup for one generation (§6.6 step 14)."""
        with self.engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM rag_vector_chunks WHERE generation_id = :g"),
                {"g": generation_id},
            )
            return int(result.rowcount or 0)
