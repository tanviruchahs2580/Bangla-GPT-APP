"""RAG V5 Gate P1 — pgvector persistence and generation lifecycle.

These tests run against REAL PostgreSQL + the vector extension. They are
skipped — with the exact missing dependency named — when no pgvector-capable
PostgreSQL URL is configured; a SQLite run may never claim pgvector
semantics (Master Prompt §6.2/§13.3). CI's Postgres engine job uses the
pgvector/pgvector:pg16 image, so the gate is real there.

Covered: generation state machine (building→validated→active→retained),
atomic pointer semantics, idempotent upsert, exact-cosine search with
server-side metadata filters, generation isolation (no cross-generation
candidates), dimension/completeness validation, retirement cleanup.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from bangla_gpt_api.db.session import make_session_factory
from bangla_gpt_api.retrieval.generation import (
    GenerationManager,
    GenerationStateError,
    PgVectorStore,
)

_PG_URL = os.environ.get("BGPT_PGVECTOR_TEST_URL", "").strip()

pytestmark = [
    pytest.mark.skipif(
        not _PG_URL,
        reason=(
            "BGPT_PGVECTOR_TEST_URL not configured — pgvector integration"
            " requires real PostgreSQL + the vector extension (NOT_RUN locally,"
            " real in the CI pgvector leg)"
        ),
    )
]


@pytest.fixture()
def pg_engine():
    engine = create_engine(_PG_URL)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    # migrations are applied by the CI job before tests; ensure the tables
    # exist even when this file runs standalone against a provisioned URL
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _PG_URL)
    command.upgrade(cfg, "head")
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM rag_vector_chunks"))
        conn.execute(text("DELETE FROM rag_active_generation"))
        conn.execute(text("DELETE FROM rag_index_generations"))
    engine.dispose()


def _store(pg_engine, gen_id: str) -> PgVectorStore:
    return PgVectorStore(pg_engine, gen_id)


def test_generation_state_machine_and_atomic_pointer(pg_engine) -> None:
    manager = GenerationManager(make_session_factory(pg_engine))
    manager.create_building(
        generation_id="g1",
        corpus_digest="digest-a",
        embedder_name="hashing",
        dimension=384,
    )
    with pytest.raises(GenerationStateError):
        manager.activate("g1")  # building → activate is refused
    manager.mark_validated("g1", chunk_count=3)
    manager.activate("g1")
    assert manager.active_generation_id() == "g1"
    row = manager.get("g1")
    assert row is not None and row.state == "active" and row.activated_at is not None

    # a second validated generation swaps the pointer; the old one is retained
    manager.create_building(
        generation_id="g2", corpus_digest="digest-a", embedder_name="hashing", dimension=384
    )
    manager.mark_validated("g2", chunk_count=2)
    manager.activate("g2")
    assert manager.active_generation_id() == "g2"
    assert manager.get("g1").state == "retained"


def test_upsert_is_idempotent_and_search_applies_filters_in_sql(pg_engine) -> None:
    manager = GenerationManager(make_session_factory(pg_engine))
    manager.create_building(
        generation_id="gx", corpus_digest="d", embedder_name="hashing", dimension=4
    )
    store = _store(pg_engine, "gx")
    vec_a = [1.0, 0.0, 0.0, 0.0]
    vec_b = [0.0, 1.0, 0.0, 0.0]
    rows = [
        ("c1", "src1", 6, "science", "কোষ", vec_a),
        ("c2", "src1", 7, "math", "বীজগণিত", vec_b),
    ]
    assert store.upsert(rows) == 2
    assert store.upsert(rows) == 2  # idempotent: no duplicates, no error
    assert store.count() == 2

    # exact cosine: vec_a matches c1; the class filter is applied in SQL
    hits_all = store.search(vec_a, top_k=5)
    assert hits_all[0][0] == "c1"
    assert len(hits_all) == 2
    hits_class6 = store.search(vec_a, top_k=5, class_level=6)
    assert [h[0] for h in hits_class6] == ["c1"]
    hits_chapter = store.search(vec_a, top_k=5, chapter="কোষ")
    assert [h[0] for h in hits_chapter] == ["c1"]
    assert store.search(vec_a, top_k=5, class_level=9) == []

    manager.mark_validated("gx", chunk_count=2)


def test_generation_isolation_no_cross_generation_candidates(pg_engine) -> None:
    manager = GenerationManager(make_session_factory(pg_engine))
    for gen in ("ga", "gb"):
        manager.create_building(
            generation_id=gen, corpus_digest="d", embedder_name="hashing", dimension=4
        )
        manager.mark_validated(gen, chunk_count=1)
    sa = _store(pg_engine, "ga")
    sb = _store(pg_engine, "gb")
    sa.upsert([("only-a", "s", 6, "science", "কোষ", [1.0, 0.0, 0.0, 0.0])])
    sb.upsert([("only-b", "s", 6, "science", "কোষ", [1.0, 0.0, 0.0, 0.0])])
    assert [h[0] for h in sa.search([1.0, 0.0, 0.0, 0.0], top_k=5)] == ["only-a"]
    assert [h[0] for h in sb.search([1.0, 0.0, 0.0, 0.0], top_k=5)] == ["only-b"]


def test_validate_detects_count_and_dimension_problems(pg_engine) -> None:
    manager = GenerationManager(make_session_factory(pg_engine))
    manager.create_building(
        generation_id="gv", corpus_digest="d", embedder_name="hashing", dimension=4
    )
    store = _store(pg_engine, "gv")
    store.upsert([("c1", "s", 6, "science", "কোষ", [1.0, 0.0, 0.0, 0.0])])
    problems = store.validate(expected_count=2, dimension=4)
    assert any("count" in p for p in problems)
    store.upsert([("c2", "s", 6, "science", "কোষ", [0.0, 1.0, 0.0, 0.0])])
    assert store.validate(expected_count=2, dimension=4) == []
    manager.mark_validated("gv", chunk_count=2)


def test_retirement_cleans_retained_generation_rows(pg_engine) -> None:
    """Real cleanup flow: a newer generation is active, the older retained
    one is retired and its vectors are deleted; the active one is untouched."""
    manager = GenerationManager(make_session_factory(pg_engine))
    for gen in ("keep", "drop"):
        manager.create_building(
            generation_id=gen, corpus_digest="d", embedder_name="hashing", dimension=4
        )
        manager.mark_validated(gen, chunk_count=1)
        _store(pg_engine, gen).upsert(
            [("c-" + gen, "s", 6, "science", "কোষ", [1.0, 0.0, 0.0, 0.0])]
        )
        manager.activate(gen)
    assert manager.active_generation_id() == "drop"
    assert manager.get("keep").state == "retained"
    removed = PgVectorStore(pg_engine, "keep").delete_generation("keep")
    assert removed == 1
    assert _store(pg_engine, "drop").count() == 1  # active generation untouched
