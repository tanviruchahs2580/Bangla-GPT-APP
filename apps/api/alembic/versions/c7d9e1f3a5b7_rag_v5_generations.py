"""RAG V5: index generation registry + pgvector chunk embeddings

Revision ID: c7d9e1f3a5b7
Revises: b6c8d0e2f4a6
Create Date: 2026-11-15

Two additions for the V5 retrieval-generation contract (Master Prompt
§3.3/§6.4):

* ``rag_index_generations`` — the registry for one complete retrieval
  snapshot (corpus digest, embedder identity, dimension, BM25 artifact
  identity, state machine ``building → validated → active → retained →
  retired``/``failed``). Engine-neutral: created on SQLite too so local
  runs and tests exercise the same lifecycle code.
* ``rag_active_generation`` — the single-row atomic activation pointer.
  Engine-neutral for the same reason.
* ``rag_vector_chunks`` — pgvector rows keyed by (generation_id,
  chunk_id) with class/subject/chapter metadata columns so metadata
  filters run server-side. **PostgreSQL only** (requires the ``vector``
  extension); on SQLite this DDL is skipped entirely — SQLite keeps the
  in-memory VectorIndex, and no test may claim pgvector semantics from
  SQLite (Master Prompt §6.2).

The embedding dimension is fixed at 384 for this schema generation
(multilingual-e5-small and the HashingEmbedder are both 384). A model
with a different dimension requires a reviewed migration — the
fixed-dimension strategy documented in the V5 plan (§6.3 option 1).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d9e1f3a5b7"
down_revision: str | Sequence[str] | None = "b6c8d0e2f4a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VECTOR_DIM = 384


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "rag_index_generations",
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="building"),
        sa.Column("corpus_digest", sa.String(length=64), nullable=False),
        sa.Column("embedder_name", sa.String(length=120), nullable=False),
        sa.Column("embedder_revision", sa.String(length=120), nullable=True),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("bm25_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("validated_at", sa.DateTime(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("generation_id"),
    )
    op.create_index("ix_rag_index_generations_state", "rag_index_generations", ["state"])
    op.create_table(
        "rag_active_generation",
        sa.Column("singleton", sa.Integer(), nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("singleton"),
    )
    if _is_postgres():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            f"CREATE TABLE rag_vector_chunks ("
            f"generation_id VARCHAR(64) NOT NULL, "
            f"chunk_id VARCHAR(64) NOT NULL, "
            f"source_id VARCHAR(120) NOT NULL, "
            f"class_level INTEGER, "
            f"subject VARCHAR(120), "
            f"chapter VARCHAR(200), "
            f"embedding vector({_VECTOR_DIM}) NOT NULL, "
            f"created_at TIMESTAMP NOT NULL, "
            f"PRIMARY KEY (generation_id, chunk_id))"
        )
        op.create_index(
            "ix_rag_vector_chunks_generation",
            "rag_vector_chunks",
            ["generation_id"],
        )
        op.create_index(
            "ix_rag_vector_chunks_meta",
            "rag_vector_chunks",
            ["class_level", "subject", "chapter"],
        )


def downgrade() -> None:
    if _is_postgres():
        op.drop_index("ix_rag_vector_chunks_meta", table_name="rag_vector_chunks")
        op.drop_index("ix_rag_vector_chunks_generation", table_name="rag_vector_chunks")
        op.execute("DROP TABLE rag_vector_chunks")
        # The extension itself is left installed: other schemas may use it
        # and DROP EXTENSION is a cluster-level operation.
    op.drop_table("rag_active_generation")
    op.drop_index("ix_rag_index_generations_state", table_name="rag_index_generations")
    op.drop_table("rag_index_generations")
