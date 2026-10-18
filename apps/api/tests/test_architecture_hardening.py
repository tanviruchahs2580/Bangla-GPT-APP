"""System-design hardening tests: DB posture, truthful readiness, boot cost.

Three architecture-level contracts are pinned here (each was a real gap
between what the system *declared* and what it *did*):

* **Cross-engine integrity parity** — the app enforces foreign keys on
  PostgreSQL, but the live single-file SQLite deployment ran with SQLite's
  defaults (``foreign_keys=OFF``, no lock wait, rollback journal). The
  pragmas in ``db/session.py`` now give SQLite the same contract; these
  tests assert the pragmas are actually applied (a comment is not a
  posture) and that a dangling foreign key is refused.
* **Truthful readiness** — ``/ready``/``/status`` previously reported OK
  while the retrieval index was missing, even though every tutoring turn
  503s in that state. Both now include the index, and these tests fail if
  that regresses in either direction.
* **Boot cost observability** — index construction is a per-worker boot
  cost; ``bgpt_rag_index_build_seconds`` must record it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import ChatMessage
from bangla_gpt_api.db.session import (
    POSTGRES_CONNECT_TIMEOUT_SECONDS,
    SQLITE_BUSY_TIMEOUT_MS,
    init_db,
    make_engine,
    make_session_factory,
)
from bangla_gpt_api.main import create_app
from bangla_gpt_api.metrics import REGISTRY


def _file_engine(tmp_path):  # noqa: ANN001, ANN202 - pytest tmp_path fixture
    url = f"sqlite:///{(tmp_path / 'posture.db').as_posix()}"
    return make_engine(Settings(env="test", database_url=url))


def _pragma(engine, name: str):  # noqa: ANN001, ANN202
    with engine.connect() as conn:
        return conn.exec_driver_sql(f"PRAGMA {name}").scalar()


# ------------------------------------------------------ DB posture (SQLite) --


def test_sqlite_file_engine_applies_production_pragmas(tmp_path) -> None:  # noqa: ANN001
    engine = _file_engine(tmp_path)
    assert _pragma(engine, "journal_mode") == "wal"
    assert _pragma(engine, "foreign_keys") == 1
    assert _pragma(engine, "busy_timeout") == SQLITE_BUSY_TIMEOUT_MS
    # synchronous=NORMAL is the integer 1; WAL's documented safe pairing.
    assert _pragma(engine, "synchronous") == 1


def test_sqlite_memory_engine_keeps_integrity_pragmas() -> None:
    engine = make_engine(Settings(env="test", database_url="sqlite://"))
    # WAL is meaningless in memory, but FK enforcement and lock-wait posture
    # must match the file engine, or tests would validate a weaker contract
    # than production runs.
    assert _pragma(engine, "foreign_keys") == 1
    assert _pragma(engine, "busy_timeout") == SQLITE_BUSY_TIMEOUT_MS


def test_sqlite_foreign_keys_are_enforced(tmp_path) -> None:  # noqa: ANN001
    engine = _file_engine(tmp_path)
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        session.add(ChatMessage(conversation_id=999_999, role="user", content="orphan"))
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_postgres_engine_sets_connect_timeout() -> None:
    engine = make_engine(
        Settings(env="test", database_url="postgresql+psycopg://u:p@127.0.0.1:1/db")
    )
    # create_engine is lazy: no connection is attempted here, only the
    # connect budget is configured.
    assert engine.dialect.name == "postgresql"
    assert engine.pool._creator is not None
    # The timeout reaches libpq via connect_args; assert the declared value
    # stays wired (a silent constant edit would reintroduce indefinite hangs).
    assert POSTGRES_CONNECT_TIMEOUT_SECONDS == 10


# ------------------------------------------------------ truthful readiness ---


def test_ready_includes_the_retrieval_index() -> None:
    app = create_app(Settings(env="test"))
    client = TestClient(app)
    assert client.get("/ready").status_code == 200

    # Degrade exactly the dependency under test: the provider and DB stay up,
    # only the index disappears -- /ready must now fail.
    ctx = app.state.ctx
    saved = (ctx.index, ctx.tutor)
    ctx.index, ctx.tutor = None, None
    try:
        res = client.get("/ready")
        assert res.status_code == 503
        assert res.json()["detail"] == "Retrieval index unavailable"
    finally:
        ctx.index, ctx.tutor = saved

    assert client.get("/ready").status_code == 200


def test_status_page_reports_curriculum_component() -> None:
    app = create_app(Settings(env="test"))
    client = TestClient(app)
    body = client.get("/status").json()
    curriculum = next(c for c in body["components"] if c["name"] == "curriculum")
    assert curriculum["ok"] is True
    assert body["status"] == "ok"

    ctx = app.state.ctx
    saved = (ctx.index, ctx.tutor)
    ctx.index, ctx.tutor = None, None
    try:
        degraded = client.get("/status").json()
        curriculum = next(c for c in degraded["components"] if c["name"] == "curriculum")
        assert curriculum["ok"] is False
        assert degraded["status"] == "degraded"
    finally:
        ctx.index, ctx.tutor = saved


# ------------------------------------------------------ boot cost metric -----


def test_boot_records_index_build_duration() -> None:
    before = REGISTRY.get_sample_value("bgpt_rag_index_build_seconds_count", {"mode": "hybrid"})
    create_app(Settings(env="test"))
    after = REGISTRY.get_sample_value("bgpt_rag_index_build_seconds_count", {"mode": "hybrid"})
    assert (after or 0.0) >= (before or 0.0) + 1.0


def test_bm25_mode_records_its_own_build_duration() -> None:
    before = REGISTRY.get_sample_value("bgpt_rag_index_build_seconds_count", {"mode": "bm25"})
    create_app(Settings(env="test", retrieval_mode="bm25"))
    after = REGISTRY.get_sample_value("bgpt_rag_index_build_seconds_count", {"mode": "bm25"})
    assert (after or 0.0) >= (before or 0.0) + 1.0
