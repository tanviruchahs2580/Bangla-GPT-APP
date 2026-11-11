/**
 * A11Y (reduced motion) — regression guard.
 *
 * The `prefers-reduced-motion: reduce` block used to neutralise only
 * `animation-duration` and `transition-duration`. That was not enough to
 * actually remove motion:
 *
 *   - 15 `animation-delay` declarations survived, and with
 *     `animation-fill-mode: both` plus `from { opacity: 0 }` the staggered
 *     children were still held invisible for up to ~340ms each, so the page
 *     "popped in" late for exactly the users who asked for no motion;
 *   - collapsing the duration of an `infinite` decorative loop restarts it
 *     ~1000x/second, which is more work than not collapsing it at all.
 *
 * This file exists because the fix shipped with no test of its own: the three
 * suites that were re-run next to it (tutorAutoScroll, skipLink,
 * w2_i18n_css_typography) cannot fail if these declarations are deleted.
 */
import { describe, expect, it } from "vitest";
import { readStyles, rulesMatchingMember } from "./cssTokens";

const CSS = readStyles();

/** Body of the `prefers-reduced-motion: reduce` at-rule. */
function reducedMotionBlock(): string {
  const open = CSS.search(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{/);
  expect(open, "no prefers-reduced-motion block").toBeGreaterThanOrEqual(0);
  const start = CSS.indexOf("{", open) + 1;
  let i = start;
  let depth = 1;
  while (i < CSS.length && depth > 0) {
    if (CSS[i] === "{") depth += 1;
    else if (CSS[i] === "}") depth -= 1;
    i += 1;
  }
  return CSS.slice(open, i);
}

describe("reduced motion (A11Y)", () => {
  it("neutralises duration for every element, pseudo included", () => {
    const body = reducedMotionBlock();
    expect(body).toContain("animation-duration: 0.001ms !important");
    expect(body).toContain("transition-duration: 0.001ms !important");
    // `*` alone would miss every ::before/::after decoration.
    expect(body).toContain("*::before");
    expect(body).toContain("*::after");
  });

  it("removes the stagger, not just the duration", () => {
    const body = reducedMotionBlock();
    expect(body).toContain("animation-delay: 0s !important");
    expect(body).toContain("transition-delay: 0s !important");
  });

  it("stops infinite loops from being restarted a thousand times a second", () => {
    expect(reducedMotionBlock()).toContain(
      "animation-iteration-count: 1 !important",
    );
  });

  it("has a real stagger to neutralise, so the assertions above mean something", () => {
    // If the file ever loses its delayed animations, the delay reset becomes
    // vacuous and this test should be revisited rather than left to pass by
    // accident.
    const outside = CSS.replace(reducedMotionBlock(), "");
    const delays = [...outside.matchAll(/animation-delay:\s*([^;]+);/g)].filter(
      (m) => !/^\s*0s/.test(m[1]),
    );
    expect(
      delays.length,
      "no non-zero animation-delay outside the reduced-motion block",
    ).toBeGreaterThan(0);
  });

  it("keeps scroll behaviour instant rather than smooth", () => {
    expect(reducedMotionBlock()).toContain("scroll-behavior: auto !important");
  });

  it("leaves a non-motion channel on every live indicator", () => {
    // `animation-iteration-count: 1` is only safe because these elements still
    // convey their state without pulsing. Each entry is the declaration that
    // keeps the element perceivable once the animation stops -- verified
    // against the stylesheet, not assumed.
    const channels: Array<[string, string[], string]> = [
      [
        ".stream-cursor",
        ["background", "width", "height"],
        "the streaming caret is a filled block, so it stays visible at rest",
      ],
      [
        ".voice-btn.recording::after",
        ["border", "opacity"],
        "the recording ring keeps a 0.6-opacity danger border at rest",
      ],
    ];
    for (const [selector, props, why] of channels) {
      const bodies = rulesMatchingMember(CSS, selector).join("\n");
      for (const prop of props) {
        expect(bodies, `${selector}: ${why} (needs ${prop})`).toContain(prop);
      }
    }
  });
});
