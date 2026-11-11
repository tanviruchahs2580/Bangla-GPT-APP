# Accessibility Report — Bangla GPT frontend renovation

Scope: WCAG 2.2 AA-oriented review of the frontend, focused on what this renovation changed.
Target statement is deliberate: **AA-oriented**, not "AA certified". Automated scanning plus
targeted manual measurement cannot establish conformance on its own, and no assistive
technology was driven by a human in this pass.

---

## 1. What this renovation fixed

### 1.1 Hero prompt placeholder — was a real AA failure (R-02)

The most prominent input in the product, on the student home hero. `.hero .home-prompt .input`
paints a **literal** `rgba(255,255,255,0.96)` fill over `--grad-hero` in both themes, so its
placeholder colour must be theme-invariant.

| `--grad-hero` stop | Before `#6b7a66` | After `#525c4d` | Threshold |
|---|---:|---:|---:|
| `--brand-ink` `#052e16` | **4.24** ✗ | 6.51 | 4.5:1 (1.4.3) |
| `--brand` `#166534` | **4.31** ✗ | 6.61 | 4.5:1 |
| `--brand-strong` `#14532d` | **4.28** ✗ | 6.57 | 4.5:1 |

Measured by `evidence/accessibility/contrast_audit.py`, which reads the values out of
`styles.css` rather than hardcoding them, and asserted by
`contrastTokens.test.ts` → `clears 4.5:1 on the fill over every --grad-hero stop`.
The guard also asserts the fill is still a literal, so theming it later fails loudly instead
of silently inverting the ratio.

### 1.2 Placeholders were unguarded product-wide (R-04)

The hero prompt was the **only** rule in 5,156 lines that styled a placeholder. Every other
input fell through to the user agent's own colour — which no guard can measure and which was
never chosen for the dark `--card: #1b1e14`. Added one semantic role and one global rule:

```css
--placeholder: var(--muted);          /* aliased, so a theme change moves both */
::placeholder { color: var(--placeholder); opacity: 1; }
```

`opacity: 1` is load-bearing: Firefox dims placeholders with its own opacity, which would
multiply the effective ratio straight back below 4.5:1. Measured worst case 5.03:1 (on
`--bg`); asserted on `card` / `card-2` / `bg-elev` / `bg` in both themes.

**Verified in a real browser** (Chrome via Playwright, `http://localhost:5173/login`): an
input with no placeholder rule of its own resolves `color: rgb(93, 107, 87)` — i.e.
`--placeholder` — with `opacity: 1`, and exactly two `::placeholder` rules are parsed.

### 1.3 Progress-ring track was invisible (R-05)

Both `.ring` declarations painted the empty arc with `color-mix(in srgb, var(--line) 70%, transparent)`
over `--card`:

| | Before | After (`--line-strong`) | Threshold |
|---|---:|---:|---:|
| light | **1.21:1** ✗ | 3.54:1 | 3:1 (1.4.11, non-text) |
| dark | **1.16:1** ✗ | 3.46:1 | 3:1 |

A ring communicates proportion through the arc-versus-track boundary, so an unreadable track
makes the graphic unreadable. The fix reuses `--line-strong` — a token that *already* carries
an asserted ≥3:1 contract on those surfaces in `formControlBoundary.test.ts` — rather than
introducing a new value, so the ring joins an enforced floor instead of a new promise.

### 1.4 Reduced motion did not actually remove motion (R-07)

The universal `!important` reset neutralised `animation-duration` but left **15
`animation-delay` declarations** intact. With `animation-fill-mode: both` and
`from { opacity: 0 }`, a reduced-motion user was still held invisible for up to ~340 ms per
staggered child. It also collapsed the duration of `infinite` decorative loops, which
restarts them ~1000×/second — worse than not collapsing them.

`animation-delay` / `transition-delay` are now reset to `0s`, with
`animation-iteration-count: 1`.

**Checked for a regression from `iteration-count: 1`:** the `infinite` animations are the
streaming pulse, the streaming caret blink, and the voice/recording indicator. Each of those
also conveys its state through a non-motion channel — a visible element, the `--danger`
colour, `aria-pressed`, and a `role="status"` live region — so one iteration leaves no state
misrepresented. Ending decorative motion for a user who asked for it is the intent of the
media query; it is not a state change.

### 1.5 Guard blind spot — the root cause behind several of the above (R-01)

Both token guards located their block with `css.indexOf(":root {")`, resolving to the **first**
of four blocks. 11 light and 6 dark tokens were outside every ratio assertion in the
repository, including `--line-strong`'s own later re-declaration and the entire
`--aurora-*` / `--ring-glow` / `--grad-shine` set. It was also a latent trap: the second
`:root` sits *after* the first dark block at equal specificity, so a token added there under
an existing dark name would have silently overridden dark mode with no test failing.

`src/test/cssTokens.ts` now merges every block per theme (brace-depth aware, comments
masked), and both guards use it. `contrastTokens.test.ts` grew 12 → 27 tests.

### 1.6 Newly-guarded pairs that were already passing

Now asserted in both themes, so a future palette change cannot move them quietly:
`ok`/`warn`/`danger` on their tints (5.14–8.12), `teal-strong` on `teal-soft` (5.17/7.85),
`ai` on `ai-soft` (5.62/5.36), `muted` on all four surfaces (5.03–7.91), `ink` on `card`
(15.08/14.63).

### 1.7 Semantics

- **R-12** — resend-verification was `<a href="/forgot">` with an intercepted click: announced
  as a link but performing an action, and navigating to the password-reset page on
  middle-click, "open in new tab", or without JS. Now a real `Button`
  (`type="button"` by default, so it cannot submit the form), tested by role.
- **R-11** — the per-question "accept" button reused the bulk `qpReviewAll` label, so a
  screen-reader user heard "Accept all" on a single-question control. Distinct label now.
- **R-03** — a failed invite fetch rendered an empty table, i.e. announced as "no invites"
  when the request had failed. Now a `role="alert"` with a retry.
- **R-06** — a failed offline-copy delete had no feedback at all. Now announced through the
  existing polite toast region.

## 2. What was already strong (verified as unchanged)

- Skip link present on authenticated **and** public routes (`App.tsx:192`).
- `RequireAuth` distinguishes "API unreachable" from "session refused", with `role="alert"`
  and focus moved to the heading — the one screen that says what is wrong would otherwise be
  silent to a screen reader.
- `Modal` implements a real focus trap, Esc, scroll lock and focus restoration.
- Six roving-tabindex widgets with correct key maps (see `TEST-STRATEGY-AND-MATRIX.md` §4),
  and every ask/send input guards Enter with `nativeEvent.isComposing` for the Android Bangla
  IME.
- 44 px coarse-pointer tap floor; print stylesheet; semantic z-scale.
- Bengali line-height floors (body ≥ 1.6, heading ≥ 1.5) and "no Latin tracking on Bengali"
  are asserted, not just intended. No `hyphens: auto`. `font-synthesis: none` protects matras.
- axe runs in CI across 4 variants (light/dark × bn/en) on the public routes and all five role
  routes, failing on serious/critical.

## 3. Where I reasoned rather than measured — stated, not hidden

| Item | Status |
|---|---|
| **No real screen-reader session.** No NVDA/JAWS/TalkBack/VoiceOver pass was performed with a human or a real AT. ARIA snapshot tests (`e2e/screen-reader.spec.ts`, 3 YAML baselines) and axe results are **not** a substitute. | **NOT RUN** |
| **Reflow / 200 % zoom.** `e2e/reflow.spec.ts` (12 tests) exists and was not re-run to completion in this delivery. | **NOT RUN** |
| **Keyboard-only completion of every critical journey.** Covered by `e2e/keyboard.spec.ts` and unit tests for the widgets, but not re-executed end to end here. | **PARTIALLY VERIFIED** |
| **`.ring` arc-vs-track contrast** is still 1.55:1 light / 2.81:1 dark. The arc is read by hue, not luminance. Fixing it needs a three-level gauge — a visual-design decision, not an unambiguous correction. Recorded as **R-15** for the owner. | **KNOWN LIMIT** |
| **`.card` mixed border** at 1.22:1 / 1.17:1. Decorative, not a control edge; the control boundary (`--line-strong`) is asserted. **R-16**. | **KNOWN LIMIT** |
| **`.btn:disabled`** white label at 2.67 / 3.86. WCAG-exempt (inactive control), but the reason for disablement is never exposed to assistive tech — only `aria-busy`. | **KNOWN LIMIT** |
| **Native mobile / Android.** No `java`, `gradle` or `adb` on this machine. Browser viewport emulation is **not** reported as device testing. | **BLOCKED** |

## 4. Honest verdict for this section

Twelve accessibility-relevant defects were fixed with demonstrated regression guards, and the
guard suite that should have caught two of them is now able to see a third of the palette it
previously could not. That is a real improvement.

It is **not** a WCAG conformance claim. Automated scans plus targeted ratio measurement on
changed surfaces, without a real assistive-technology pass, does not support one.
