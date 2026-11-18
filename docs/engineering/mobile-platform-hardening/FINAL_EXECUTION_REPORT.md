# FINAL EXECUTION REPORT — mobile & platform hardening (vc206 · E5-2 · native assets · ResponsiveTable · DPIA · Cloudflare)

**Date:** 2026-11-18 · **Branch:** `feat/mobile-platform-hardening`
**Baseline:** `main` @ `d24719a2` · **Final:** `d6db8fb` (6 commits, 93 files, +3189/−716)

---

## 1. Executive summary and per-workstream status

| Workstream | Status | One-line outcome |
|---|---|---|
| A — vc206 Android device verification | **PASS (engineering) / BLOCKED (device rows)** | Back-button priority order implemented + tested; APK build/sync path verified; physical-device matrix requires owner hardware |
| B — E5 Font Phase 2 | **PASS** | `@fontsource` fully removed; 10 licensed WOFF2 self-hosted at stable URLs; critical face preloaded (fetched exactly once, zero third-party egress); fallback **measured**, not guessed |
| C — Status bar / splash / icons | **PASS (engineering) / BLOCKED (on-device rows)** | Two 7.x plugins integrated safely; Capacitor-template splash and white adaptive background defects fixed; 31 brand assets generated deterministically |
| D — ResponsiveTable | **PASS** | Shared component + 17/20 tables migrated in 4 batches; 3 documented exceptions; one empty-state gap fixed |
| E — DPIA | **DRAFT COMPLETE** | Evidence-first 20-section draft; Act 63 of 2026 verified against primary sources; stale legal premise corrected; all interpretations flagged for counsel |
| F — Cloudflare Workers | **DECISION COMPLETE** | RETAIN CURRENT PLATFORM; gateway PoC-only; FastAPI migration rejected on evidence; no PoC run (no account) |

**Overall: READY FOR OWNER DEVICE/LEGAL SIGN-OFF.** All engineering/CI gates pass
locally; what remains is explicitly human (physical device, signing, legal review,
vendor confirmations). This is **not** a production-ready claim.

## 2. Commits

1. `def8447` feat(web): vc206 back-button priority — keyboard, overlay, in-app history before exit
2. `5e7fdcb` feat(web): E5 phase 2 — self-hosted WOFF2, critical preload, measured fallback
3. `45f8eef` feat(web): native system UI + brand launcher assets (status bar, splash, adaptive icons)
4. `94c636d` feat(web): ResponsiveTable — shared accessible data-table surface, 17 tables migrated
5. `72e15a1` docs(privacy): DPIA draft (Act 63 of 2026)
6. `d6db8fb` docs(architecture): Cloudflare Workers feasibility

## 3. Change list (by area)

- **Native/back-button:** `src/lib/nativeBackButton.ts` (priority order: IME keyboard →
  topmost dismissible overlay → dirty-state confirm (quiz/streaming) → in-app history →
  root exit; single-listener guard), `AppShell.tsx` wiring, tests.
- **Fonts:** `public/fonts/` (10 woff2 + 2 OFL licences + README/SHA-256),
  `src/fonts.css` (new), `index.html` (preload), `styles.css` (`--font` stack),
  `main.tsx`, `apps/web/scripts/font_metrics.py`, `apps/web/scripts/verify_fonts.mjs`, package.json/lock.
- **Native assets:** `@capacitor/status-bar@7.0.6`, `@capacitor/splash-screen@7.0.5`,
  `capacitor.config.ts`, `src/lib/nativeSystemUi.ts`, `apps/web/scripts/generate_native_assets.mjs`,
  31 regenerated PNG/XML assets under `android/` + `public/`, manifest entries.
- **Tables:** `src/components/ResponsiveTable.tsx` (new) + 10 page/component files
  migrated; 2 governance tests updated to the new contract (intent unchanged).
- **Docs:** 6 workstream records + DPIA + Cloudflare study + CHANGELOG + 3 corrected
  legacy docs. Full inventory: `git diff --stat d24719a2..d6db8fb`.

## 4. Key architectural decisions (and rejected alternatives)

1. **One inset owner** (`adjustMarginsForEdgeToEdge: "auto"`): the status-bar plugin sets
   icon style only — never `overlaysWebView`/`setBackgroundColor`. Rejected: stacking a
   second inset strategy (the double-inset bug class).
2. **Splash auto-hide as the fail-safe:** no app-driven `hide()`; a startup error cannot
   trap a user on splash. Rejected: gating splash on font-preload/auth (indefinite-splash
   risk the brief explicitly forbids).
3. **Byte-identical font vendoring** instead of re-subsetting now: zero rendering risk,
   stable URLs beat hashed assets for cache stability. Rejected: aggressive subsetting
   (risks truncating arbitrary tutor text — B2's explicit warning).
4. **Measured fallback** via actual SFNT metrics, em-normalised (Noto upm 1000 vs Nirmala
   upm 2048 — a raw-ratio approach was caught and fixed during derivation).
5. **Presentation-only table component**: state/pagination/authorization stay page-owned;
   no sort support (no consumer sorts). Rejected: a table framework (over-generalisation).
6. **Matrix tables stay bespoke** where per-cell styling exists (A18) — forcing them in
   would need arbitrary cell-attr hooks.
7. **Cloudflare:** retain platform; the API's hard dependencies (sync DB drivers, Redis,
   arq, native wheels, FS fonts) are blockers on Workers, not costs.

## 5. Dependency changes (lockfile via npm only)

| Package | Before | After |
|---|---|---|
| `@fontsource/noto-sans-bengali` | present | **removed** |
| `@fontsource/hind-siliguri` | present | **removed** |
| `@capacitor/status-bar` | — | **7.0.6** (exact) |
| `@capacitor/splash-screen` | — | **7.0.5** (exact) |

Proof: `grep -c fontsource package.json package-lock.json` → 0/0; `npx cap sync android`
registers exactly 3 plugins (app, splash-screen, status-bar); `npm ci` verified by the
test battery running on the installed tree. Knip: one documented exception
(`ignoreDependencies: ["@capacitor/splash-screen"]` — consumed natively via
`capacitor.config.ts`, no JS import exists by design).

## 6. Font measurements (this HEAD, not historical)

- Before: 34 UI woff2 (≈375 KB incl. latin-ext) **+ 35 legacy .woff (~671 KB) shipped in
  every APK**; hashed URLs invalidated font caches every deploy.
- After: **10 woff2 = 346,060 B**; preload = 1 file (44,352 B), fetched exactly once
  (verified in Chromium); KaTeX fonts (39 files, 256 KB) untouched scope.
- First-view Bengali bytes: materially unchanged (~55 KB) — stated plainly per B6; the
  wins are dependency removal, APK weight, and cache stability across deploys.
- Zero third-party font egress (verified; screenshots in the workstream record).

## 7. ResponsiveTable inventory and exceptions

17 migrated / 3 retained (+1 list misusing table classes). Full table with per-surface
preserved behaviour: `TABLE_INVENTORY.md`. Exceptions: A15/A20 (header-less result lists
— not data tables), A18 (per-cell-styled weak-concept matrix). Gap fixed: A17's
header-only empty state → `emptyMessage` with the existing `noResults` key.

## 8. Android build artifact and device verification

- **Local build: NOT RUN** (no JDK/Android SDK on this machine — recorded, not hidden).
  The CI `debug-assemble` job on the PR is the build gate; `npx cap sync android`
  succeeds locally and the synced bundle was verified to contain the new fonts/icons.
- **APK SHA-256 / install evidence: NOT PRODUCED** — no artifact exists to hash.
- **Device acceptance matrix: BLOCKED — owner/device action required.** The full matrix
  (API 35/36, gesture + 3-button nav, light/dark, keyboard, back-priority cases, splash
  transition, insets) is ready in `DEVICE_VERIFICATION_VC206.md`; every row that needs
  hardware is explicitly marked. `vc206`'s origin could not be independently established
  and is preserved as the requested label (A1 rule).

## 9. Automated test results (exact)

| Gate | Command | Result |
|---|---|---|
| Prettier | `npm run format:check` | PASS (all files) |
| ESLint (0 warnings) | `npm run lint` | PASS |
| Knip/dead-code | `npm run deadcode` | PASS (1 documented exception) |
| TypeScript + Vite build | `npm run build` | PASS |
| Unit/integration suite | `npm run test` | **124/124 test files pass** |
| Capacitor sync | `npx cap sync android` | PASS (3 plugins) |
| API gates (pytest/ruff/mypy…) | — | **NOT RUN — no API file changed** (`git diff --stat` on `apps/api/` is empty) |
| Playwright E2E/visual/axe | CI on PR | not runnable locally (needs API stack); visual baselines untouched by design |

## 10. Cloudflare finding

`RETAIN CURRENT PLATFORM`; thin edge gateway = POC ONLY; FastAPI-on-Workers rejected
(sync psycopg, Redis, arq, native PDF wheels, FS fonts are blockers). Docs retrieved
2026-11-18. No PoC run (no account authorization; no reachable origin) — criteria,
data-protection rules and rollback are pre-written in the study.

## 11. DPIA critical/high risks and outstanding sign-offs

Residual high risks (R2 consent/child-notice, R3 cross-border vendor terms, R7 model
retention/training, R9 refusal-event sensitivity, R10 shared-device leakage) each carry
mitigations and proposed owners in `DPIA_BANGLA_GPT_DRAFT.md` §13–§14. Outstanding human
sign-offs: counsel review (commencement, bases, child provisions, transfers, CDO),
owner go/no-go per §17, vendor written confirmations. **No legal or release approval is
claimed by this report.**

## 12. Remaining blockers and explicit owner actions

1. **Physical Android device run** of the vc206 matrix (+ emulator rows if desired) →
   then sign `DEVICE_VERIFICATION_VC206.md`.
2. **CI run on the final SHA** — capture the `debug-assemble` + web-gate job URLs (this
   report cannot fabricate run links).
3. **Legal:** counsel engagement for the DPIA checklist (§19) and the corrected DPA
   template.
4. **Vendor confirmations** (LLM/SMTP/Sentry/hosting/CDN): retention, training use,
   deletion, region.
5. **Optional:** authorize the Cloudflare Option-B PoC under the pre-written criteria.
6. Release signing/Play submission remain untouched (no debug-signed release artifact
   was produced, per the brief).

## 13. Rollback instructions

- **Fonts:** `git revert 5e7fdcb` restores `@fontsource` imports (binaries are additive;
  removing `public/fonts/` is safe afterwards).
- **Native assets/plugins:** `git revert 45f8eef` removes the plugins, config and
  regenerated assets (restores the Capacitor-template splash and white adaptive
  background — the defects this commit fixed; rollback is functional, not desirable).
- **Tables:** `git revert 94c636d` restores all bespoke table markup (component file is
  additive).
- **Docs:** independent; revert individually.
- No database migration, no API change, no consent/retention change → no data rollback
  exists or is needed.

## 14. Statement of what was NOT verified, and why

- Physical-device behaviour (no device), APK artifact hash (no local build), CI job
  outcomes on the final SHA (CI runs on the PR, not here).
- Live vendor payload capture (synthetic-only environment rule).
- Clause-level text of Act 63 of 2026 (Bijoy-encoded gazette PDF; counsel task) — the
  act's identity/publication **is** verified.
- Vendor contract terms (owner/vendor action; labelled `UNKNOWN` in the DPIA register).
- Cloudflare PoC measurements (not run).
- Screen-reader behaviour of migrated tables beyond automated axe-level checks
  (manual SR pass belongs with the device matrix).
