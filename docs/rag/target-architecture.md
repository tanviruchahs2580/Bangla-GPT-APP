# RAG target architecture and roadmap (from the 2026-10-29 gap analysis)

Source: `.qa-work/audit/RAG/report.md` §6 (gap analysis against the master
reference architecture) and the findings register. This document turns that
analysis into a phased plan. It is a plan, not a claim about the current
system — the current state is `docs/rag/architecture.md`.

## 1. Gap table (reference component -> state here -> gap)

| Reference component | State here | Gap | Finding ids |
|---|---|---|---|
| Ingestion with offset map + versioned manifest | chunks + acquisition manifest; per-source `content_version` | no offset map back to PDF text; committed artifacts are not reproducible from the raw files | F-RAG-8, F-RAG-16 |
| Lexical + dense indexes, transactional filters | BM25 + hashing-embedder vector lane, in-memory, filters pre-applied | no semantic lane, no pgvector/Postgres index, no blue/green swap | F-RAG-10, F-RAG-4 |
| Query pipeline (language ID, rewrite, variants, filters) | variants, glossary, spelling, Banglish, follow-up rewrite | no language/script identification, no learned rewriter | RAG-08 |
| Parallel lexical+dense, RRF, cross-encoder, MMR, parent expansion | candidate pool 3x top_k, RRF k=60, deterministic rerank | no cross-encoder, no diversity control, no parent expansion | F-RAG-9 |
| Textbook-grounded gate before generation | IDF-weighted content-term coverage, >=2-absent budget implemented | untuned on a held-out set; threshold constants in source | F-RAG-2 |
| Versioned prompts, citation-first output, streaming | streaming shipped; sectioned answer contract | prompts unversioned, no inline citation IDs, no prompt hash | F-RAG-11 |
| Validation: citation existence/support, numeric, safety, language gate | safety screen, coverage gate, per-chunk citation check, output screen | no numeric recomputation, no language/register gate, no claim-level entailment | F-RAG-7, F-RAG-15 |
| Versioned golden set, ratchet gates, online signals, human sample | golden gate (fixed 2pp) + admin board; hit@3 floor and red-team in `evaluation.cli --gate` | dataset unversioned, no intervals/strata, no human sample | F-RAG-5, F-RAG-6, F-RAG-13 |
| Traces, caches keyed by corpus version, fallbacks, kill switch | cache keyed by corpus fingerprint; LLM breaker/fallback | no per-answer trace, no retrieval-only degraded mode, no kill switch | F-RAG-11, F-RAG-12, F-LLM-14 |

## 2. P0 — correctness, no new dependencies

1. **Out-of-corpus budget** (done, F-002): the gate refuses when >= 2 content
   terms are absent from the corpus; measured false-answer 3/4 -> 0/4 on the
   family-C probes, in-corpus false-refusal unchanged at 5/624.
2. **Truthful class metadata** (done, F-049): cover-statement detection with
   range support, level-range attribution only behind the explicit flag, and
   refusal when no signal exists. Remaining for P1: the five secondary
   curriculum documents have garbled covers — decide (owner) whether they are
   level-wide curriculum material (keep level attribution) or replace them
   with class-specific textbooks.
3. **Reproducible corpus artifacts** (partly done): a double-build
   idempotency check is still missing; regenerate `data/nctb` artifacts and
   `retrieval_eval.json` in one commit, or make CI rebuild the corpus.
4. **Docs truthfulness**: `docs/rag/architecture.md` (current state) and the
   corrections section in `docs/RAG_ARCHITECTURE.md` (this change).
5. **Numeric/unit checks** are absent everywhere; nothing claims them yet, so
   this stays a P1 candidate rather than a defect.

## 3. P1 — retrieval quality, offline evidence first

1. Held-out stratified eval set with a version field, Wilson intervals and a
   paired bootstrap against the previous SHA (the harness is
   `.qa-work/tools/stats.py`; make a product artifact of it).
2. Parent expansion and a token-budgeted context assembly behind flags, with
   an ablation runner; measure chunk size with the production tokenizer.
3. A real multilingual embedding model (`BAAI/bge-m3`,
   `intfloat/multilingual-e5-*`) only after licence checks and a golden-eval
   lift beyond the noise.
4. Chapter metadata for sources whose extraction lost running heads; a build
   that fails on missing chapter for chapter-scoped products.

## 4. P2 — operations and scale

1. Index manifest (corpus hash, embedder name/dims) verified at startup; a
   versioned index build with blue/green swap and rollback.
2. pgvector/Postgres lexical index parity test.
3. Per-stage latency with p99, TTFT, and retrieval-only degraded mode when
   the provider is unavailable (`/tutor/ask` currently must stay 503 because
   the index is built inside the provider branch — F-LLM-14).
4. Index-size/QPS/cost rows in the capacity plan.

## 5. P3 — advanced

1. Cross-encoder rerank and MMR/diversity.
2. Claim-level entailment checks with a validated judge (the current judge is
   the deterministic `local_overlap` mode).
3. Per-answer trace store (chunk ids, prompt hash, citation outcome) and
   drift indicators on the admin quality board.
4. Human review loop: rubric, stratified sample, calibrate the confidence
   display label.

## 6. Wave-2b status update (2026-10-30)

The gap table above was written at the audit SHA. What has moved since, with
the owning evidence:

| Gap | Status now |
|---|---|
| Versioned golden set, intervals, paired bootstrap, strata | Done: `eval/golden_v3.json` + `baseline_v3.json`, `evaluation/stats.py`, `docs/rag/golden-set-v3.md`; the gate also enforces the language floors |
| Versioned prompts, prompt hash, per-answer trace | Done: `PROMPT_VERSION`/`PROMPT_SHA256`, `evaluation/observability.py`, `tests/test_w2_eval_trace.py` |
| Kill switch and retrieval fallback isolation | Done: `AI_GENERATION_ENABLED`, lexical-lane fallback in `_retrieve_guarded`; the provider-outage path still returns 503 rather than retrieval-only excerpts (open, F-131) |
| Index manifest verified at boot, embedder identity | Done: `nctb_corpus_identity` boot log, `apps/api/scripts/check_corpus_manifest.py`, `build_embedder` identity gate; the per-answer/health exposure is still open (F-082 handoff) |
| Token-budgeted context assembly | Done and wired at the tutor call site (F-129); measured selection drops nothing on the committed set |
| Numeric recomputation and language-integrity checks | Done deterministically (`evaluation/output_validation.py`, `evaluation/metrics.py`); the semantic validator still lacks parser call sites (F-118 handoff) |
| Cross-encoder, MMR, pgvector, human evaluation loop | Still open (P2/P3 items above, unchanged) |
