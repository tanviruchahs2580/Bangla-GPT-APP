# RAG V5 baseline audit — 2026-11-15

Statuses per the V5 prompt §2.1. HEAD at audit: `c944164` (main, post
v0.11.2). Environment: developer workstation; live production = single-host
SQLite container (runbook §7.1); CI carries real Postgres.

## Request flow and index lifecycle (VERIFIED_IN_SOURCE)

- Serving path: auth/consent/safety → normalize/transliterate → BM25 ∥
  VectorIndex → RRF (k=60) → lexical rerank → grounding gate (IDF-weighted
  coverage ≥ 0.5, <2 absent content terms) → top-3 evidence → answer with
  `citation_verified` (deterministic citation_check, metered, warn-only —
  pinned by `test_citation_check_metered_and_warned_on_fail`).
- Index lifecycle: `load_nctb_corpus()` runs at startup from
  `data/nctb/normalized/` (847 chunks real curriculum corpus; corpus digest
  `1396faf2…`, embedder fingerprint enforced by `_verify_embedder_identity`
  and the manifest gate). BM25 + vectors are rebuilt per process start —
  the V5 prompt's persistence requirement targets exactly this.
- Retrieval mode: single `hybrid` mode (`config.py:179`); no
  bm25-only/neural mode switches yet.

## Embedding adapter (VERIFIED_IN_SOURCE)

- `Embedder` protocol: `name` + `embed(texts) -> list[list[float]]`.
- `HashingEmbedder` (384-dim, char-ngram hashing, L2-normalised) is the
  default; `RemoteEmbedder` exists behind `EMBEDDING_MODEL` + API base/key
  (OpenAI-compatible; hardening required before any student-data egress —
  V5 §4.4 default is no egress).
- `vector_text()` embeds heading context + body. Identity enforced against
  the corpus manifest in both lanes (F-129/RAG-11).

## Vector storage (VERIFIED_IN_SOURCE)

- `VectorIndex` = brute-force cosine over in-memory vectors; module
  docstring explicitly defers pgvector to V5 ("will implement the same
  contract server-side"). No pgvector anywhere in the tree; CI Postgres =
  `postgres:16-alpine` (no extension); production DB = SQLite.

## BM25 (VERIFIED_IN_SOURCE)

- `BM25Index` in-process; artifact persistence/generation identity do not
  exist yet — the V5 generation contract must bind both lanes.

## Class 6 corpus scope (VERIFIED_IN_SOURCE + VERIFIED_LOCAL_RUNTIME)

- The served corpus is 9 NCTB curriculum documents (classes 6–10 share the
  secondary payload via level-range fallback; per-class `detected_classes`
  empty) — NOT the class-6 textbook. The owner-supplied class-6 textbook is
  QUARANTINED (no text layer; `.docx` route documented, never delivered).
- V5 §0.2 scope-lock consequence: the initial V5 index cannot claim an
  approved Class 6 textbook corpus. Per §5.1/§17 blocker rules: build
  pipeline/schema/validators/fixtures; mark real Class 6 ingestion and
  model-selection acceptance `BLOCKED_SOURCE_OR_RIGHTS` /
  `BLOCKED_OWNER_DATA`; the CURRENT corpus (already serving) remains the
  efficiency target for the working system, with class filters preserved.

## Evaluation data (VERIFIED_IN_SOURCE)

- `golden_v3.json` (427 items) is bound to the bundled 78-chunk sample
  corpus (identity pin); baseline v3 gates CI. Real-corpus
  `retrieval_eval.json` families (self-sentence n=100, chapter-title n=80,
  adversarial) are unsupervised/weak — NOT human-reviewed labels. No
  corpus-bound human-reviewed benchmark exists ⇒ model-selection
  acceptance gate = `BLOCKED_OWNER_DATA` (V5 §5.1 rules).

## Verification (VERIFIED_IN_SOURCE)

- Deterministic `citation_check` + trace `citation_verdict` + Prometheus
  counter; no claim-level mapping, no verification_status states, no
  shadow/enforce modes yet.

## Discrepancy/risk register

| ID | P | Finding | Status |
|---|---|---|---|
| R5-01 | P1 | pgvector absent everywhere (CI/prod); production DB is SQLite | VERIFIED_IN_SOURCE; activation `BLOCKED_INFRA` for prod, CI integration is the safe isolated work |
| R5-02 | P1 | No human-reviewed Class 6 labels ⇒ no qualified model/reranker selection possible | VERIFIED_IN_SOURCE; `BLOCKED_OWNER_DATA` |
| R5-03 | P1 | Approved Class 6 textbook corpus absent (quarantined source) | VERIFIED_IN_SOURCE; scope-lock governs |
| R5-04 | P2 | BM25/vectors rebuilt every process start; no generation identity | VERIFIED_IN_SOURCE; this wave's deliverable |
| R5-05 | P2 | RemoteEmbedder egress unhardened for student data | VERIFIED_IN_SOURCE; keep non-default + redaction-first |
| R5-06 | P3 | ANN strategy premature at 847-chunk scale | VERIFIED_IN_SOURCE; exact search is the reference (V5 §6.3) |
