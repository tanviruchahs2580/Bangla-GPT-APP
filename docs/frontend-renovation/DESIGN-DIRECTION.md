# Design Direction — Bangla GPT frontend renovation

Captured 2026-11-11 · HEAD `03dfe21`

## 1. Honest starting position

This frontend is **not a greenfield mess**. Before proposing anything, the audit established
what already holds:

- 166 token declarations across four blocks, with 99 semantic tokens covering brand, fills,
  accents, semantic states, surfaces, typography, radius, elevation, spacing, motion and a
  semantic z-scale (`styles.css:9-183`).
- One `--font` stack with Bengali fallbacks and `font-synthesis: none` protecting matras
  (`styles.css:115-117,274`).
- No raw hex colour outside token declarations — enforced by `contrastTokens.test.ts:146-166`.
- A real accessibility guard family: contrast, form-control boundary, Bengali typography
  numerics, iconography, keyboard contracts, axe sweeps in both jsdom and a real browser.
- `prefers-reduced-motion` handled by a universal `!important` reset that provably covers
  every later animation (`styles.css:445-453`).
- A 44 px coarse-pointer tap floor, a print stylesheet, and six roving-tabindex keyboard
  widgets.
- Baseline gates green: format, lint, 113 unit-test files, build (see
  `BASELINE-AND-REPOSITORY-AUDIT.md`).

So this renovation is **not** "replace a bad design". Claiming otherwise would be dishonest.
The evidence points at four specific failure classes.

## 2. Evidence-backed problems

### P1 — Accessibility defects that the guards cannot see

| # | Defect | Measurement | Evidence |
|---|---|---|---|
| D-01 | **Contrast-guard blind spot.** Both contrast tests locate their token block with `css.indexOf(":root {")`, which resolves to line 9 only. The later `:root` (3846) and dark block (3870) are invisible to every ratio computation, so 11 light + 6 dark tokens have never been checked. Worse: the second `:root` sits *after* the first dark block at equal specificity, so the next token added there under a name that already exists in dark mode silently overrides dark mode with no error. | 17 tokens unguarded | `contrastTokens.test.ts:17-18`; `formControlBoundary.test.ts:24-25`; `styles.css:3846,3870` |
| D-02 | **Hero prompt placeholder fails AA.** `.hero .home-prompt .input::placeholder` uses `--hero-placeholder` on a literal `rgba(255,255,255,0.96)` fill over `--grad-hero`. | **4.24–4.31:1**, below the 4.5:1 text minimum — on the single most prominent input in the product | `styles.css:4187,4194` |
| D-06 | **Reduced motion does not reset `animation-delay`.** The universal reset sets `animation-duration: .001ms !important` but leaves 15 `animation-delay` declarations intact. Combined with `animation-fill-mode: both` and `from { opacity: 0 }`, a reduced-motion user is still held invisible for up to 340 ms per staggered child. | 15 delays unreset, up to ~340 ms per child | `styles.css:445-453`, `3904-3941`, delays at `2087,2090,3907-3941,4679-4687` |
| D-18 | **No global `::placeholder` rule** exists anywhere except the hero one, so every other input relies on the user-agent placeholder colour inside a dark `--card: #1b1e14`. Unmeasured — flagged, not asserted. | unguarded | grep: single `::placeholder` hit |

### P2 — Duplicated sources of truth (the real maintainability defect)

| # | Defect | Evidence |
|---|---|---|
| D-03 | `.ring` is declared twice (1202 and 4370); the later one wins entirely. Its track is `color-mix(--line 70%)` over `--card`. | track at **1.21:1 (light) / 1.16:1 (dark)** — the empty portion of the progress arc is effectively invisible, below the 3:1 non-text minimum |
| D-04 | **Two button vocabularies.** `ui.tsx:20-27` emits `.btn .btn-*`; a legacy `button.primary` / `button.secondary` / `button.small` set lives at `styles.css:3076-3112` and is still consumed raw at 7 call sites including `AppShell.tsx:92`. Those three classes have no owner in `ui.tsx`. | grep |
| D-05 | **`.stat` rendered three different ways.** `.stat` (`styles.css:1135-1141`), `.stat-row > div` (`3141-3147`), `.landing-stats > div` (`4735-4745`) — same information shape, three fills, three inner-class conventions (`.stat-value/.stat-label` vs `.num/.lbl` vs bare `<strong>/<span>`). Reach 86 raw `className="stat` sites against 5 `<Stat>` uses. | grep |
| D-10 | `.card` declared twice (719, 4349); `.hero` declared twice (1624, 4102) with 19 `.hero` selectors total. The later definition wins; the earlier one is dead weight that makes intent unreadable. | grep |
| D-08 | `--glass-bg` declared twice with byte-identical values (179, 248) — a no-op that implies a dark-parity requirement that does not exist. | `styles.css:179,248` |
| D-09 | `@keyframes voice-pulse` defined twice (2146, 2876). The later definition silently replaces the first for **both** consumer rules (2143 and 2874), so one of them does not animate as written. | grep |
| D-07 | The "no loose colour literal" guard only matches **hex**. 52 `rgba()` literals remain outside token lines — the top repeat is `rgba(0,0,0,0.45)` ×5, and the hero input fill itself is a literal. | grep: 75 `rgb/rgba()` occurrences, 23 on token lines |
| D-12 | `.ring-inner` applies `letter-spacing: -0.02em` and is allowlisted as Latin-only by `w2_i18n_css_typography.test.ts:52`, whose stated justification ("all call sites pass `{Math.round(x)}%`") is **stale** — `ui.tsx:141` now renders `formatNumber(...)`, i.e. Bengali digits under `bn`. The guard still passes because it only inspects the selector. | code |

### P2 — Decoration substituting for hierarchy

| # | Defect | Evidence |
|---|---|---|
| D-17 | The renovation that landed before this one added a decorative layer that carries no information: **3 "drifting aurora blobs"** at `filter: blur(28px)` looping `16s infinite` behind the home hero (`4121-4132`), a three-layer radial mesh on `body::before` plus a masked diagonal weave on `body::after` (`289-336`), **25 `radial-gradient`** uses, a shine sweep painted on **every** button on hover (`--grad-shine`, `3990-3999`), a 14 %/6 % gloss duplicated onto `.btn-primary` and `.btn-teal` (`4033-4036,4049-4052`), the same `inset 0 1px 0 rgba(255,255,255,.45)` copy-pasted into four tile rules (`4308,4320,4328,4336`), and an untokenised amber glow `rgba(217,119,6,0.5)` (`4325`). | grep |
| D-11 | **86 `box-shadow` declarations.** `--elev-1..3` plus seven legacy aliases plus `--quick-shadow(-hover)`, `--shadow-brand(-lg)`, `--ring-glow` and per-component one-offs. The file's own comment at `135-136` calls this "the single canonical scale"; 86 shadows across ~700 rules means elevation communicates nothing. | grep |
| — | **Motion scale does not govern the layer that matters.** 31 `transition:` declarations, only 10 reference a `--m-*` token; 33 `animation:` declarations, only 13. Raw durations include 16s, 26s, 2.6s and a scatter of 340–620 ms entrance values — and 420 ms exists both as `--m-page` and as a literal. | grep |

### P2/P3 — Trust and copy defects found during inventory

| # | Defect | Evidence |
|---|---|---|
| D-13 | The **per-question** "accept" button reuses the `qpReviewAll` label, so a single-row action reads as a bulk one. | `QPaperReviewPanel.tsx:288-290` |
| D-14 | `resendVerification` is rendered as `<a href="/forgot">` whose click is intercepted. Middle-click or "open in new tab" lands the user on `/forgot` instead — a false affordance. | `LoginPage.tsx:320-339` |
| D-19 | School-invite fetch failure renders an **empty list** — the UI reports "no invites" when the request failed. Elsewhere this codebase is strict about exactly this lie (`LoadError` is used 19 times). | `SchoolsCard.tsx:36-61` |
| D-20 | Deleting an offline chapter copy that fails **leaves the row with no message**. | `OfflineLibrary.tsx:86-92` |
| D-16 | `MePage.tsx:504` renders the server string `on_disable_note_code` through `t()` with a raw-value fallback, so an unmapped code can surface as machine text to a child. | code |
| D-15 | Four destructive actions take effect with **no confirmation**: delete saved note, delete offline copy, revoke guardian invite code, revoke school invite. | `MePage.tsx:370-377`, `OfflineLibrary.tsx:86-92`, `ParentInviteCard.tsx:88-96`, `SchoolsCard.tsx:219-227` |

## 3. Design direction: **subtract, then solidify**

Rejected directions and why:

- **"New visual identity"** — rejected. The product has a legitimate existing identity, live
  Playwright visual baselines, and an explicit instruction not to invent branding. A restyle
  would invalidate 60 reviewed baselines to change nothing a user asked for.
- **"Adopt a component library / Tailwind"** — prohibited (`AGENTS.md` §4) and unnecessary;
  the primitives already exist.
- **"Add a light/dark/tonal third theme"** — out of scope: theme parity must be *preserved*,
  not expanded (`master-prompt §7.9`).

**Chosen direction.** Treat the existing visual language as the product's, and spend the
renovation on the four things the evidence supports:

1. **Close the guard blind spots first.** The single highest-value change is not visual at
   all: make the contrast and boundary guards parse *every* token block, then let the
   newly-visible assertions tell us what is actually wrong. Fix what they reveal. A guard
   that cannot see a third of the tokens is the root cause behind several findings above.
2. **Subtract decoration that carries no information.** Remove the aurora blobs, the masked
   weave, the per-button shine sweep and the duplicated gloss. Collapse the shadow scale to
   the three tokens that exist for it. Keep every gradient that encodes a **semantic fill**
   (buttons, chips, brand marks) — those are identity, not ornament.
3. **Unify the duplicated primitives**, one owner each: one button vocabulary, one stat
   contract, one `.card`, one `.ring`. Delete the loser only after proving no consumer
   remains.
4. **Make feedback honest where it is currently silent**, and fix the copy/semantics defects
   that mislead (D-13, D-14, D-19, D-20, D-16).

Explicitly **not** in scope, and recorded as recommendations for the product owner rather
than silently changed: D-15 (adding confirmations changes the interaction contract, which
the feature lock names explicitly), the `SchoolDashboard` admin-vs-school_admin gate
mismatch, and the un-paginated `getSchoolStudents(100, 0)` call.

## 4. Bengali-first constraints on every change

These are acceptance criteria, not preferences. Each is guarded by an existing test that
must keep passing, or by a new one:

- Bengali body line-height ≥ 1.6, heading ≥ 1.5 (`w2_i18n_css_typography.test.ts:92-101`).
- No `letter-spacing` or `text-transform` on Bengali text — the only five `letter-spacing`
  sites are `:lang(en)`-scoped or explicitly allowlisted (`styles.css:557,2837,3735,4345,4823`).
- No `hyphens: auto`.
- Font weights limited to the two loaded faces (400/700); `600` resolves to 700 by design.
- Numerals follow the active language's policy (`w2_i18n_numeral_policy.test.ts`).
- Conjunct shaping relies on `font-synthesis: none` + the Noto Sans Bengali stack — no font
  substitution, no `font-feature-settings` changes.
- Removing decoration must not remove the **44 px coarse-pointer tap floor**
  (`styles.css:5094-5120`).

## 5. Assumptions and unknowns (honest ledger)

**Observed facts** — everything in §2, each with a line reference or a grep count.

**Inferences** (stated as such, not as measured): the user-agent placeholder colour in dark
mode is likely below 4.5:1 but was not measured without a browser; the perceived emptiness
of `.ring`'s track follows from its computed 1.21:1 ratio rather than from a screenshot;
the `voice-pulse` duplicate's visual consequence was not render-verified.

**Assumptions being carried:** that the existing Playwright visual baselines are the
approved design targets for everything this renovation does not deliberately change.

**Not determined / blocked:**
- No user research, interviews or usability testing was performed. No such claim is made.
  The rubric in §6 is a transparent heuristic review.
- No field Core Web Vitals data exists; any performance figure produced here is lab-only.
- The Android emulator path is blocked on this machine by design (`AGENTS.md` §13: no
  `java`, `gradle`, or `adb`), so WebView behaviour is verified only through the Playwright
  `mobile-chromium` project and must never be reported as native verification.

## 6. Objective review rubric (applied to representative routes)

Scored 1–5 with a screenshot reference per dimension. Not a scientific UX metric.

| Dimension | Review question |
|---|---|
| Task clarity | Can the intended user identify the main task and next action? |
| Information hierarchy | Are primary, secondary and supporting information distinguishable? |
| Bengali-first readability | Are glyphs, line-height, mixed text and long content legible? |
| Consistency | Do shared components, tokens and states feel coherent across roles? |
| Responsive usability | Does layout adapt without hiding capabilities? |
| Accessibility | Semantics, focus, keyboard, contrast, assistive labels. |
| Interaction quality | Loading, success, error, disabled, streaming and recovery clarity. |
| Visual integrity | Product-specific, restrained, free of generic template patterns. |

Any dimension scoring 1–2 requires a fix or an explicit blocker rationale. Baseline and
final scores are recorded in `VISUAL-QA-REPORT.md`.
