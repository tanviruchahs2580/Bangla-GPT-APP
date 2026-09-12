"""Application dependency construction.

Extracted from the monolithic ``main.py``.  Builds every runtime dependency
(provider, index, tutor, database engine, admin bootstrap) and returns an
``AppContext`` plus all objects needed by the lifespan context — **no closure
capture**, all passed explicitly.

Returns a tuple so the caller can attach ``app.state.engine`` and pass
provider/engine to ``build_lifespan()``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.auth.security import hash_password
from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.db.models import User
from bangla_gpt_api.db.session import init_db, make_session_factory
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex  # noqa: F401 (re-exported for tests)
from bangla_gpt_api.routers.deps import AppContext
from bangla_gpt_api.services.tutor import TutorService

if TYPE_CHECKING:  # typing-only: never executed, so no import cycles
    from sqlalchemy.engine import Engine

    from bangla_gpt_api.caching import Cache, CachedRankingIndex
    from bangla_gpt_api.providers.base import LLMProvider
    from bangla_gpt_api.retrieval.base import RankingIndex
    from bangla_gpt_api.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation helpers (called once at boot — fail-fast on bad config)
# ---------------------------------------------------------------------------


def validate_app_config(settings: Settings) -> None:
    """Validate rate-limit / jobs backends.  Raises on any unsupported value."""
    if settings.rate_limit_backend not in ("memory", "redis"):
        raise RuntimeError(
            f"RATE_LIMIT_BACKEND={settings.rate_limit_backend!r} is not supported; "
            "use 'memory' or 'redis'"
        )
    if settings.rate_limit_backend == "redis" and not settings.redis_url:
        raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL to be set")
    if settings.jobs_backend not in ("inline", "arq"):
        raise RuntimeError(
            f"JOBS_BACKEND={settings.jobs_backend!r} is not supported; use 'inline' or 'arq'"
        )


def validate_database_url(settings: Settings) -> None:
    """Ensure we are not silently using an in-memory DB in production."""
    if settings.is_production and settings.database_url.strip() == "sqlite://":
        logger.critical(
            "production_in_memory_database",
            extra={"op": "config"},
        )
        raise RuntimeError(
            "DATABASE_URL must be a persistent store in production "
            "(e.g. sqlite:////data/app.db or PostgreSQL)"
        )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _safe_init_db(engine: object, settings: Settings) -> None:
    """create_all tolerant of concurrent multi-worker boot (gunicorn -w N)."""
    try:
        from bangla_gpt_api.config import get_settings as _get_s

        s = settings or _get_s()
        if s.is_production and s.database_url.strip().startswith("postgresql"):
            return
    except Exception:
        pass
    try:
        init_db(engine)  # type: ignore[arg-type]
    except Exception as exc:
        if "already exists" not in str(exc):
            raise


def _bootstrap_admin(session_factory: Callable[[], Session], settings: Settings) -> None:
    """Create the admin user if credentials are provided (idempotent)."""
    if not settings.admin_email or not settings.admin_password:
        return

    force_change = settings.force_admin_password_change
    db: Session = session_factory()
    try:
        admin_email = settings.admin_email.strip().lower()
        exists = db.execute(select(User).where(User.email == admin_email)).scalar_one_or_none()
        if exists is None:
            db.add(
                User(
                    email=admin_email,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                    must_change_password=force_change,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                # Another worker bootstrapped the same admin concurrently.
                db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Provider / Index / Tutor construction
# ---------------------------------------------------------------------------
# NOTE: provider / fast_provider / circuit_breaker / fallback_provider are
# ACCEPTED AS PARAMETERS (not looked up here).  This avoids a circular
# import (main → initialize → providers → main) and lets callers that
# monkeypatch ``main.get_provider`` retain control.


def _build_index(
    chunks: list[Chunk],
    settings: Settings,
    cache: Cache,
    hybrid_index_cls: type[HybridIndex] | None = None,
) -> CachedRankingIndex:
    """Build a ranking index (hybrid or BM25) with RAG query-result cache."""
    from bangla_gpt_api.caching import RAG_CACHE_TTL_SECONDS, CachedRankingIndex

    if settings.retrieval_mode.strip().lower() == "hybrid":
        from bangla_gpt_api.retrieval.embedding import build_embedder

        # Use the passed-in class (for monkeypatch support) or the real one.
        if hybrid_index_cls is None:
            from bangla_gpt_api.retrieval.hybrid_index import HybridIndex as _real_hybrid

            hybrid_index_cls = _real_hybrid

        inner: RankingIndex = hybrid_index_cls(chunks, build_embedder(settings))  # type: ignore[arg-type]
    else:
        from bangla_gpt_api.retrieval.bm25 import BM25Index

        inner = BM25Index(chunks)

    return CachedRankingIndex(inner, cache, ttl=RAG_CACHE_TTL_SECONDS)


def _build_tutor(
    index: RankingIndex,
    provider: LLMProvider,
    fast_provider: LLMProvider | None,
    circuit_breaker: CircuitBreaker | None,
    fallback_provider: LLMProvider | None,
) -> TutorService:
    """Construct the TutorService with optional circuit breaker + fallback."""
    return TutorService(
        index=index,
        provider=provider,
        fast_provider=fast_provider,
        circuit_breaker=circuit_breaker,
        fallback_provider=fallback_provider,
    )


def _load_corpus_chunks(settings: Settings) -> list[Chunk]:
    """Load NCTB corpus or fall back to sample corpus."""
    if settings.nctb_corpus_dir:
        from pathlib import Path as _Path

        from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

        corpus_root = _Path(settings.nctb_corpus_dir)
        chunks = load_nctb_corpus(
            corpus_root / "normalized",
            quality_report_path=corpus_root / "quality_report.json",
        )
        if chunks:
            return chunks
    return load_sample_corpus()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_dependencies(
    settings: Settings,
    cache: Cache,
    provider: LLMProvider | None,
    fast_provider: LLMProvider | None,
    circuit_breaker: CircuitBreaker | None,
    fallback_provider: LLMProvider | None,
    hybrid_index_cls: type[HybridIndex] | None = None,
    make_engine_fn: Callable[..., Any] | None = None,
) -> tuple[AppContext, LLMProvider | None, LLMProvider | None, Engine, Callable[[], Session]]:
    """Build all runtime dependencies.

    Parameters ``provider``, ``fast_provider``, ``circuit_breaker``,
    ``fallback_provider`` are passed from ``main.py`` so that callers that
    monkeypatch ``main.get_provider`` retain control.

    ``hybrid_index_cls`` and ``make_engine_fn`` are optional overrides that
    let callers that monkeypatch ``main.HybridIndex`` / ``main.make_engine``
    inject their own implementations.  When *None* the function falls back
    to the real internal classes.

    Returns ``(ctx, provider, fast_provider, engine, session_factory)``.
    """
    # Validation (fail-fast)
    validate_app_config(settings)
    validate_database_url(settings)

    # Resolve monkey-patchable overrides
    _hi_cls = hybrid_index_cls
    _me_fn = make_engine_fn

    # --- Index construction (needs provider present) ---
    index: RankingIndex | None = None
    tutor: TutorService | None = None
    if provider is not None:
        chunks = _load_corpus_chunks(settings)
        from bangla_gpt_api.caching import RAG_CACHE_TTL_SECONDS, CachedRankingIndex
        from bangla_gpt_api.retrieval.embedding import build_embedder

        if settings.retrieval_mode.strip().lower() == "hybrid":
            if _hi_cls is None:
                from bangla_gpt_api.retrieval.hybrid_index import HybridIndex as _real_hybrid

                _hi_cls = _real_hybrid
            inner: RankingIndex = _hi_cls(chunks, build_embedder(settings))  # type: ignore[arg-type]
        else:
            from bangla_gpt_api.retrieval.bm25 import BM25Index

            inner = BM25Index(chunks)

        index = CachedRankingIndex(inner, cache, ttl=RAG_CACHE_TTL_SECONDS)

        tutor = _build_tutor(index, provider, fast_provider, circuit_breaker, fallback_provider)
    else:
        tutor = None

    # --- Database ---
    if _me_fn is None:
        from bangla_gpt_api.db.session import make_engine as _real_make_engine

        _me_fn = _real_make_engine
    engine = _me_fn(settings)
    _safe_init_db(engine, settings)
    session_factory = make_session_factory(engine)

    # --- Admin bootstrap ---
    _bootstrap_admin(session_factory, settings)

    # --- AppContext ---
    ctx = AppContext(
        settings=settings,
        cache=cache,
        provider=provider,
        index=index,
        tutor=tutor,
        session_factory=session_factory,
        ai_job_tasks=set(),
    )

    return ctx, provider, fast_provider, engine, session_factory
