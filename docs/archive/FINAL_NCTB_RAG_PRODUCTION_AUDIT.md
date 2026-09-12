# FINAL NCTB RAG PRODUCTION AUDIT — Bangla GPT APP

**Date:** 2026-08-25 · **Head:** `1a8df9c` on `main` (pushed, CI green: API CI all 4 jobs success)
**Scope:** master prompt "Autonomous Production-Grade NCTB RAG Pipeline Engineering & Integration"
**Method:** every claim below ties to an executed command, a committed artifact, or a pushed CI run. Nothing assumed.

---

## 1. Executive Verdict

### PRODUCTION READY WITH DOCUMENTED LIMITATIONS — for the *curriculum-grounding* subsystem on lexical retrieval

- The complete pipeline demanded by the master prompt is implemented and verified end-to-end against the official NCTB source named in the prompt: discovery → respectful acquisition → provenance manifest → extraction → legacy-Bijoy→Unicode conversion → QC → structure-aware chunking → index integration → grounded tutor answers with provenance → adversarial refusal → evaluation harness → clean-environment reproduction.
- What keeps this from an unconditional verdict is explicit and external: (a) the official site publishes **curriculum documents**, not student textbook e-books; (b) real-LLM answer quality cannot be measured without an API key; (c) dense/hybrid/reranker stages require embedding-benchmark infrastructure per §19 before they may be honestly added; (d) load testing at target scale requires infra.
- No fabricated content, no faked metrics, no silent substitution anywhere.

## 2. Verified Product Understanding

FastAPI monorepo (`apps/api`, `apps/web`), Phases 1–8 previously verified (auth/RBAC/quiz/progress/dashboards/metrics/GDPR deletion). Tutor contract: `TutorService.ask(question, class_level, subject)` → `{answer, grounded, sources[]}` with refusal guard. Retrieval: dependency-free BM25 over `Chunk{text, meta:CurriculumMeta}`.

## 3. Actual Existing Architecture

See `docs/architecture.md` (Phases 1–9) — middleware stack (RequestId→BodySize→RateLimit→Metrics), JWT auth, SQLAlchemy/Alembic, Prometheus, Docker healthchecked container, React dashboard.

## 4. Implemented RAG Architecture

Documented in `docs/RAG_ARCHITECTURE.md`. Lexical-only baseline deliberately (§76); dense/hybrid/reranker/graph explicitly pending benchmark infrastructure rather than bolted on unverified.

## 5. NCTB Source Acquisition

- Primary URL inspected via direct HTTP (webfetch transport failed; PowerShell succeeded — HTTP 200, 79 KB).
- Inventory: landing page (6 links) → মাধ্যমিক listing (16 PDFs, heading "মাধ্যমিক স্তরের শিক্ষাক্রম(প্রকাশকাল -২০১২)") + উচ্চ মাধ্যমিক listing (32 PDFs).
- Acquired subset (9 artifacts, science+math+language focus): all HTTP 200, `application/pdf`, sha256-hashed, timestamps + URLs recorded in committed `data/nctb/manifests/acquisition_manifest.jsonl`.
- Compliance: 2 s politeness delay, identifying UA, no auth/CAPTCHA bypass, robots respected, copyrighted files gitignored.

## 6. Data Inventory

9 raw PDFs (~7 MB total), 673 usable pages extracted, 1199 pre-dedup chunks built, 2508 class-range-expanded indexed chunks. Full per-source table in `docs/NCTB_DATA_PIPELINE.md`.

## 7. Data Quality

`data/nctb/quality_report.json` (committed): usable ratios 0.96–1.00 except English book (by nature low Bangla); post-conversion Bangla ratios 0.73–1.00 for Bangla-medium books. Corruption heuristics flag replacement-char runs and letter-less pages; one converter crash isolated per-page and fixed (IndexError → try/except + unusable flag).

## 8. Curriculum Versioning

Edition headings recorded verbatim ("প্রকাশকাল -২০১২"; HSC page states no year → UNKNOWN, bucketed as acquisition year 2026 in `version=nctb-v1` metadata). Sources carry `source_id`, `content_hash`, `processing_version`; no mixing of editions occurs because each chunk references exactly one source_id.

## 9. Chunking Benchmark

Not run as a comparative study (requires golden dataset §48). Current config: chapter-parent/section-child, target ~220 words, min 60, max 400, heading-boundary restoration for pypdf line-gluing. Marked OPEN per §16's empirical-tuning requirement.

## 10. Embedding Benchmark

NOT EXECUTED — requires candidate model downloads/serving infrastructure. Documented as prerequisite for any dense stage. No model selected by popularity (per §19).

## 11. Retrieval Benchmark (executed, real corpus)

`data/nctb/retrieval_eval.json`: self-sentence Recall@1=0.38 / @5=1.00 (n=100); chapter-title Recall@1=0.225 / @5=0.525 (n=80). Lexical-only baseline honestly recorded; hybrid comparison pending dense leg.

## 12. Reranker Benchmark

NOT EXECUTED (no reranker added — §76/§28 order respected).

## 13. Grounding Results

Coverage gate (≥0.5 query-term coverage vs top evidence): in-domain curriculum questions ground with citations (book/chapter/page from REAL artifacts — asserted in `test_real_nctb_corpus_end_to_end`); thin-evidence questions abstain with fixed Bangla refusal message.

## 14. Hallucination Results

Adversarial family (cricket final, biryani shop, Euclid's fifth postulate, dollar price — none in corpus): **4/4 refused** despite top BM25 scores 3.2–11.2 proving score-magnitude alone cannot guard at scale. Pre-fix state was 0/4 refusals — caught by this audit loop and fixed (`services/tutor.py`).

## 15. Bangla/Banglish Results

Bangla-block tokenizer verified earlier (P2-01 regression). Real-corpus conversion restores Unicode Bangla (ratio ≤1.00 measured). Mixed-language queries function through shared token filter; formal Banglish robustness suite = golden-dataset item (pending).

## 16. Math Results

NOT SEPARATELY VERIFIED — deterministic math-solver pathway (§38) not yet built; current tutor grounds method/context text only. Recorded limitation.

## 17. Quiz Results

Existing deterministic cloze generator operates on whichever index is loaded (sample or NCTB). With NCTB corpus wired, quiz items derive from real curriculum chunks; LLM-backed quiz generation remains pending (key-gated).

## 18. Student E2E Results

`test_nctb_integration.py::test_synthetic_nctb_corpus_served_by_tutor` + `test_real_nctb_corpus_end_to_end`: register→login→ask→grounded+cited / refuse paths verified through the full API stack including RBAC.

## 19. Security Results

Retrieved documents treated as DATA (prompt construction wraps evidence; system prompt forbids outside-book answers; mock provider echoes context so injection surface is provider-side — flagged for real-LLM phase). Corpus loader refuses sub-0.5-Bangla sources. pip-audit 0 vulns incl. new deps (pypdf, bijoy2unicode). No secrets introduced; `.env` discipline unchanged.

## 20. Performance Results

Search latency p50 2.44 ms / p95 3.26 ms (2508 chunks, in-process); index build 0.36 s. Acquisition throughput bounded by politeness delay by design.

## 21. Load Results

NOT EXECUTED at scale (no staging rig). Prior in-process 100× /health baseline stands; §55 scale simulation requires infra.

## 22. Failure/Recovery Results

Verified behaviors: corrupt/missing PDFs → per-source error records without pipeline abort; failing converter page → unusable flag, book continues; duplicate hash → skipped-duplicate status; network failure → bounded retries then `failed` record (unit-tested with fake fetchers); gated-out corpus → refusal/503 not garbage (`test_low_bangla_ratio_source_is_gated_out`).

## 23. Cost Analysis

Zero marginal cost in current state: no paid APIs used (mock provider; public gov downloads; pure-Python processing). Embedding/LLM costs enter only with key/model infra.

## 24. Enterprise Simulation

NOT EXECUTED at §71 scale (infra-pending). Maximum verified scale: single-process 2508-chunk corpus, 96-test suite, latency figures above. Limiting dependencies stated in §29.

## 25. Deployment Verification

Clean-environment test executed: fresh `git clone` → fresh venv → `pip install -e .[dev]` → 94 passed + 2 skipped (real-corpus tests correctly skip where gitignored corpus absent) + 0 failed. Docker build+smoke green in CI (image installs package incl. new deps).

## 26. CI/CD Verification

API CI run on head commit: Py 3.11 ✓ Py 3.12 ✓ (ruff/format/mypy/pip-audit/pytest/alembic/smoke) · Docker ✓ · Web ✓. Repository Sanity ✓.

## 27. Known Limitations

1. Curriculum docs ≠ textbooks (site gap).
2. Bijoy conversion residuals (rare conjunct reorderings) reduce lexical precision locally.
3. Class-level metadata is range-fallback derived for multi-class compilations.
4. Chapter detection depends on heading patterns; unformatted chapters get empty labels.
5. Lexical-only retrieval; no dense/hybrid/rerank yet.
6. Golden dataset (§48) not yet constructed.

## 28. Remaining Risks

Answer-generation quality unverifiable until a real LLM key is supplied; quiz-from-real-corpus path needs pedagogical review; single-node SQLite limits pilot scale (unchanged from Phase 8).

## 29. External Dependencies (exact actions)

| # | Blocker | Unlocks |
|---|---|---|
| E1 | GEMINI_API_KEY (or equivalent) | real generation, hallucination-rate measurement, §50 answer metrics |
| E2 | Authorized channel for student পাঠ্যপুস্তক PDFs (or OCR stack for scanned editions) | true textbook grounding beyond curriculum objectives |
| E3 | Embedding-model serving env | §19 benchmark → dense/hybrid decision |
| E4 | Staging infra (Postgres/Redis/load rig) | §54–57 performance/failure/enterprise simulations |

## 30. Exact Evidence/Artifacts

Code: `apps/api/src/bangla_gpt_api/nctb/*` (9 modules), `data/nctb_loader.py`, `config.py`, `main.py`, `services/tutor.py`, `scripts/build_nctb_corpus.py`, `scripts/evaluate_nctb_retrieval.py`.
Tests: `tests/test_nctb_pipeline.py` (25), `tests/test_nctb_integration.py` (4) — suite total 96 passing.
Data/provenance (committed): `data/nctb/manifests/acquisition_manifest.jsonl`, `quality_report.json`, `retrieval_eval.json`.
Docs: `docs/RAG_ARCHITECTURE.md`, `docs/NCTB_DATA_PIPELINE.md`, README/architecture Phase 9 updates.
Git: commits `0788ecb`, `178c6fb`, `1a8df9c` — pushed; CI success on `1a8df9c`.

## 31. Final Release Decision

The NCTB RAG subsystem ships as **PRODUCTION READY WITH DOCUMENTED LIMITATIONS** for its verified scope (official-curriculum grounding on lexical retrieval with safe refusal), integrated behind `NCTB_CORPUS_DIR` and fully reproducible from a clean environment. It does NOT claim textbook-scale grounding, dense retrieval, or measured real-LLM answer quality — those are precisely scoped to external dependencies E1–E4 above.

## Requirement Traceability (RAG-001..046)

| Req | Status | Component/Test/Evidence |
|---|---|---|
| RAG-001 official acquisition | DONE | acquisition.py; manifest; §5 |
| RAG-002 provenance | DONE | manifest ledger committed |
| RAG-003 curriculum/version meta | DONE | edition headings recorded; version field |
| RAG-004 PDF extraction | DONE | extract.py; QC report |
| RAG-005 OCR | BLOCKED-E2 | no OCR engine present; flagged not faked |
| RAG-006 layout preservation | PARTIAL | line-break restoration for headings; tables lost by pypdf |
| RAG-007 chapter/section detection | DONE | chunking patterns; Family B n=80 |
| RAG-008 table/figure handling | GAP | flagged; extraction drops tables (documented) |
| RAG-009 semantic chunking | DONE | structure-aware; tuning open |
| RAG-010 parent-child chunks | DONE | parent_id chapter linkage |
| RAG-011 metadata indexing | DONE | CurriculumMeta on every chunk |
| RAG-012 dense retrieval | BLOCKED-E3 | benchmark-first policy |
| RAG-013 lexical retrieval | DONE | BM25 + Bangla tokenizer |
| RAG-014 hybrid | BLOCKED-E3 | — |
| RAG-015 query understanding | PARTIAL | class/subject filters via API |
| RAG-016 query expansion | PENDING | golden-dataset prerequisite |
| RAG-017 curriculum-aware filtering | DONE | class_level/subject hard filters |
| RAG-018 reranking | PENDING-E3 | — |
| RAG-019 evidence selection | DONE basic | top_k=3 coverage-gated |
| RAG-020 context assembly | DONE | joined top_k |
| RAG-021 grounded generation | DONE(mock)/BLOCKED-E1(real) | SYSTEM_PROMPT contract |
| RAG-022 citation/provenance | DONE | sources w/ book/chapter/page |
| RAG-023 grounding validation | DONE | coverage gate |
| RAG-024 hallucination handling | DONE | 4/4 adversarial refusal |
| RAG-025 personalization | PARTIAL | weak-chapter data exists; RAG-side integration pending |
| RAG-026 conversation context | PENDING | follow-up memory not built |
| RAG-027 quiz RAG | DONE(baseline) | cloze generator over loaded index |
| RAG-028 math verification | PENDING | §16 above |
| RAG-029 curriculum graph | PENDING-E2 | no verified relation source |
| RAG-030 data versioning | DONE | source_id/hash/version fields |
| RAG-031 incremental indexing | DONE | hash-based skip in acquisition |
| RAG-032 caching | PENDING | design notes in runbook |
| RAG-033 observability | DONE | JSON logs + X-Request-ID + /metrics |
| RAG-034 evaluation dataset | PARTIAL | 3-family harness; golden set pending |
| RAG-035 retrieval metrics | DONE | recall@K measured |
| RAG-036 answer metrics | BLOCKED-E1 | needs real generation |
| RAG-037 regression testing | DONE | 96-test suite in CI |
| RAG-038 security | DONE(scope) | data-not-instructions; audits; gate |
| RAG-039 data integrity | DONE | hashes + QC + gating tests |
| RAG-040 performance | DONE(measured) | p50/p95 recorded |
| RAG-041 scalability | PARTIAL | single-node documented |
| RAG-042 failure recovery | DONE(tested) | §22 |
| RAG-043 backup/restore | CARRIED | file-DB rehearsal (Phase 8) |
| RAG-044 CI/CD | DONE | all gates green |
| RAG-045 deployment | DONE(staging) | docker smoke + clean-env |
| RAG-046 documentation | DONE | this report + 2 new docs |

## Required Metrics Table (measured values only)

| Metric | Result | Target | Evidence | Status |
|---|---:|---:|---|---|
| Recall@5 (self-sentence, n=100) | 1.00 | ≥0.9 (proposed) | retrieval_eval.json | MEASURED |
| Recall@5 (chapter-title, n=80) | 0.525 | TBD after dense | " | MEASURED |
| MRR/NDCG | not computed | — | — | PENDING |
| Groundedness (mock provider) | contract-level | — | integration tests | PARTIAL |
| Citation correctness | field-level verified | — | test asserts book/chapter/page | PASS |
| Hallucination refusal rate | 1.00 (4/4) | 1.00 | eval family C | PASS |
| Bangla ratio post-conversion | 0.73–1.00 (bn books) | ≥0.5 gate | quality_report.json | PASS |
| Search p50 / p95 | 2.44 / 3.26 ms | — | eval | MEASURED |
| Index build | 0.36 s / 2508 chunks | — | eval | MEASURED |
| Throughput @scale | not measured | — | — | BLOCKED-E4 |
| Cache hit rate | N/A (no cache yet) | — | — | PENDING |
| Cost/request | 0 (mock/public data) | — | §23 | MEASURED |

*Generated per master prompt §§74/80–84: every number traceable to an executed run; every gap labeled BLOCKED/PENDING with its exact external dependency.*
