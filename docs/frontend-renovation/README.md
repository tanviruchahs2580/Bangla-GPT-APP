# README — Frontend renovation evidence bundle (Bangla GPT)

**Started:** 2026-11-11 · **Repository:** `Bangla-GPT-APP` · **Branch:** `main`
**Baseline commit:** `03dfe21b6f90bc27ca476bfa459318a14bf3d266` (release 0.10.0 merge)
**Worktree at start:** clean — no staged, unstaged or untracked files.
**Changes are uncommitted.** No commit, push, merge, tag, release or deploy was performed.

If you have the delivery: read **`FINAL-DELIVERY-REPORT.md`**. For the two-minute version,
**`EXECUTIVE-SUMMARY.md`**. For what went wrong and how it was caught,
**`REGRESSION-AND-INDEPENDENT-REVIEW.md`**.

---

## Verdict

**`PARTIALLY COMPLETED — BLOCKERS REMAIN`.**

Fifteen substantiated defects were fixed, four of them found only by the independent review
pass — including two that I introduced and one I had mis-reported as passing. Every static
gate is green after a clean, uncontended run. All 68 browser tests pass (8 smoke journeys +
60 visual baselines). Three planned consolidation waves were deliberately deferred rather
than half-verified, and the full per-feature functional matrix was not executed.

`FINAL-DELIVERY-REPORT.md` quantifies exactly what is proven and what is not. No
`COMPLETED — VERIFIED` claim is made, and no national-scale-readiness claim is made at all.

---

## Documents

| File | What it is |
|---|---|
| `EXECUTIVE-SUMMARY.md` | Two-minute read: verdict, what changed, what is proven, what is not |
| `FINAL-DELIVERY-REPORT.md` | Full report: findings, evidence tables, coverage counts, limitations, handover |
| `REGRESSION-AND-INDEPENDENT-REVIEW.md` | **Read this one.** Independent findings and their dispositions, including the defects I introduced |
| `BASELINE-AND-REPOSITORY-AUDIT.md` | Environment, repo safety, the five baseline gates, measured baseline defects |
| `ROUTE-AND-PAGE-INVENTORY.md` | 25 routes, the `RequireAuth` decision order, responsive archetypes |
| `FEATURE-LOCK-REGISTER.md` | ~200 capability rows with `file:line` + 12 untouchable cross-cutting contracts |
| `USER-JOURNEY-MATRIX.md` | Per-role journeys: entry, task, states, permission boundary, honest coverage status |
| `DESIGN-DIRECTION.md` | The direction, rejected alternatives, measured problems, honest unknowns ledger |
| `DESIGN-SYSTEM-SPEC.md` | Token source of truth, guarded ratios, known limits, deferred consolidation |
| `COMPONENT-INVENTORY.md` | Primitives and contracts, plus the recorded duplication |
| `CONTENT-AND-TERMINOLOGY.md` | The three new strings, the Bengali rules, unresolved terminology |
| `IMPLEMENTATION-PLAN.md` | Waves, slice acceptance, deferred work with reasons, rollback |
| `RISK-REGISTER.md` | `R-01`–`R-24`: fixed / preserved-pending-owner / carried risks |
| `TEST-STRATEGY-AND-MATRIX.md` | Test estate, change→test matrix, coverage denominators, repro commands |
| `FEATURE-PARITY-REPORT.md` | The parity table with real counts, and what was not run |
| `VISUAL-QA-REPORT.md` | Browser verification per fix, visual-baseline reading, rubric scores |
| `ACCESSIBILITY-REPORT.md` | WCAG-oriented results: measured vs reasoned, with the limits named |
| `PERFORMANCE-REPORT.md` | Lab-only bundle and build measurements; field data marked unavailable |
| `FRONTEND-SECURITY-REVIEW.md` | Security/privacy review of the diff, incl. the children's-data angle |
| `TOOLING-INVENTORY.md` | Skills / plugins / MCP / subagents used, with installed-vs-invoked-vs-verified separated |
| `EXECUTION-LOG.md` | Chronological log: what was run, what it returned, what was decided |

`decisions/` is empty and is documented as such: no architectural decision record was needed,
because nothing in this delivery changed architecture, dependencies, routing or data flow.

## Evidence

| Path | Contents |
|---|---|
| `evidence/test-results/baseline-gates.log` | The pre-edit gate run (format, lint, 479 tests, build, knip) |
| `evidence/test-results/final-gates.log` | The post-change clean run — the authoritative one |
| `evidence/accessibility/contrast_audit.py` | Reproducible WCAG audit reading real token values; exit 1 on a breach |
| `evidence/browser-console-network/invalid-selector-repro.html` | Minimal repro of the dropped-rule defect (R-08) |
| `evidence/final/01-login-bn-light-1440.png` | Post-change login capture, read back and inspected |
| `evidence/baseline/`, `evidence/visual-diffs/` | **Empty, deliberately.** See `VISUAL-QA-REPORT.md` §6 — the visual comparison artefacts are the 60 tracked Playwright baselines under `apps/web/e2e/__screenshots__/`, not duplicates here. Recorded as an empty directory rather than left to look like an oversight |

Pre-existing UI evidence from earlier work lives outside this bundle at
`docs/uiux_renovation_evidence/` and is **not** claimed as evidence for this renovation.

## Reproduce

```bash
# Static + unit gates (from apps/web)
npm run format:check && npm run lint && npx tsc --noEmit && npm run test && npm run build && npm run deadcode

# The contrast audit, reading the real token values out of src/styles.css
.venv/Scripts/python.exe docs/frontend-renovation/evidence/accessibility/contrast_audit.py

# Browser tests. Run it SELF-CONTAINED: outside CI the harness sets
# reuseExistingServer:true, so anything already answering on the default API
# port is adopted AND ITS SEEDING IS SKIPPED — which silently produces
# "Email or password is incorrect" against real code.
cd apps/web && CI=1 E2E_API_PORT=8100 E2E_WEB_PORT=5273 npx playwright test --project=chromium smoke visual
```

## What this renovation is not

- Not a restyle. `DESIGN-DIRECTION.md` §3 rejects a new visual identity and explains why; the
  60 existing visual baselines stand as the approved targets for everything untouched.
- Not a feature release. No capability was added: the missing school-student pagination and
  the four unconfirmed destructive actions are recorded as recommendations, not implemented,
  because the feature lock names confirmations and submission behaviour explicitly.
- Not backend work. No API route, schema, migration, prompt, RAG threshold or configuration
  file was changed — verified against the diff by an independent reviewer.
- Not a national-scale claim. Frontend evidence cannot establish backend reliability, traffic
  capacity or operational readiness; none is offered.
