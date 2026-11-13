# Architecture review — RAG V4 readiness pass (V4 Phase 6)

Date: 2026-11-13 · Branch `feat/bangla-gpt-rag-v4-readiness` · Scores are 1–5
**only where evidence exists**; anything without evidence is `UNSCORED`, per
the master prompt's rule that a guessed number is worse than no number.

Evidence classes: `VS` = verified in source, `VT` = verified in test/CI,
`VR` = verified in non-production runtime (this machine), `VP` = production
read-only. Full inventory with per-claim statuses: `current-state.md`.

## Topology verdict

**Modular monolith — matches the master prompt's default direction.** One
FastAPI service + ARQ workers (Redis, inline mode in tests), enforced layer
boundaries via import-linter (5 contracts, CI):
`db` is a leaf; `retrieval`/`providers`/`nctb` never reach up into
`services`; evaluation is offline tooling. The master prompt's candidate
module map maps onto the real tree as: identity → `auth.py`/routers,
curriculum+corpus → `nctb/`+`curriculum/` (PEP-420 namespace, deliberate),
ingestion → `nctb/` + workers, retrieval → `retrieval/`, tutor →
`services/tutor.py`, grounding → `services/tutor.py` gate + citation check,
evaluation → `evaluation/` (import-linter-isolated), platform →
`config.py`/`db/`/`initialize/`. No needless re-packaging proposed.

**No speculative rewrite is included in this pass** — no new framework,
database, queue, or vector store. Every recommendation below is either a
measured no-op confirmation or an owner-decision escalation.

## Scorecard

| Dimension | Score | Evidence | Severity / action |
| --- | --- | --- | --- |
| Correctness / data integrity | 4 | 42-table schema w/ real role CHECK; 36-migration chain; append-only audit; retention sweep tests (14 pass) [VS/VT] | Medium: vocabulary invariants are comment-only (flagged for future schema-hardening migration) |
| Retrieval / answer quality | 3 | Hybrid BM25∥dense + RRF + gate; sweep 24 cells identical (0.808/0.9951); R@1 0.87 vs 0.95 resolved as corpus-revision effect, taxonomy documented [VT/VR] | High (quality, not defect): 20.2% false-refusal rate on answerable items is measured but unimproved — needs corpus-bound golden labels (owner) |
| Latency / performance | 3 | e2e INP budget pass; traces 27–82 ms hermetic; throttled perf specs pass in CI; 2 long-task specs skip locally (windowing absent) [VR/VT] | Medium: transcript windowing is a known-open frontend item |
| Availability / resilience | 4 | Provider fallback + circuit breaker; SSE error envelope parity (S8); retry-recover e2e; kill switch [VT/VR] | Low |
| Scalability / capacity | UNSCORED | No capacity model exists; single-host SQLite production is documented [VP] | Medium: owner decision, not this pass |
| Security / privacy / safeguarding | 4 | Argon2id, Fernet PII, hashed tokens, egress redaction metered, boot guards, 48 redteam/injection tests; S7 egress hardening [VT/VS] | High residual: safeguarding escalation is a proposal, no owner-approved human process; no DPIA |
| Maintainability / modularity | 4 | import-linter 5 contracts enforced in CI; routers by domain; deps aliases [VT] | Low |
| Testability | 5 | 252 API test files, hermetic eval CLI, no-retry e2e discipline, 213/0 local e2e [VT/VR] | Low |
| Observability / operability | 3 | Structured redacted logs, token-gated /metrics, trace store; no OTel tracing across stages; tunnel fragility documented [VS/VP] | Medium: alerting/on-call path unexercised |
| Deployability / rollback | 3 | Rollback runbook exists; rollback kept as stopped container; live path unexercised end-to-end; backup docs describe Postgres but live runs SQLite [VP] | High gap: restore untested (documented in AGENTS §15) |
| Cost / operational complexity | 3 | Local embedder = zero marginal model cost; Docker single host; no provider spend without owner config [VS] | Low |

## Prioritized findings (all carried from evidence; no new code this phase)

1. **[High, owner] False-refusal rate 20.2%** on answerable golden items
   (82/406). Any published "refusal quality" claim must carry this split.
   Improvement requires corpus-bound golden labels — fabrication is
   prohibited; owner decision.
2. **[High, owner] Restore/DR unexercised** on the live SQLite topology; no
   `psql`/`sqlite3` locally to rehearse. Documented as known gap, not
   silently claimed.
3. **[High, owner] Safeguarding escalation** is a proposal without an
   approved human process — children's-product blocker for any GO without
   explicit risk acceptance.
4. **[Medium, eng] Real-corpus retrieval eval suite missing** — the golden
   gate is sample-bound; neighbor expansion and any future reranker change
   are unmeasurable against real content until labels exist.
5. **[Medium, eng] No OTel stage-level tracing** — retrieval stage timings
   exist in logs; cross-stage trace correlation absent. Proposal only.
6. **[Low, eng] Vocabulary invariants comment-only** (quiz status, content
   sources, audit action) — future schema-hardening migration.

## ADRs

Material decisions from this pass that needed ADRs are drafted in
`adr-drafts.md` (retention-sweep wording, SSE refusal-envelope parity,
neighbor-expansion default, X-02 return-path policy, reranker egress guard,
non-Bangla exclusion). Existing decision records live in
`docs/adr/ADRs.md`; no conflict found with any of the drafts.
