# Performance Report — Bangla GPT frontend renovation

**All figures in this file are lab measurements.** No field / RUM data exists for this
product, none was collected, and no lab number here may be presented as a field P75
(the master prompt §12.1 forbids exactly that). Nothing in this file supports a
national-scale capacity or reliability claim.

---

## 1. Measurement conditions

| Item | Value |
|---|---|
| Machine | developer workstation, win32 10.0.26300 x64 |
| Node | v24.19.0, npm 11.17.0 |
| Build | `npm run build` (`tsc && vite build`), Vite 5.4.21, production mode |
| Tested commit | baseline `03dfe21` + the uncommitted working-tree changes described in `FINAL-DELIVERY-REPORT.md` |
| Network | not throttled — this is a local build-size and build-time measurement, not a load test |
| Lighthouse | **not run in this delivery** — `lighthouserc.json` thresholds are reproduced below for context only |

## 2. Bundle measurements — the constraint that shaped this work

The build declares its own budget through a `bundle-budget` Vite plugin, and it prints the
comparison on every build. The relevant line at baseline:

```
assets/index-DSLPKL17.js: 112989 B gzip / 125000 B (app entry)
```

**The app entry was at 90.4 % of its own ceiling before this renovation began.** That is a
hard constraint, not a preference: any change that pushes the entry chunk past 125,000 B
gzip fails the build.

Consequence for this work: **no dependency was added, no new module was imported into the
entry graph, and no code was added to the entry chunk.** The four behaviour-bearing fixes
touch components already in their routes' graphs (or add a few hundred bytes to a lazy route
chunk), and the new `cssTokens.ts` is a test-only module that never reaches the bundle.
Every route chunk sits far below its own 110,000 B allowance, so the budget model is not
under pressure from anything here.

### 2.1 Baseline bundle (before)

| Artefact | Raw | gzip | Budget | Head-room |
|---|---:|---:|---:|---:|
| `assets/index-*.js` — app entry | 339.59 kB | **112,989 B** | 125,000 B | 9.6 % |
| `assets/safeMarkdown-*.js` — KaTeX, lazy | 395.69 kB | 120.28 kB | route 110,000 B | — |
| `assets/index-*.css` | 78.45 kB | 15.79 kB | 160,000 B (Lighthouse) | 51 % |
| `assets/safeMarkdown-*.css` — KaTeX, lazy | 30.26 kB | 8.10 kB | — | — |
| `assets/AITutorPage-*.js` — largest route | 22.30 kB | 7.77 kB | 110,000 B | 93 % |
| `assets/LearnPage-*.js` | 19.60 kB | 6.42 kB | 110,000 B | 94 % |
| `assets/CreatePage-*.js` | 20.19 kB | 5.81 kB | 110,000 B | 95 % |
| Total JS + CSS | ~1.03 MB raw | ~290 kB gzip | 2,000,000 B (Lighthouse) | 85 % |

Route-level code splitting is genuinely in place: 49 separate route chunks were emitted,
including 306–423 B chunks for single icons (`chevron-left`, `check`, `trash`, `sparkles`,
`bot`, `timer`) — so Lucide icons are being tree-shaken per route rather than shipped as one
icon bundle. Lazy loading is real, not nominal.

### 2.2 CSS weight problem, recorded not fixed

`index-*.css` is 78.45 kB raw / 15.79 kB gzip from a **single 5,156-line stylesheet with no
splitting**. That is a lot of CSS to ship on first paint for an app where most users touch one
role's surfaces. It is also the direct cause of the duplication recorded in
`DESIGN-SYSTEM-SPEC.md` §7.1 (two button vocabularies, three stat layouts, `.card` and
`.hero` and `.ring` each declared twice).

The fix is the deferred Wave 3 consolidation, which is a component-migration project rather
than a minification project — minifying harder would not remove a single duplicate rule.

## 3. What this renovation changed about performance

**Nothing, deliberately — and that is a finding, not an omission.**

Every change in this delivery is one of: a token value, a duplicated declaration removed, an
attribute on an existing rule, a copy string, an element type, or a state flag that renders a
message. None of them adds a request, a dependency, a listener, a timer, a re-render, or a
route. The predicted effect on load and interaction metrics is **zero**, and because it is
zero there is no before/after improvement to claim.

The master prompt §12.2 says to "optimise only observed bottlenecks" and forbids claiming an
improvement without comparable before/after measurement. No bottleneck was observed at the
component/route level by the measurements above, so none was optimised, and no improvement is
claimed.

### 3.1 Measured side benefits (small, and stated as such)

| Change | Effect |
|---|---|
| R-08 (`.page-title` rule restored) | The invalid selector no longer ships. esbuild's CSS warning count went **1 → 0**. Byte effect is negligible. |
| R-10 (`--glass-bg` dead override removed) | One declaration removed. Negligible. |
| R-07 (reduced motion) | For users with `prefers-reduced-motion`, collapsing `infinite` loops to a single iteration **removes** ~1000 restarts/second of prior animation work. This is a real saving for that cohort on low-end Android devices, where continuous composited animation is the expensive part. Not measured — asserted from the CSS semantics. |
| R-05 (ring track) | `color-mix()` replaced by a plain token. `color-mix` is computed once at parse time, so the practical difference is nil. |

## 4. The CI Lighthouse budget (unchanged, reproduced for reference)

From `apps/web/lighthouserc.json`, all assertions `error`:

| Assertion | Threshold |
|---|---:|
| `categories:performance` | ≥ 0.5 |
| `largest-contentful-paint` | ≤ 4,000 ms |
| `cumulative-layout-shift` | ≤ 0.1 |
| `total-blocking-time` | ≤ 3,000 ms |
| `resource-summary:script:size` | ≤ 1,200,000 B |
| `resource-summary:stylesheet:size` | ≤ 160,000 B |
| `resource-summary:font:size` | ≤ 700,000 B |
| `resource-summary:total:size` | ≤ 2,000,000 B |

These are **CI's** gates, run against `staticDistDir: ./dist`. This delivery did not re-run
them; they will run on whatever CI job picks up the change. Note that a `categories:performance ≥ 0.5`
floor is a permissive bar — passing it would not demonstrate that the app is fast, only that
it is not catastrophic.

Separately, the repo's own README for the serve helper is **stale**: `e2e/serve_for_audit.mjs`
claims `lighthouserc.json` uses it as `startServerCommand` and that `npm run audit:serve`
exists. Neither is true any more (the config uses `staticDistDir`, and no `audit:serve`
script exists). Recorded as documentation drift; not changed here.

## 5. Not measured — explicitly

| Metric | Status | Why |
|---|---|---|
| **Field LCP / INP / CLS (p75)** | **UNAVAILABLE** | No RUM source in the repository or the product. Any p75 figure would be invented. |
| Lab LCP / INP / CLS | **NOT RUN** | Lighthouse was not executed in this delivery. |
| Long tasks / unnecessary re-renders | **NOT MEASURED** | No profiling session was run. |
| Long-conversation streaming / scroll / memory | **NOT MEASURED** | `e2e/w2-perf.spec.ts` and `e2e/perf.spec.ts` exist and are partly gated behind `E2E_PERF=1` / `E2E_WEB=preview`; they were not executed here. |
| Font loading behaviour | **PARTIAL** | Weights are asserted against the two loaded faces (400/700). Byte weight was not re-measured beyond the build budget output. |
| Data-heavy table rendering at scale | **NOT MEASURED** | The admin table is 20 rows/page; the school students table fetches 100 rows on page 1. Neither was profiled. |
| Network throttled / slow-3G behaviour | **NOT MEASURED** | Not run. The offline/PWA specs exist and were not part of this run. |

## 6. Honest summary

Bundle weight is **unchanged** by this renovation, and the app-entry ceiling that was already
90.4 % consumed remains the single biggest constraint on any future frontend work. The only
performance-relevant improvement is for reduced-motion users, and it is a correctness fix
that happens to save work rather than an optimisation.

**No improvement is claimed, and none should be inferred from this document.**
