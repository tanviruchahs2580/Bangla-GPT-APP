# User-journey E2E — 13-step validation (V4 Phase 7)

Date: 2026-11-13 · Branch: `feat/bangla-gpt-rag-v4-readiness`

## Execution

Full Playwright suite, local run (not CI), harness-managed servers on the
mandated local ports **`E2E_API_PORT=8010`, `E2E_WEB_PORT=5273`** (5173
belongs to a sibling project's dev server; `strictPort` keeps the override
loud). The harness seeded a throwaway SQLite DB outside the repo, booted the
real API (`ENV=test`, `LLM_PROVIDER=mock`, inline jobs) and the real web dev
server, and asserted the served app is this product (`00-identity.spec.ts`).

Command: `cd apps/web && E2E_API_PORT=8010 E2E_WEB_PORT=5273 npx playwright test`

**Result: 213 passed, 14 skipped, 0 failed — 56.2 min, exit 0** (two
projects: `chromium` desktop + `mobile-chromium` Pixel 5).

## Step → evidence map (master prompt §10.1)

| # | Step | Evidence (all PASSED unless noted) |
| --- | --- | --- |
| 1 | Login with existing supported flow | `smoke.spec.ts` student/teacher/admin sign-in; `qa-flows ANON-04` wrong-credential refusal; `keyboard.spec` login via Enter alone |
| 2 | Session restoration and expiration | `w2-flows X-02` near-expiry token renews, expired forces re-login, tabs survive; `session.spec` stale token rejected; `w2-session` logout clears cache/storage/offline copies |
| 3 | Class/subject/book/chapter selection | `w2-c1-flows STU-11` reader chapter opens, bookmark/font persist; `STU-12` unified search over the corpus |
| 4 | Questions in Bangla, Banglish, English, mixed | `w2-c1-flows STU-12` three Bangla surface forms → same hits; `STU-17` five question variants settle grounded/refused; smoke streamed answer |
| 5 | Loading/streaming and cancellation | `w2-flows STU-04` tokens grow, **Stop aborts**, **mid-stream failure is recoverable**, Bangla text intact; `resilience` slow-API skeletons; `perf.spec` 120-message thread at 4x throttle (SKIPPED, see below) |
| 6 | Answer rendering and formatting | `screen-reader` completed streamed answer announced exactly once; `visual.spec` 72 snapshot variants of student-tutor etc. all pass |
| 7 | Citation labels, source metadata, safe navigation | `STU-17` **citations match the corpus**; `keyboard.spec` evidence dialog traps and restores focus; `w2-a11y` evidence/ask-tab labelled + axe clean |
| 8 | Follow-up behavior and context handling | `w2-flows STU-18` follow-up stays grounded, **New chat leaks no earlier context**; `STU-03` second turn stays in-thread |
| 9 | History and persistence | `qa-flows STU-03` history survives reload and re-login, New chat clears it; `seed_long_history` + `perf` heap check |
| 10 | Network interruption, retry, timeout, recovery | `resilience` failing API → actionable message → **retry recovers**; offline banner; slow-3G flows complete; `w2-perf` INP budget under login+tutor |
| 11 | No-result, ambiguity, refusal, fallback UX | smoke **out-of-corpus refusal with the grounding message** (no fake citations); `w2-c1 STU-06` unsafe prompt → supportive refusal, nothing harmful stored; `ADM-08` safety audit records refusal without content |
| 12 | Logout, invalidation, authorization boundaries | `crawl` each role denied other roles' home (guard, not styling); `SAD-03`/`PAR-04` cross-tenant/cross-child ID access denied; `ADM-05` impersonation bounds + revoke; `X-11` kill switch |
| 13 | Mobile viewport, keyboard, scrolling, input | `mobile-chromium` project (Pixel 5): bottom-nav ≥44px targets, **student asks the tutor and gets an answer on mobile**; `keyboard.spec` tab order + visible focus; `reflow.spec` no overflow at named widths + 200% text resize |

## The 14 skips — each conditional by design, none a failure

| Spec | Skip reason (from the spec's own code) |
| --- | --- |
| `offline-shell` (2) + `w2-session` SW-cache (1) | service worker exists only in the production build; these need `E2E_WEB=preview` |
| `perf.spec` 2 long-task tests | transcript windowing (`MESSAGE_WINDOW`) absent on this branch; `E2E_PERF=1` measures the current worst task |
| `w2-perf` Slow 3G + 4x | needs the production-bundle harness (`E2E_WEB=preview`); dev module graph can't fit the interactivity budget under throttle |
| `store-listing` (8) | asset regeneration is opt-in (`STORE_ASSETS=1`) |

## Honest limits of this pass

- **Mock provider.** `LLM_PROVIDER=mock` — every "streamed answer" is the
  deterministic mock; the journeys validate streaming/citations/refusal
  *plumbing*, not live-model answer quality. Live-model behaviour remains
  the UNVERIFIED-LIVE class recorded elsewhere in the V4 ledger.
- **Dev harness, not preview.** The 3 service-worker specs and 3
  throttled-interactivity specs are unexercised here; they pass in CI's
  preview leg (last known green), not re-run locally in this pass.
- **Chromium-family only locally.** Firefox/WebKit live in
  `playwright.engines.config.ts` (CI); not run in this local pass.
- Accessibility conformance here = the repo's own standard (axe
  serious/critical = 0 across theme×language variants, keyboard,
  screen-reader baselines) — not a new external audit.
