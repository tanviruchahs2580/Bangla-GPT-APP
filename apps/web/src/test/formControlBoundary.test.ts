/**
 * UX-008: the resting boundary of a form control is non-text UI, so WCAG
 * 1.4.11 asks for 3:1 against the surface it sits on. The filled controls
 * here (.input/.select/.textarea, .chip, .quiz-option, .suggest-chip,
 * button.secondary) are all `--card` filled, and `--card` is only 1.13:1
 * against `--bg` in light mode and 1.10:1 in dark — so the 1.5px border is
 * the control's only edge, and `--line-strong` was the token carrying it at
 * 1.62:1 (light) and 1.61:1 (dark).
 *
 * axe cannot see this (it treats border contrast as "incomplete" and it runs
 * on the rendered light theme only), which is why the floors are pinned here
 * for BOTH themes, computed from styles.css with the relative-luminance
 * formula from WCAG 2.2 §1.4.4. The assertion is the 3:1 floor, not the
 * current value, so a later palette pass can move the token again as long as
 * the boundary keeps its contrast.
 *
 * The white-label fills on the same controls have their own guard
 * (contrastTokens.test.ts); this file only covers the resting boundary.
 */
import { describe, expect, it } from "vitest";
import { ratio, readStyles, themeTokens } from "./cssTokens";

const CSS = readStyles();

// Merged across EVERY token block, both themes. Reading only the first
// `:root`/dark pair left 11 light and 6 dark tokens outside this guard --
// the v3-extended set (--ease-*, --m-xs/--m-page, --grad-shine, --ring-glow,
// --quick-shadow*, --aurora-*). See cssTokens.ts.
const { light: LIGHT, dark: DARK } = themeTokens(CSS);

/**
 * Every declaration block whose selector, whitespace-collapsed, is exactly
 * `selector`, joined. The cascade splits a component across rules (the v2
 * `.chip` block re-states only the radius), so a boundary claim has to ask
 * whether the token is the border SOMEWHERE for this selector rather than
 * whether the last block repeats it.
 */
function allRules(selector: string): string {
  const wanted = selector.replace(/\s+/g, " ").trim();
  const bodies = [...CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) => m[1].replace(/\s+/g, " ").trim() === wanted)
    .map((m) => m[2]);
  expect(bodies.length, `no rule for ${selector}`).toBeGreaterThan(0);
  return bodies.join("\n");
}

// Every surface a control can be painted on, so a darker token cannot pass by
// having been measured against the kindest one.
const LIGHT_SURFACES = ["card", "card-2", "bg-elev", "bg"];
const DARK_SURFACES = ["card", "card-2", "bg-elev", "bg"];

describe("form-control boundaries (UX-008)", () => {
  it.each([
    ["light", LIGHT, LIGHT_SURFACES],
    ["dark", DARK, DARK_SURFACES],
  ])("--line-strong clears 3:1 on every %s surface", (_name, theme, keys) => {
    for (const key of keys) {
      expect(
        ratio(theme["line-strong"], theme[key]),
        `--line-strong vs --${key}`,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it("keeps the filled controls on --card with --line-strong as their border", () => {
    // The selector group the fix is about, exactly as styles.css declares it.
    const input = allRules(".input, .select, .textarea");
    expect(input).toContain("border: 1.5px solid var(--line-strong)");
    expect(input).toContain("background: var(--card)");
    for (const selector of [".chip", ".quiz-option", ".suggest-chip"]) {
      const rules = allRules(selector);
      expect(rules, `${selector} border`).toContain("var(--line-strong)");
      expect(rules, `${selector} fill`).toContain("background: var(--card)");
    }
    expect(allRules("button.secondary")).toContain("var(--line-strong)");
  });
});
