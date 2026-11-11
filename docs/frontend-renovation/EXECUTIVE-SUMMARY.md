# Executive Summary — Bangla GPT frontend renovation

**Date:** 2026-11-11 · **Repository:** `Bangla-GPT-APP` · **Branch:** `main`
**Baseline commit:** `03dfe21` · **Changes:** uncommitted · **No push, merge, tag, release or deploy.**

---

## Verdict

**`PARTIALLY COMPLETED — BLOCKERS REMAIN`.**

Not `COMPLETED — VERIFIED`, because the full per-feature functional matrix was not executed
and the Android/WebView check is impossible on this machine. Not `NOT COMPLETED`, because
fifteen substantiated defects were fixed with demonstrated regression guards, every static
gate is green, and all 68 browser tests pass including all 60 visual baselines without
re-baselining.

## What was actually done

The audit found that this frontend is **not** a greenfield mess — it already had 99 semantic
tokens, zero loose hex colour, a real z-scale, Bengali typography guards, and six
roving-tabindex keyboards. So the direction became **repair and solidify**, not restyle.
Resty–ling would have invalidated 60 reviewed visual baselines to change nothing a user asked
for, and the task explicitly forbids inventing branding.

Four things were fixed, in dependency order.

**1. The guards could not see a third of the palette.** Both contrast tests located their
token block with `css.indexOf(":root {")`, which resolves to the first of four blocks. Eleven
light and six dark tokens were outside every ratio assertion in the repository — and because
the second `:root` sits *after* the first dark block at equal specificity, a colliding token
name would have silently broken dark mode with no test failing. A new shared
`src/test/cssTokens.ts` merges every block; `contrastTokens.test.ts` went from 12 to 27 tests
and a regression guard now fails if the parser stops seeing all blocks.

**2. The two defects that blind spot was hiding.**

| Defect | Was | Now | Threshold |
|---|---:|---:|---:|
| Hero prompt placeholder, on the product's most prominent input | **4.24:1** | 6.51:1 | 4.5:1 |
| Progress-ring track (the empty arc is how you read the proportion) | **1.21 / 1.16:1** | 3.54 / 3.46:1 | 3:1 |

The placeholder was the *only* placeholder rule in 5,156 lines, so every other input fell
through to the user-agent colour inside the dark surface. One semantic role and one global
rule fixed that across the product. The ring track reuses `--line-strong`, a token that
already carries an asserted 3:1 contract, rather than inventing a value.

**3. Reduced motion did not remove motion.** The `!important` reset neutralised animation
*duration* but left 15 `animation-delay` declarations intact, so with
`animation-fill-mode: both` and `from { opacity: 0 }` a reduced-motion user was still held
invisible for up to ~340 ms per staggered child. It also collapsed `infinite` decorative loops
to 0.001 ms — restarting them ~1000×/second. Fixed, and now covered by a dedicated test file.

**4. Three places where the UI said something untrue.** A failed school-invite fetch rendered
an empty list (indistinguishable from "no invites"); a failed offline-copy delete said nothing
at all; the login page's resend-verification control was a link to another page whose click was
intercepted. Each now reports the truth, and each has a test that was demonstrated to fail
against the pre-change code.

## What the independent review found — including two defects I introduced

Two read-only reviewers were tasked with **falsifying** the preservation claim. They succeeded
twice, and one of those was worse than a code bug:

- **A rename broke an existing test, and I reported it as passing.** Relabelling a
  question-paper button left `qpapers.test.tsx` selecting by the old label, so it silently
  re-pointed at a *different* control (the bulk action) and failed. I had run the file but
  read the test names through a `grep | head` filter instead of the summary line, then wrote
  "re-run → pass" into the execution log. **That false claim has been corrected and the
  correction is recorded, not quietly edited out.**
- **`LoginPage.tsx` breached its page-size ratchet** (361 vs a 353 ceiling). Fixed by
  extracting the handler rather than raising the ratchet — the file is now 350 lines, three
  *below* its original ceiling, with the ratchet untouched.
- A new helper exported two functions nothing used, turning the dead-code gate red.
- A per-question badge still said "Accept all" — pre-existing, but my rename made the row read
  "Accept all" beside "Accept this one".
- An inaccurate justification in one of my own comments, and a citation of three test suites
  that could not have failed if the reduced-motion fix were deleted.

All are fixed and retested. `REGRESSION-AND-INDEPENDENT-REVIEW.md` carries the full
dispositions, including what the reviewers verified as *correct*.

## What is proven, and what is not

**Proven:** format, lint, typecheck, build, dead-code and the reproducible contrast audit all
pass; **114 of 114 unit/component test files pass**; **68 of 68 browser tests pass** — 8 smoke
journeys against a real seeded API (sign-in, registration, a streamed grounded answer, a
refusal, a full quiz attempt, the teacher dashboard) plus **60 visual baselines across 5
screens × light/dark × Bangla/English × 3 viewports, with no re-baselining**. No feature was
removed, disabled, orphaned or mocked; no API contract, permission, validation rule or state
transition was altered.

**Not proven:** roughly 190 of ~200 capability rows have not been individually executed end to
end — they are covered by the register, the unit suite and the smoke/visual sweeps, not by a
per-feature functional test. No real assistive-technology pass. No field performance data. No
Android/WebView check (no `java`, `gradle` or `adb` on this machine — and browser viewport
emulation is never reported as device testing). No usability testing with real users.

## Deliberately not done

Collapsing the duplicated button/stat vocabularies and subtracting the decorative layer
(three blurred "aurora" blobs on a 16 s loop behind the home hero, a shine sweep on every
button hover, 86 `box-shadow` declarations). The reason is not cost — it is that this change
invalidates nearly all 60 visual baselines at once, and doing it without completing the full
capture-review-rebaseline cycle would produce exactly the "attractive diff, green-looking
report, no real verification" outcome the task forbids. **It is the top recommendation for the
next wave**, along with four unconfirmed destructive actions that were left alone because the
feature lock names confirmations explicitly.

## Honest framing

This delivery is worth more for what it repaired in the *verification system* than for what it
changed on screen. The highest-value outcome is that the guard suite can now see a third of the
palette it previously could not, so the next palette change cannot move twenty unguarded
colour pairs silently. The visible diff is small by design.
