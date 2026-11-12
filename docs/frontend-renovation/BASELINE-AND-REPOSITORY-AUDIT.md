# Baseline and Repository Audit — Bangla GPT frontend renovation

Captured 2026-11-11. All figures below were produced by the commands shown; nothing is
carried over from prior documents without re-measurement.

## 1. Environment (measured)

| Item | Value | How measured |
|---|---|---|
| OS | win32 10.0.26300 x64 | host |
| Shell | Git Bash (`git version 2.55.0.windows.5`) | `git --version` |
| Node | `v24.19.0` | `node --version` — matches `.nvmrc` = 24 and `engines.node` `>=24 <25` |
| npm | `11.17.0` | `npm --version` — matches `engines.npm` `>=11` |
| Python | 3.12.10 at repo-root `.venv/Scripts/python.exe` | `pyvenv.cfg`; satisfies `requires-python >=3.11` |
| Web deps | installed (`apps/web/node_modules`) | dir exists |
| Playwright browsers | `chromium-1243`, `chromium-1248`, `firefox-1543/1555`, `webkit-2359/2370` | `%LOCALAPPDATA%/ms-playwright` |
| Android SDK / `java` / `gradle` / `adb` | **absent** | `AGENTS.md` §13 states no local Android builds; not re-attempted |

**Android is blocked by design on this machine, not by this task.** Per the master prompt
§10.3 and §17.6, that means this delivery cannot carry a `COMPLETED — VERIFIED` verdict that
includes native verification, and browser viewport emulation must never be reported as
emulator or device testing.

## 2. Repository identity and safety

| Check | Result |
|---|---|
| Working directory | `C:\Users\DST\projects\Bangla GPT APP` |
| Remote | `https://github.com/tanviruchahs2580/Bangla-GPT-APP.git` |
| Branch | `main`, tracking `origin/main` |
| HEAD at start | `03dfe21b6f90bc27ca476bfa459318a14bf3d266` ("Merge pull request #108 from tanviruchahs2580/chore/release-0.10.0") |
| `git status --short --branch` | `## main...origin/main` — **clean, no staged/unstaged/untracked files** |
| Owner work at risk | none — the tree was clean at start, so no owner modification needed preserving |

No destructive command was run at any point: no `reset --hard`, no `clean -fd`, no forced
checkout, no branch switch, no history rewrite, no push, no merge, no tag, no release.

A local dev API was already running on `127.0.0.1:8000` when browser QA began. It was
**not restarted or reconfigured**; it was identified as this project's API via
`GET /health`, `/live` and `/status` before anything touched it.

## 3. Baseline quality gates (before any product edit)

Exact command sequence and full log:
`docs/frontend-renovation/evidence/test-results/baseline-gates.log`

| # | Gate | Command (from `apps/web`) | Result | Exit |
|---:|---|---|---|---:|
| 1 | Format | `npm run format:check` | PASS — all files use Prettier style | 0 |
| 2 | Lint | `npm run lint` (`eslint src --max-warnings 0`) | PASS — zero warnings | 0 |
| 3 | Unit/component | `npm run test` (vitest, guarded by `check_vitest_ran.mjs`) | **113 test files, 479 tests, all passed** | 0 |
| 4 | Build | `npm run build` (`tsc && vite build`) | PASS — 2742 modules, built in 12.63 s | 0 |
| 5 | Dead code | `npm run deadcode` (knip) | PASS | 0 |

**No baseline failures existed in the web gate set.** Nothing in this renovation can be
excused as pre-existing red.

### 3.1 Baseline build artefacts (performance reference points)

| Artefact | Raw | gzip |
|---|---:|---:|
| `assets/index-*.js` (app entry) | 339.59 kB | **112,989 B** |
| `assets/safeMarkdown-*.js` (KaTeX, lazy) | 395.69 kB | 120.28 kB |
| `assets/index-*.css` | 78.45 kB | 15.79 kB |
| `assets/safeMarkdown-*.css` (KaTeX, lazy) | 30.26 kB | 8.10 kB |
| `AITutorPage-*.js` (largest route) | 22.30 kB | 7.77 kB |

The build declares its own budget via a `bundle-budget` plugin, visible in the build log:
the app entry has a **125,000 B gzip ceiling and sat at 112,989 B — 90.4 % of budget.**
That is a hard constraint on this renovation: the entry chunk must not grow.

### 3.2 Baseline build warning — the finding that started the audit

The baseline build emitted exactly one warning, and it was non-fatal:

```
warnings when minifying css:
▲ [WARNING] Unexpected "*" [css-syntax-error]
    <stdin>:3048:6:
      3048 │ .stat-*/.table-wrap
           ╵       ^
```

The emitted CSS contained this as a single selector list:

```css
.stat-*/.table-wrap names above. --------- */ .page-title{font-size:var(--fs-2xl);…}
```

Cause: a block comment in `styles.css` ended early. Line 3059 read
`defaults. New markup should prefer the .btn-*/` — the `.btn-*` followed by `/` formed a
closing `*/`, so everything after it became live CSS. See `DESIGN-DIRECTION.md` D-… and
`REGRESSION-AND-INDEPENDENT-REVIEW.md` for the fix and its measured severity.

Because esbuild only *warns*, this shipped. It is recorded here as a **baseline defect that
existed before the renovation**, not as a regression introduced by it.

## 4. Measured baseline of the accessibility guards

Two token-contract guards read `apps/web/src/styles.css`, and both located their token block
with `indexOf`:

```ts
const LIGHT = parseBlock(CSS, ":root {");
const DARK  = { ...LIGHT, ...parseBlock(CSS, '[data-theme="dark"] {') };
```

`styles.css` declares **four** token blocks (`grep -nE '^\s*(:root|\[data-theme)'`):
`:root` (line 9), `[data-theme="dark"]` (196), `:root` (3885), `[data-theme="dark"]` (3909).

`indexOf` resolves to the first match of each, so the second pair was outside every ratio
assertion in the repository. Measured difference: the guards saw **99 light / 40 dark**
tokens; parsing every block yields **110 light / 46 dark**.

Independent, reproducible measurement of the consequence:
`docs/frontend-renovation/evidence/accessibility/contrast_audit.py` (exit 1 at baseline).

| Pair | Required | Measured (baseline) | Verdict |
|---|---:|---:|---|
| `.hero .home-prompt .input::placeholder` on its literal `rgba(255,255,255,.96)` fill over `--grad-hero` | 4.5:1 | **4.24 / 4.31 / 4.28** across the three gradient stops | **FAIL** |
| `.ring` track, `color-mix(--line 70%)` over `--card`, light | 3:1 | **1.21:1** | **FAIL** |
| `.ring` track, dark | 3:1 | **1.16:1** | **FAIL** |
| `ok` on `ok-soft` (light / dark) | 4.5:1 | 6.32 / 6.95 | pass, **unguarded** |
| `warn` on `warn-soft` | 4.5:1 | 5.56 / 8.12 | pass, **unguarded** |
| `danger` on `danger-soft` | 4.5:1 | 5.14 / 5.54 | pass, **unguarded** |
| `teal-strong` on `teal-soft` | 4.5:1 | 5.17 / 7.85 | pass, **unguarded** |
| `ai` on `ai-soft` | 4.5:1 | 5.62 / 5.36 | pass, **unguarded** |
| `muted` on `card` / `bg-elev` / `card-2` / `bg` | 4.5:1 | 5.03–5.67 / 6.66–7.91 | pass, **unguarded** |

"Unguarded" means no assertion covered them *before* this renovation, so a palette change
could have moved them silently.

## 5. Not measured, and why

- **No field Core Web Vitals.** No RUM source exists in this repository, and no production
  traffic was touched. Every performance number produced by this work is lab-only and is
  labelled as such in `PERFORMANCE-REPORT.md`.
- **No Android emulator or device run.** See §1.
- **No user research, interviews or usability testing.** None was performed and none is
  claimed; the design review in `VISUAL-QA-REPORT.md` is a transparent heuristic review.
- **No authenticated manual browser session was driven by hand.** The fixture password was
  deliberately not placed into any command line or transcript; authenticated verification
  runs through the project's own Playwright harness, which holds the credential in
  `e2e/a11y.ts`.
