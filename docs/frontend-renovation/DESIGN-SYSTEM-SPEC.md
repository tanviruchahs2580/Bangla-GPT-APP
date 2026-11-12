# Design System Specification — Bangla GPT frontend

Companion to `DESIGN-DIRECTION.md`. That file says *what* the direction is and why; this one
records *what actually exists in the code* and what this renovation changed.

Status legend: **UNCHANGED** (verified as-is, no edit), **CHANGED** (edited by this
renovation), **DEFECT → see R-nn** (recorded, not fixed, reason in `RISK-REGISTER.md`).

---

## 1. Where the tokens live

One governed source: `apps/web/src/styles.css`. There is no second token source, no
page-level mini system, and no CSS framework (`AGENTS.md` §4 — no Tailwind; preserved).

The file declares four token blocks, and **this is the single most important structural fact
in the stylesheet**:

| Block | Line (after this renovation) | Tokens | Role |
|---|---:|---:|---|
| `:root` | 9 | 99 | v3 base: brand, fills, accents, semantic states, surfaces, typography, radius, elevation, spacing, layout, motion, z-scale, glass/focus |
| `[data-theme="dark"]` | ~195 | 40 | dark overrides for the above |
| `:root` | ~3880 | 11 | v3-extended: `--ease-bounce`, `--ease-soft`, `--m-xs`, `--m-page`, `--grad-shine`, `--ring-glow`, `--quick-shadow`, `--quick-shadow-hover`, `--aurora-1..3` |
| `[data-theme="dark"]` | ~3905 | 6 | dark overrides for the extended set |

**R-01 — CHANGED.** Both contrast guards used to locate their block with
`css.indexOf(":root {")`, which resolves to line 9 only, so the entire second pair was
invisible to every ratio assertion (guards saw 99 light / 40 dark tokens; the file has 110 /
46). `src/test/cssTokens.ts` now merges **every** block per theme, in source order, matching
cascade behaviour. The latent half of the bug is also closed: the second `:root` sits after
the first dark block at equal specificity, so a colliding token name there would previously
have silently overridden dark mode with no test failing; a `blockCounts()` regression guard
now fails if the parser stops seeing all blocks.

**R-19-style consolidation is NOT done.** The two `:root` pairs are deliberately left in
place rather than physically merged into one block: merging is a pure-move edit across 200
lines of reviewed CSS with no behavioural benefit now that the guards can see both, and it
would make the diff unreviewable. Recorded as a tidy-up, not a defect.

## 2. Colour roles

Every role below is a semantic token. Raw hex outside token declarations: **zero**, enforced
by `contrastTokens.test.ts` ("no loose colour literals", F-199).

| Role group | Tokens |
|---|---|
| Brand | `--brand`, `--brand-strong`, `--brand-ink`, `--brand-soft`, `--brand-soft-2`, `--brand-solid`, `--brand-solid-strong` |
| White-label fills | `--*-solid` / `--*-solid-strong` for brand, teal, warn, ai, danger; `--on-brand` is the single ink they all carry and stays white in both themes because those fills are theme-invariant |
| Accents | `--teal`, `--teal-strong`, `--teal-soft`, `--ai`, `--ai-soft`, `--fresh`, `--earth` |
| Semantic state | `--danger`, `--danger-soft`, `--warn`, `--warn-soft`, `--ok`, `--ok-soft` |
| Surfaces | `--bg`, `--bg-elev`, `--card`, `--card-2` |
| Text | `--ink`, `--muted`, **`--placeholder` (CHANGED — new)** |
| Borders | `--line`, `--line-strong` |
| Specials | `--white`, `--print-ink`, `--hero-placeholder` (**CHANGED**), `--splash-glow` |

### 2.1 R-02 — CHANGED: hero prompt placeholder

`--hero-placeholder` was `#6b7a66`. `.hero .home-prompt .input` paints a **literal**
`rgba(255,255,255,0.96)` fill over `--grad-hero` in *both* themes, and the token measured
**4.24:1** there — under the 4.5:1 text minimum, on the most prominent input in the product.
Now `#525c4d`: **6.51:1** worst case across the three gradient stops. The guard asserts the
ratio against every stop *and* asserts the fill is still a literal, so theming the fill later
fails loudly instead of silently inverting the ratio.

### 2.2 R-04 — CHANGED: a real placeholder role

The hero prompt was the only rule in 5,156 lines that styled a placeholder; every other
input fell through to the user-agent colour inside the dark `--card: #1b1e14`. Added
`--placeholder: var(--muted)` (aliased, so a theme change moves both together) plus one
global rule:

```css
::placeholder { color: var(--placeholder); opacity: 1; }
```

`opacity: 1` is load-bearing — Firefox dims placeholders with its own opacity, which would
multiply the ratio straight back below 4.5:1. Measured: 5.03:1 worst case (on `--bg`).
Browser-verified: a rule-less input resolves `rgb(93, 107, 87)` at `opacity: 1`.

### 2.3 Guarded ratios

| Pair | Threshold | Coverage |
|---|---:|---|
| `#fff` on `--brand-solid`, `--brand-solid-strong`, `--danger-solid`, `--teal-solid`, `--teal-solid-strong` | 4.5:1 | pre-existing |
| `#fff` on each gradient stop + the 14 % white top highlight | 4.5:1 | pre-existing |
| `#fff` glyphs on `--tile-teal/-warn/-ai` stops | 3:1 | pre-existing |
| `--line-strong` on `--card`/`--card-2`/`--bg-elev`/`--bg` | 3:1 | pre-existing |
| hero placeholder across all `--grad-hero` stops | 4.5:1 | **new** |
| `--placeholder` on the four input surfaces | 4.5:1 | **new** |
| `--line-strong` on `--card` (ring track) | 3:1 | **new** |
| `ok`/`warn`/`danger`/`teal-strong`/`ai`/`muted`/`ink` on their tints and surfaces | 4.5:1 | **new** (were unguarded) |

### 2.4 Known limits — recorded, not papered over

| Surface | Measured | Why not fixed |
|---|---:|---|
| `.ring` **arc vs track** | 1.55:1 light / 2.81:1 dark | The arc is read by hue. Fixing it needs a three-level gauge — a visual redesign of a component with reviewed baselines. **R-15**, owner decision. |
| `.card` mixed border `color-mix(--line 75%)` | 1.22:1 light / 1.17:1 dark | Decorative, not a control edge (the control boundary is `--line-strong`, asserted). Raising it changes every card in the product. **R-16**. |
| `.btn:disabled` white label at `opacity .55` + `grayscale .35` | 2.67 / 3.86 | WCAG-exempt (inactive control). |
| Un-themed user-agent placeholder inside a themed dark surface | n/a now | This is what R-04 fixed. |

## 3. Typography

**UNCHANGED.** One stack, applied once at `body`:
`"Noto Sans Bengali", "Hind Siliguri", -apple-system, "Segoe UI", system-ui, sans-serif`.
`font-synthesis: none` protects matras.

- Scale: 7 `clamp()` tokens, `--fs-xs` → `--fs-3xl`. Used 102×; raw font sizes only twice
  (a `12pt` inside `@media print`, a `10px` on `.notif-badge`).
- Line-height: `--lh-body: 1.7`, `--lh-head: 1.5`, `--lh-tight: 1.3`. Guarded ≥1.6 / ≥1.5.
- Weights: only 400 and 700 faces are loaded; the 25 `font-weight: 600` declarations resolve
  to the 700 face by design and the range is asserted against the loaded faces.
- `letter-spacing`: 5 non-zero sites, all `:lang(en)`-scoped or explicitly allowlisted.
  No `text-transform` on Bengali. No `hyphens: auto`.

**Bengali-first acceptance criteria carried by this renovation** (all still enforced):
Bengali line-height floors; no Latin tracking on Bengali; numerals follow the active
language's policy; no font substitution; no `font-feature-settings` change; and the **44 px
coarse-pointer tap floor** was not removed.

## 4. Spacing, radius, layout, z-scale

**UNCHANGED.** `--space-1..7` = 4/8/12/16/24/32/48. `--radius-sm|--radius|--radius-lg|--radius-full`
= 10/16/24/999px. `--maxw: 1120px`, `--topbar-h: 64px`, `--nav-h`. A real semantic z-scale:
`--z-dropdown 30 · --z-sticky 40 · --z-overlay 50 · --z-modal 60 · --z-toast 70`.

## 5. Elevation

**UNCHANGED, and flagged.** `--elev-1..3` exist with seven legacy aliases
(`--shadow-sm/md/lg/1/2/3`), plus `--quick-shadow(-hover)`, `--shadow-brand(-lg)`,
`--ring-glow`. The file has **86 `box-shadow` declarations**, so the comment calling this
"a single canonical scale" is not what the file does. Collapsing it is part of deferred
Wave 3.3 (see `IMPLEMENTATION-PLAN.md`) because it invalidates most visual baselines at once.

## 6. Motion

**R-07 — CHANGED.** Tokenised timings `--m-fast 150 / --m-med 250 / --m-slow 350` with
`--m-xs 90ms` and `--m-page 420ms`. The scale does **not** govern the layer that matters:
of 31 `transition:` declarations only 10 reference a token, and of 33 `animation:`
declarations only 13. That ratio is a recorded observation, not fixed here.

The reduced-motion block now does what it claimed:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
    animation-delay: 0s !important;        /* new */
    transition-delay: 0s !important;       /* new */
    animation-iteration-count: 1 !important;/* new */
    scroll-behavior: auto !important;
  }
}
```

Why each line matters: neutralising the *duration* left 15 `animation-delay` declarations
intact, so with `animation-fill-mode: both` and `from { opacity: 0 }` a reduced-motion user
was still held invisible for up to ~340 ms per staggered child. And collapsing the duration
of an `infinite` loop restarts it ~1000×/second, which is worse than not collapsing it.

**Checked for a downside:** the `infinite` animations are the streaming pulse, the streaming
caret blink and the voice/recording indicator. Each also conveys its state through a
non-motion channel (visible element, `--danger` colour, `aria-pressed`, `role="status"`), so
one iteration does not leave any state misrepresented — which is the condition for removing
motion that WCAG's reduced-motion guidance is about.

## 7. Components

**UNCHANGED.** `components/ui.tsx` exports 13 primitives, each with one implementation:

| Primitive | Variants / notes |
|---|---|
| `Button` | variants primary/teal/ghost/soft/danger/default; sizes sm/md/lg; `block`; `loading` → `aria-busy`; **defaults `type="button"`** (which is why the LoginPage fix cannot submit the form) |
| `Card` | optional `title`/`action`, spreads `rest` so `role`/`aria-*` reach the DOM |
| `Badge` | 5 tones |
| `Spinner`, `Skeleton` (4 variants) | |
| `ProgressRing` | `role="img"`, Bangla-aware `aria-label` |
| `Stat` | 5 call sites |
| `LoadError` | `role="alert"` + optional retry — the product's standard honest-failure surface (19 uses) |
| `Modal` | portal, focus trap, Esc, scroll lock, focus restore |
| `Field` | injects `aria-describedby` / `aria-invalid` |
| `Segmented` | `role="group"` + `aria-pressed` — deliberately not a tablist |
| `Avatar` | 4 sizes × 3 tones |
| `TrendMark` | |

### 7.1 Recorded duplication (NOT fixed — deferred Wave 3.1/3.2)

- **Two button vocabularies.** `ui.tsx` emits `.btn .btn-*`; a legacy
  `button.primary` / `button.secondary` / `button.small` set lives at `styles.css:3076-3112`
  and is still consumed raw at 7 sites. `formControlBoundary.test.ts` asserts
  `button.secondary`, so retiring it means rewriting an accessibility guard in the same
  change.
- **Three parallel stat layouts** — `.stat` (1135), `.stat-row > div` (3141),
  `.landing-stats > div` (4735) — reached by **86** raw `className="stat…"` sites against 5
  `<Stat>` uses.
- `.card` is declared twice (719, 4349); `.hero` twice (1624, 4102).
- `.ring` is declared twice (1202, 4370) — the later wins; **R-05** fixed its track.

### 7.2 R-10 — CHANGED: dead duplicate removed

`--glass-bg` was re-declared in the dark block with a byte-identical value. It resolves
`var(--bg-elev)`, which is already themed, so the override changed nothing while implying a
dark-parity requirement that does not exist. Removed, with the reason in place.

### 7.3 R-09 — CHANGED: colliding `@keyframes`

`@keyframes` names are global and the later definition wins for **both** consumers, so the
recording ripple silently lost its `scale(0.96) → scale(1.08)` expansion and only faded
opacity. The button-blink animation is renamed `voice-blink`; no test referenced either name.

## 8. Responsive system

**UNCHANGED.** Eight numeric breakpoints — 480, 560, 760, 899/900, 960, 1023/1024 — matching
the set documented in `AGENTS.md` §16. No undocumented one-off breakpoint exists.

Two recorded weaknesses: the file mixes mobile-first `min-width` in the base layer with
`max-width` in the later layer, so override order depends on file position rather than
stated intent; and the 760 px tier is fragmented across four blocks spread over ~1000 lines.
Zero container queries.

## 9. Required viewport profiles

From the master prompt §7.5, with the coverage rule that keeps the matrix bounded:

| Profile | Viewport | Coverage |
|---|---|---|
| Compact mobile | 360 × 800 | visual baseline set |
| Standard mobile | 390 × 844 | Playwright `mobile-chromium` project (Pixel 5, 393×851) |
| Large mobile | 430 × 932 | archetype-level |
| Tablet portrait | 768 × 1024 | visual baseline set |
| Small desktop | 1024 × 768 | archetype-level |
| Standard desktop | 1440 × 900 | per-route smoke |
| Large desktop | 1920 × 1080 | archetype-level |

Smoke every route at desktop + mobile; full viewport set per distinct layout archetype;
every critical journey at one desktop and one mobile profile. The visual baseline set already
covers 5 representative screens × {light, dark} × {bn, en} × {360, 768, 1280} — 60 snapshots.

## 10. Anti-AI-slop rules applied to this renovation

`DESIGN-DIRECTION.md` §2 records the decorative layer that exists (3 "drifting aurora blobs"
at `blur(28px)` looping 16 s behind the home hero, a two-layer masked page background, 25
`radial-gradient` uses, a shine sweep on *every* button hover, the same
`inset 0 1px 0 rgba(255,255,255,.45)` copy-pasted into four tile rules, an untokenised amber
glow). **This renovation removed none of it** — deliberately. Wave 3.3 is deferred because
that change invalidates nearly every visual baseline at once and needs the full 60-snapshot
review cycle, which this delivery does not have the budget to complete honestly.

The counter-discipline that *is* real and was preserved: semantic tokens with named roles,
zero loose hex, a genuine z-scale, a Bangla-specific typography guard suite, a 44 px tap
floor, a print stylesheet, and a reduced-motion guard that covers the whole file.
