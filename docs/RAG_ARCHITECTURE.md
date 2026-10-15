# RAG Architecture — Bangla GPT APP (NCTB subsystem)

Status: **verified as implemented** (2026-08-25). Every component below maps
to code in `apps/api/src/bangla_gpt_api/` and to executed evidence recorded
in `FINAL_NCTB_RAG_PRODUCTION_AUDIT.md`.

## Implemented architecture (lexical baseline)

```text
Student question (Bangla/Banglish)
        ↓
  POST /tutor/ask  (JWT required)
        ↓
  BM25Index.search(class_level=…, subject=…)      ← curriculum-aware filter
        │   tokenizer: Bangla block U+0980–U+09FF
        ↓
  Grounding gate (TutorService._grounded)
        │   • query-term coverage ≥ 0.5 against top evidence
        │   • absolute score floor retained at 0 (coverage dominates;
        │     fixed floors do not transfer across corpus sizes — measured)
        ├── fail → INSUFFICIENT_EVIDENCE_ANSWER, grounded=false (abstain)
        ↓ pass
  Context assembly (top_k=3 chunks joined)
        ↓
  LLMProvider.generate(prompt, system=SYSTEM_PROMPT)
        │   provider factory; mock default; real providers behind key
        ↓
  AskResponse{answer, grounded=true, sources[book/chapter/section/page/score]}
```

## Corpus flow

```text
nctb.gov.bd official pages
  → acquisition (respectful, idempotent, sha256 manifest)
  → raw PDFs (data/nctb/raw, gitignored)
  → pypdf extraction + per-page encoding flags
  → legacy Bijoy→Unicode conversion where detected
  → normalization (NFC, zero-width strip), corruption QC
  → structure-aware chunking (chapter parent → section child, page range)
  → normalized/*.chunks.jsonl (+ quality_report.json)
  → NCTB_CORPUS_DIR wiring → BM25Index at app startup
```

## Deliberate deviations from the master target diagram (§6)

| Master component | Status | Justification |
|---|---|---|
| Dense retrieval | partial | the vector lane ships with a deterministic, model-free embedder (`retrieval/embedding.py`: char 2-4-grams, dim 384); a real embedding model is still pending (§19) — `embedding_model` stays empty and naming one raises `ProviderNotConfigured` |
| Hybrid merge | shipped | BM25 + vector lanes fused with reciprocal rank fusion (k=60) then lexically reranked (`retrieval/hybrid_index.py`); `retrieval_mode` defaults to `"hybrid"` |
| Reranker | partial | deterministic lexical rerank ships (BM25-lane base + RRF + term coverage + char trigrams); a model-based reranker benchmark is still pending (§28) |
| Graph retrieval | pending | no verified prerequisite graph source yet (§15: never hallucinate relations) |
| Query understanding/expansion/router | partial | class/subject hard filters via API contract; intent classification deferred until golden dataset exists |

Per master §76 (no overengineering): what ships is hybrid retrieval by
default — a deterministic, model-free embedder fused with BM25 and lexically
reranked, measured and documented rather than padded with unbenchmarked
model-based stages; model-based dense retrieval and a model-based reranker
remain pending.

## Measured baseline (real corpus, 2026-08-25)

| Metric | Value |
|---|---|
| Indexed chunks (class-range expanded) | 2508 |
| Index build | 0.36 s |
| Search latency p50 / p95 | 2.4 ms / 3.3 ms |
| Self-sentence Recall@1 / @5 (n=100) | 0.38 / 1.00 |
| Chapter-title Recall@1 / @5 (n=80) | 0.225 / 0.525 |
| Adversarial refusal rate | 4/4 = 1.00 |

Full numbers regenerate via `apps/api/scripts/evaluate_nctb_retrieval.py`.
