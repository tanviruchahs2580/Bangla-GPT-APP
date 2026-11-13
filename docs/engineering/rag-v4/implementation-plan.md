# Implementation plan — RAG V4 readiness execution record (V4 Phases 6/8/9)

Date: 2026-11-13 · Branch `feat/bangla-gpt-rag-v4-readiness`

This is the execution sequence that WAS followed on this branch (what the
master prompt calls an approved/safe sequence), with each item's gate, and
the owner decisions that were *escalated, not assumed*.

## Executed sequence (all committed)

| # | Step | Gate that had to pass | Commit |
| --- | --- | --- | --- |
| 0 | Repo identity, current-state inventory, source registry, R@1 investigation | every claim status-tagged; no unverified assertion | `9de07ec` |
| 1 | S1 X-02: canonical return-path policy on every /login bounce | web unit + e2e; no weakening of existing e2e | `06e6abc` |
| 2 | S2 ingestion resource caps (untrusted PDF path) | new pytest suite; lint/mypy on touched files | `40bde1a` |
| 3 | S3–S6 loud non-Bangla exclusion, subject redaction in logs, rebuild idempotence | pytest suites; doc drift corrected in same change | `e18b00b` |
| 4 | S7 reranker egress guard (refuse cleartext endpoints) | pytest; dormant-path coverage ≥ 96.7% floor intact | `33b389f` |
| 5 | S8 SSE error frames carry `refused_reason` (parity with JSON envelope) + vision-refusal confidence pin | SSE contract tests; web client confirmed unchanged (`{__error, ...data}` spread) | `e06d784` |
| 6 | S9 data-minimization doc refreshed to actual retention sweep | 14 retention tests re-run; `config.py:329` cited | `ddfb115` |
| 7 | Phase 3: eval-CLI neighbor-expansion wiring fix, then measured A/B | identity-bound golden gate, both legs ALL GATES PASS; bootstrap CI vs committed baseline | `aa3d7be` + `8512918` |
| 8 | Phase 4: 3-question end-to-end traces with evidence ids | trace store non-empty; refusal honest (empty sources) | `ad4c79e` |
| 9 | Phase 7: 13-step user journey, full Playwright suite on 8010/5273 | 213 passed / 14 skipped-by-design / 0 failed, 56.2 min | `49d4340` |
| 10 | Governance artifacts (this file, architecture-review, baseline-manifest, evidence-ledger, ADR drafts, SLO proposal) | measured fingerprints only; no guessed numbers | this commit |

## Deliberate non-actions (safe = not doing them without approval)

- **No flag flip.** `RAG_NEIGHBOR_EXPANSION` stays `false`: measured
  structural no-op on the sample-bound golden gate; real-corpus A/B is an
  owner decision needing corpus-bound labels that do not exist.
- **No baseline regeneration.** `baseline_v3.json` untouched — the pass ran
  *against* it; regenerating to make a change pass is prohibited.
- **No embedder/model change.** HashingEmbedder stays; real-model selection
  is owner-decision + manifest-breaking.
- **No retention/consent/helpline edits.** Windows, consent version and
  pinned helpline numbers untouched.
- **No production deploy from this branch.** Merge/PR discipline is the
  next terminal step; deployment remains Amber.

## Owner decisions escalated (each with exact requirements)

1. **Real-corpus golden labels** (unblocks: neighbor expansion A/B, reranker
   evaluation, false-refusal work). Requires: qualified Bangla-speaking
   educator review, per-item provenance, dataset version increment, held-out
   partition kept separate.
2. **Safeguarding escalation process** (children's-product blocker). The
   proposal in `docs/ai/incident-response.md` needs owner approval + named
   responder + tested contact path before any GO without risk acceptance.
3. **Restore/DR rehearsal** for the live SQLite topology. Requires a
   non-production restore test and consistency validation (DB ↔ manifest ↔
   index ↔ citation lineage); currently no local client tooling.
4. **SLO commitments** (see `slo-proposal.md`) — proposals only; owner
   approval required before they become commitments with alerting.
5. **Cross-encoder reranker enablement** — external endpoint + model =
   Amber per the authority matrix; also needs egress allowlist decision
   (residual from S7).
6. **Transcript windowing** (`MESSAGE_WINDOW`) — frontend perf item gating
   2 skipped long-task specs; scoped as its own frontend wave.

## Gate summary for the PR

- API: pytest suites on all touched files green; ruff/ruff-format clean;
  mypy clean on touched files. Full-suite local run: 2218 pass + 1
  documented stale-dist-metadata red (green in CI).
- Web: unit + coverage floors green; knip green; build green; e2e 213/0.
- Eval gate: identity-bound golden gate ALL GATES PASS on both Phase-3 legs.
- No gate weakened, skipped, or annotated away anywhere in this branch.
