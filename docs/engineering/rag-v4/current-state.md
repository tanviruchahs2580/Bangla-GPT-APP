# RAG V4 — current state (verified inventory)

Verified 2026-11-13 on branch `feat/bangla-gpt-rag-v4-readiness` (from `2731a4a`). Every claim below carries
its status. Statuses: VERIFIED_IN_SOURCE / VERIFIED_IN_TEST_OR_CI / VERIFIED_IN_PRODUCTION_READ_ONLY /
OWNER_REPORTED_UNVERIFIED / UNKNOWN / CONTRADICTED / NOT_APPLICABLE. Deep dossiers:
`architecture-review.md` (audit synthesis), `r1-regression-investigation.md` (Phase 1),
`source-registry.md` (corpus/source), `implementation-plan.md` (risk-ranked plan),
`evidence-ledger.jsonl` (append-only command/outcome record).

## Request path (student input → answer + citations)

`POST /tutor/ask` · chat JSON · chat SSE — routers/tutor.py:232/718/852. Stages and code sites verified in
source by the Phase-4 audit: consent gate → kill switch → normalize → safety screen →
retrieval + grounding gate → refusal branch → evidence assembly (`assemble_evidence`, 768-token selection
budget, dedupe by normalized text) → `build_evidence_prompt` (`<evidence>`/`<user_question>` delimiters,
PII-redacted question) → provider (mock/gemini/openai + fallback + circuit breaker) → output screen →
citation check (**computed, never blocking** — deliberate, test-pinned) → trace (privacy-safe) →
`AskResponse{answer, grounded, sources[], refused_reason, citation_verified, confidence}`.

- V4 §7.1 stages **absent**: claim-level mapping, constrained regeneration on citation failure
  (documented deliberate), clarification-question behavior. [VERIFIED_IN_SOURCE]
- Served answer carries no inline citation ids; `sources[]` is server-populated from chunk metadata, so
  page/chapter/attribution cannot be model-invented in the payload. [VERIFIED_IN_SOURCE]

## Retrieval engine (post-#119)

Query normalization (`retrieval/normalize.py`) → BM25 ∥ dense (HashingEmbedder, 384-dim) → RRF (k=60) →
candidate-pool dedup (normalized text + source) → rerank (lexical feature ranker default; cross-encoder
stage dormant, config-gated, injected redactor/breaker, degrades locally) → neighbor expansion (dormant,
same-section/same-class) → context assembly top_k=3 (LOCKED contract) → grounding gate (IDF coverage ≥0.5,
<2 absent terms, Bangla-bigram vector guard). Metadata filters: class/subject/chapter/book/year via one
shared predicate. Sweep: `apps/api/scripts/benchmark_retrieval_v2.py` 24 cells × 427 golden items —
all cells identical (grounded 0.808 / hit@3 0.9951 / gate-refusal 0.2412; artifact `eval/benchmark_v2.json`);
the knobs are measured-insensitive on the sample corpus. [VERIFIED_IN_TEST_OR_CI + local reruns]

## Corpus (served set)

9 sources (5 "secondary" = classes 6–10 curriculum docs, 4 "hsc" = 11–12), 847 chunks →
**1598 index chunks (multi-class 6–12, class-6 via the level-range fallback: the same 244 secondary
chunks serve classes 6–10)**. Digest `1396faf2…`, manifest `check_corpus_manifest` OK, all content_qa
files pass. The English book is silently excluded (Bangla-ratio 0.0376 < 0.5). The owner-supplied
class-6 textbook is NOT in the corpus (no text layer; no OCR path; it lives in Downloads). Corpus is
**curriculum (শিক্ষাক্রম), not student textbooks** — documented in `docs/NCTB_DATA_PIPELINE.md:36-38`.
[VERIFIED_IN_SOURCE; full table in source-registry.md]

## Auth, safety, privacy, ops

- Authz/tenancy/impersonation/exploit guards: **38 passed** (4 suites). Injection: **20 passed** (3 suites).
  Retention numbers intact (730/365/30/30); invite sweep live. [VERIFIED_IN_TEST_OR_CI]
- Reranker egress (dormant): redacted query + corpus text only; redactor injected at the only production
  construction site. Residual: no https/host allowlist; no data-use gate for the endpoint. [VERIFIED_IN_SOURCE]
- Safeguarding escalation: **no owner-approved human process exists** (proposed, unapproved, in
  `docs/ai/incident-response.md`). Automated helpline copy only. [VERIFIED_IN_SOURCE / OWNER DECISION]
- Observability: structured logs redact PII; metrics low-cardinality; /metrics token-gated in production;
  uptime probe failed 3× before today (tunnel rotation — repaired today, alias 200×2 verified).
- CI security jobs all present (pip-audit, semgrep, gitleaks-history, Trivy, CodeQL, Scorecard);
  main API CI run 43375014233 success. [VERIFIED_IN_CI ARTIFACT]
- Production: alias `https://bangla-gpt-app.vercel.app/api/health` → 200 `{"status":"ok"}` verified today;
  live API container `bangla-gpt-api:0.10.0-d6f3342` (rollback kept as `api-live-pre-auditfix`);
  pre-swap snapshot + restore_test PASS 2026-11-12 19:54. [VERIFIED_IN_PRODUCTION_READ_ONLY]

## §0.1 handoff-claim verification (V4 requirement)

All 20 owner-reported claims checked; **none CONTRADICTED, none STALE**; two refined:

| Claim | Status |
|---|---|
| PR #119 merged; 5570eaf + 2731a4a | VERIFIED (ancestry of main checked) |
| CI legs green (Chromium, import-linter, radon, floors, PG, Docker) | VERIFIED (run 43375014233, job list) |
| Vercel deploy + /api/health 200 | VERIFIED (read-only probe 200×2 today) |
| BM25+dense+RRF+candidate pool foundation | VERIFIED (hybrid_index/fusion) |
| Cross-encoder dormant until configured | VERIFIED (rag_reranker=lexical default; tests) |
| Neighbor expansion dormant, class/section scope | VERIFIED (tests) |
| book=/year= filters | VERIFIED (tests) |
| Dedup normalized-text+source, cross-class kept | VERIFIED |
| Remote dim checked on first embed | VERIFIED (on_dim_known + tests) |
| benchmark_retrieval_v2 24-cell/427, Wilson | VERIFIED |
| Sweep 0.808/0.9951/0.2412 all cells; defaults cf=3/60/off; top_k=3 locked | VERIFIED — **and semantically re-read**: 0.808 = gate-verdict agreement on mock answers; 0.2412 = ALL gate refusals, of which **82/406 = 20.2% are false refusals on answerable items** (published as refusal quality, it would mislead) |
| Eval CLI +1.17pp CI-excl-0, refusal delta 0 | VERIFIED (re-run today on the identity-bound baseline) |
| Golden 24q 0.9167 ≥ 0.9 | VERIFIED |
| 48 red-team/injection/safety/bangla passing | VERIFIED (48) |
| Real-corpus eval + manifest regenerated, gate OK | VERIFIED |
| Floors 35/35; reranker 98.32%; expansion 96.7% | VERIFIED (local full-suite + CI artifact) |
| Full local suite 2218 pass; 1 stale-metadata red | VERIFIED — the red is the installed-metadata artifact: `Settings().version` reads the stale locally-installed 0.6.2 dist over the 0.10.0 manifest; deterministic in isolation, green in CI. Disposition: local-env artifact, documented, not a code defect |
| R@1 0.87 vs 0.95; pre-v2 reproduced 0.87 | VERIFIED — and **resolved further**: 0.95 and 0.87 are different corpus revisions (digests differ); Nov-3 code × current corpus = 0.87 exactly → code contributes zero; causa prima = corpus rebuild 05d95a5 (2026-11-11). See r1-regression-investigation.md |
| Chromium X-02 bare /login | VERIFIED (3 occurrences; product-side redirect inconsistency; root cause = boot-401 path drops ?next=) |
| Tunnel URL rotated; API_ORIGIN repointed; named tunnel future | VERIFIED (twice today; repaired both) |
| Docker VHDX 82 GB; prune 20.7 GB; compaction window pending | VERIFIED |

## Unknowns / environment limits

- Live-model behaviour (precision of citation_check, false-refusal rate on a real provider) — hermetic
  harness only; UNVERIFIED-LIVE by design (no provider credentials used).
- Deployment's mounted `NCTB_CORPUS_DIR` — repo default is empty (bundled 78-chunk sample); the live
  container's actual corpus mount is not inspectable read-only from here → treat live corpus scope as
  UNKNOWN (owner can confirm via `/admin/system/info`).
- The supplied class-6 PDF/DOCX binaries were not parsed (untrusted input; no OCR path).
