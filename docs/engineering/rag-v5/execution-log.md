# RAG V5 execution log — append-only

- 2026-11-15 · W0 · Branch `feat/rag-v5-semantic-pgvector` from `c944164`;
  baseline-audit.md + feature-lock-register.md written; benchmark-protocol.md
  pre-registered (v1, PROPOSED tolerances) before any candidate scoring.
- 2026-11-15 · W3/W4 · Migration `c7d9e1f3a5b7` (engine-conditional:
  generation registry + atomic pointer on both engines; pgvector chunks +
  CREATE EXTENSION on Postgres only). Drift fixes: RagActiveGeneration
  model + state index + autogen index name. GenerationManager +
  PgVectorStore implemented; CI Postgres service switched to
  pgvector/pgvector:pg16; tests/test_pgvector_store.py (5 tests, real
  extension in CI, explicit skip-with-reason locally). Chain pin advanced.
- 2026-11-15 · W2 · retrieval/neural_embedder.py (identity contract, E5
  prefixes, dim/finite validation, lazy backend); build_embedder neural
  branch (explicit, non-default); boot guard for unknown providers.
- 2026-11-15 · W7 · evidence_verification_mode off|shadow|enforce +
  approval flag; additive `verification_status` on AskResponse; enforce
  boot-guarded (no calibrated verifier — production cannot reach it by
  accident). Config-validity guards run for every environment; the
  production-only block keeps its early return.
- 2026-11-15 · fixes · seams helper attribute (the file's own designed
  signal), .env.example entries (+ comment-pair repair), error-table
  mapping for `mfa_unavailable` was the v0.11.2 wave; this wave's
  meta-gate findings all fixed at root.
- 2026-11-15 · verify · Full API suite 2259 passed / 16 skipped (0
  failed); ruff/format/mypy clean (school.py:887 = documented local-only
  drift, CI pinned mypy passes); alembic upgrade+check clean; complexity
  ratchet untouched (no tracked function modified).
