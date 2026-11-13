# Execution log — RAG V4 readiness pass (append-only)

Format: date · phase · summary · evidence pointer. One entry per completed
unit of work; later entries never rewrite earlier ones.

- 2026-11-13 · Phase 0 · Branch `feat/bangla-gpt-rag-v4-readiness` created
  from `main`@`2731a4a`; repo identity confirmed (two-app monorepo, no root
  manifest, 42 tables, 19 router files). Evidence: current-state.md.
- 2026-11-13 · Phase 1 · 20 owner-reported handoff claims verified; none
  CONTRADICTED; two semantically refined (sweep 0.2412 = all-gate-refusals
  incl. 20.2% false-refusal split; R@1 0.87-vs-0.95 = different corpus
  revisions, code contributes zero). Evidence: current-state.md §0.1,
  r1-regression-investigation.md, scripts/diagnose_family_a.py.
  Commit `9de07ec`.
- 2026-11-13 · Phase 2 (S1) · X-02 fixed: canonical return-path policy,
  `?next=` preserved on every /login bounce, hostile destinations rejected.
  Commit `06e6abc`.
- 2026-11-13 · Phase 2 (S2) · Resource caps on untrusted-PDF parse path.
  Commit `40bde1a`.
- 2026-11-13 · Phase 2 (S3–S6) · Loud non-Bangla exclusion; subject
  redaction in logs; corpus rebuild idempotence. Commit `e18b00b`.
- 2026-11-13 · Phase 2 (S7) · Cleartext reranker egress refused; redactor
  at the only production construction site. Commit `33b389f`.
- 2026-11-13 · Phase 2 (S8) · SSE error frames carry `refused_reason`
  (JSON-envelope parity); vision-refusal confidence pinned 0.0.
  Commit `e06d784`.
- 2026-11-13 · Phase 2 (S9) · data_minimization.md re-verified against the
  retention sweep and corrected (no policy change). Commit `ddfb115`.
- 2026-11-13 · Phase 3 · Eval-CLI flag-consumption defect found via
  byte-identical pilot runs; expander wired (`aa3d7be`); measured A/B both
  legs ALL GATES PASS, no-op proven structural (0 multi-chunk buckets in
  sample corpus). Commit `8512918`.
- 2026-11-13 · Phase 4 · 3-question traces with evidence ids: grounded,
  Banglish-transliteration lane, honest refusal. Commit `ad4c79e`.
- 2026-11-13 · Phase 7 · Full Playwright suite on 8010/5273: 213 passed,
  14 skipped (all conditional-by-design), 0 failed, 56.2 min; all 13
  master-prompt journey steps mapped to passing specs. Commit `49d4340`.
- 2026-11-13 · Phases 6/8/9 · Governance artifacts written with measured
  fingerprints only: baseline-manifest.json (manifest/golden/redteam
  hashes, runtime pins), evidence-ledger.jsonl (13 append-only entries),
  architecture-review.md (11-dimension scorecard, 2 dimensions UNSCORED
  where no evidence exists), implementation-plan.md (executed sequence +
  6 escalated owner decisions), adr-drafts.md (6 drafts), slo-proposal.md
  (7 SLI + 5 alert proposals, all PROPOSED). This commit.
