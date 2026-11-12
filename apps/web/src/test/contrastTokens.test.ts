/**
 * A11Y-04 / UX-10 (F-004): the white label on the accent-gradient fills
 * (.btn-primary, .btn-teal, .chip.active, .bubble.user, .impersonation-banner,
 * the notification badge) measured 1.4–3.2:1 in dark mode, and the light
 * gradient tails failed too. axe cannot see gradient backgrounds (it reports
 * them "incomplete"), so this test pins the ratios and the wiring straight
 * from styles.css: every white-label fill must sit on the theme-invariant
 * *-solid tokens, and each gradient stop plus the .btn-primary/.btn-teal 14%
 * top highlight must keep the label at 4.5:1 in BOTH themes.
 */
import { describe, expect, it } from "vitest";
import {
  blockCounts,
  overWhite,
  ratio,
  readStyles,
  resolveToken,
  rulesForSelector,
  tokenNamesByBlock,
  themeTokens,
} from "./cssTokens";

const CSS = readStyles();

// Both token pairs, merged across EVERY block. Before this the guard read only
// the first `:root`/dark pair, so the v3-extended block further down the file
// escaped all 30-odd assertions below -- see cssTokens.ts.
const { light: LIGHT, dark: DARK } = themeTokens(CSS);

/** Body of the last rule whose selector is exactly `selector`. */
function lastRule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matches = [
    ...CSS.matchAll(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, "g")),
  ];
  expect(matches.length, `no rule for ${selector}`).toBeGreaterThan(0);
  return matches[matches.length - 1][1];
}

describe("white-label fills (F-004)", () => {
  it.each(["brand-solid", "brand-solid-strong", "danger-solid"])(
    "--%s clears 4.5:1 under #fff in both themes",
    (token) => {
      expect(ratio("#ffffff", LIGHT[token])).toBeGreaterThanOrEqual(4.5);
      expect(ratio("#ffffff", DARK[token])).toBeGreaterThanOrEqual(4.5);
    },
  );

  it("every stop of the white-label gradient tokens is a solid fill pair", () => {
    expect(LIGHT["grad-brand-solid"]).toMatch(
      /linear-gradient\(\s*135deg,\s*var\(--brand-solid\),\s*var\(--brand-solid-strong\)\s*\)/,
    );
    expect(LIGHT["grad-cta"]).toBe("var(--grad-brand-solid)");
    expect(LIGHT["grad-teal"]).toMatch(
      /linear-gradient\(\s*135deg,\s*var\(--teal-solid\),\s*var\(--teal-solid-strong\)\s*\)/,
    );
    // The pre-fix dark overrides ended in the light #22c55e/#4ade80 accents.
    expect(CSS).not.toMatch(/--grad-cta:\s*linear-gradient/);
    for (const token of ["teal-solid", "teal-solid-strong"]) {
      expect(ratio("#ffffff", LIGHT[token])).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the button top highlight cannot pull a white label under 4.5:1", () => {
    for (const token of ["brand-solid", "teal-solid"]) {
      const lifted = `#${overWhite(LIGHT[token], 0.14)}`;
      expect(
        ratio("#ffffff", lifted),
        `#fff on ${token} +14% white highlight`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps the white-label surfaces on the solid tokens", () => {
    expect(lastRule(".btn-primary")).toContain("var(--grad-cta)");
    expect(lastRule(".btn-teal")).toContain("var(--grad-teal)");
    expect(lastRule(".chip.active")).toContain("background: var(--grad-cta)");
    expect(lastRule(".bubble.user")).toContain(
      "background: var(--grad-brand-solid)",
    );
    expect(lastRule(".impersonation-banner")).toContain(
      "background: var(--brand-solid)",
    );
    expect(lastRule(".notif-badge")).toContain(
      "background: var(--danger-solid)",
    );
  });

  it("carries white glyphs on icon tiles at 3:1 or better", () => {
    const tiles: Array<[string, string, string]> = [
      [".tile-teal", "teal-solid", "teal-solid-strong"],
      [".tile-warn", "warn-solid", "warn-solid-strong"],
      [".tile-ai", "ai-solid", "ai-solid-strong"],
    ];
    for (const [selector, from, to] of tiles) {
      expect(lastRule(selector)).toContain(`var(--${from})`);
      expect(lastRule(selector)).toContain(`var(--${to})`);
      for (const token of [from, to]) {
        expect(
          ratio("#ffffff", LIGHT[token]),
          `#fff on ${selector} stop ${token}`,
        ).toBeGreaterThanOrEqual(3);
      }
    }
  });
});

/**
 * F-199 (UX-01): twenty loose hex values sat outside the token blocks, so a
 * theme or brand change had to chase them — the 2026-10-27 dark `.primary`
 * bug was one of them. The loose values are named tokens now, and this guard
 * fails on any hex that is not a `--token: …` declaration or a comment, so
 * the next one cannot land quietly.
 */
describe("no loose colour literals (F-199)", () => {
  const HEX =
    /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b/;

  it("every hex value in styles.css is a token declaration or a comment", () => {
    // Blank the comments while keeping every newline, so reported line
    // numbers still point at the real file.
    const masked = CSS.replace(/\/\*[\s\S]*?\*\//g, (block) =>
      block.replace(/[^\n]/g, " "),
    );
    const loose: string[] = [];
    masked.split("\n").forEach((line, index) => {
      if (!HEX.test(line)) return;
      if (/^\s*--[a-z0-9-]+\s*:/.test(line)) return;
      loose.push(`styles.css:${index + 1}: ${line.trim()}`);
    });
    expect(
      loose,
      `colour literals outside the token blocks:\n${loose.join("\n")}`,
    ).toEqual([]);
  });

  it("defines the ink, print and highlight tokens the rules now use", () => {
    expect(LIGHT["on-brand"]).toBe("var(--white)");
    expect(LIGHT["white"]).toBe("#ffffff");
    expect(LIGHT["print-ink"]).toBe("#000000");
    expect(DARK["on-brand"]).toBeDefined();
  });
});

/**
 * A11Y (guard-coverage): regression guard for the blind spot itself.
 *
 * styles.css declares `:root` and `[data-theme="dark"]` twice each. The old
 * `indexOf` parser saw only the first of each, so 11 light tokens and 6 dark
 * tokens were outside every ratio assertion in the repo. This test fails if a
 * parser ever stops merging all of them again.
 */
describe("token-block coverage (guard regression)", () => {
  it("merges every block of each theme, not just the first", () => {
    const counts = blockCounts(CSS);
    expect(counts.light, ":root blocks").toBeGreaterThanOrEqual(2);
    expect(counts.dark, "dark blocks").toBeGreaterThanOrEqual(2);

    // Tokens that exist ONLY in the later pair. If the parser regressed to
    // `indexOf`, these would all be undefined.
    for (const token of [
      "ring-glow",
      "quick-shadow",
      "quick-shadow-hover",
      "aurora-1",
      "aurora-2",
      "aurora-3",
      "ease-bounce",
      "ease-soft",
      "m-xs",
      "m-page",
      "grad-shine",
    ]) {
      expect(
        LIGHT[token],
        `--${token} not merged from the later :root`,
      ).toBeDefined();
    }
  });

  it("keeps the later :root disjoint from the earlier dark block (cascade trap)", () => {
    // themeTokens() merges every block, which is right for READING values. But
    // CSS resolves a token by SOURCE POSITION, not by block kind: the later
    // `:root` sits after the first `[data-theme="dark"]` block at equal
    // specificity, so a name declared in both would resolve to the LATER one in
    // dark mode -- the light block would win -- while the merged map reported
    // the dark value. Nothing overlaps today; this keeps it that way.
    const blocks = tokenNamesByBlock(CSS);
    const lastRoot = blocks.map((b) => b.theme).lastIndexOf("light");
    expect(lastRoot, "expected more than one :root block").toBeGreaterThan(0);

    const declaredBefore = new Set(
      blocks.slice(0, lastRoot).flatMap((b) => b.names),
    );
    const clash = [...new Set(blocks[lastRoot].names)].filter((n) =>
      declaredBefore.has(n),
    );
    expect(
      clash,
      `token(s) declared in the later :root AND in an earlier block: ${clash.join(", ")}`,
    ).toEqual([]);
  });
});

/**
 * A11Y (hero placeholder): the home hero's ask-input was the one input in the
 * product whose placeholder was pinned by token -- and it failed. #6b7a66 on
 * the fill measured 4.24:1 at the lightest gradient stop, under the 4.5:1
 * text minimum, on the most prominent control a student touches.
 *
 * The fill is a LITERAL near-white in both themes, so the placeholder token
 * must be theme-invariant. That assumption is asserted here rather than
 * assumed, so theming the fill later fails loudly instead of silently
 * inverting the ratio.
 */
describe("hero prompt placeholder contrast (A11Y)", () => {
  const FILL = ".hero .home-prompt .input";
  const PLACEHOLDER = ".hero .home-prompt .input::placeholder";

  it("keeps the near-white hero fill literal, as the ratio depends on it", () => {
    expect(lastRule(FILL)).toContain("rgba(255, 255, 255, 0.96)");
  });

  it("keeps the hero placeholder token theme-invariant", () => {
    // Declared once in :root and never overridden in dark. DARK is the merged
    // map (dark inherits light), so the invariant to assert is that the dark
    // layer did not move it -- not that the key is absent, which it never is.
    expect(LIGHT["hero-placeholder"]).toBeDefined();
    expect(
      DARK["hero-placeholder"],
      "--hero-placeholder must resolve identically in both themes",
    ).toBe(LIGHT["hero-placeholder"]);
    expect(lastRule(PLACEHOLDER)).toContain("var(--hero-placeholder)");
  });

  it("clears 4.5:1 on the fill over every --grad-hero stop", () => {
    const placeholder = resolveToken(LIGHT, "hero-placeholder");
    for (const stop of ["brand-ink", "brand", "brand-strong"]) {
      const fill = `#${overWhite(resolveToken(LIGHT, stop), 0.96)}`;
      expect(
        ratio(placeholder, fill),
        `${placeholder} on the hero fill over --${stop}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});

/**
 * A11Y (placeholder coverage): the hero prompt was the ONLY rule in the whole
 * stylesheet that styled a placeholder. Every other input fell through to the
 * user agent's own colour, which no guard can measure and which was never
 * chosen for our dark `--card: #1b1e14`. One token, one global rule.
 */
describe("global placeholder token (A11Y)", () => {
  it("declares one bare ::placeholder rule driven by --placeholder", () => {
    // Exact-selector match: `.hero .home-prompt .input::placeholder` also ends
    // in `::placeholder` and would satisfy a substring search on its own.
    const bodies = rulesForSelector(CSS, "::placeholder");
    const global = bodies.find((b) => b.includes("var(--placeholder)"));
    expect(
      global,
      "no `::placeholder` rule driving --placeholder",
    ).toBeDefined();
    // Firefox dims placeholders with its own opacity, which would multiply the
    // ratio straight back below 4.5:1.
    expect(global).toContain("opacity: 1");
  });

  it("clears 4.5:1 on every surface an input can be painted on", () => {
    for (const [name, theme] of [
      ["light", LIGHT],
      ["dark", DARK],
    ] as const) {
      const placeholder = resolveToken(theme, "placeholder");
      for (const surface of ["card", "card-2", "bg-elev", "bg"]) {
        expect(
          ratio(placeholder, resolveToken(theme, surface)),
          `${name}: --placeholder on --${surface}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});

/**
 * A11Y (progress ring): the empty arc was painted with
 * color-mix(--line 70%, transparent) over --card, i.e. 1.21:1 light / 1.16:1
 * dark. A ring communicates a proportion through the arc-versus-track
 * boundary, so an invisible track makes the graphic unreadable. --line-strong
 * already carries a 3:1 contract on these surfaces (formControlBoundary), so
 * reusing it puts the track under an enforced floor instead of a new token.
 *
 * KNOWN LIMIT, recorded rather than papered over: the arc-versus-track
 * boundary is still below 3:1 (1.55:1 light / 2.81:1 dark) because the arc is
 * read by hue. Lifting that needs a three-level gauge -- a design decision,
 * tracked as R-15 in docs/frontend-renovation/RISK-REGISTER.md.
 */
describe("progress-ring track contrast (A11Y)", () => {
  it("uses --line-strong, which owns the 3:1 boundary contract", () => {
    expect(lastRule(".ring")).toContain("var(--line-strong)");
  });

  it("clears 3:1 against --card in both themes", () => {
    for (const [name, theme] of [
      ["light", LIGHT],
      ["dark", DARK],
    ] as const) {
      expect(
        ratio(resolveToken(theme, "line-strong"), resolveToken(theme, "card")),
        `${name}: ring track on --card`,
      ).toBeGreaterThanOrEqual(3);
    }
  });
});

/**
 * A11Y (semantic pairs): these label-on-soft-tint pairs were rendered all over
 * the product but were covered by no assertion, because the tokens they use
 * sat in the second block pair. They pass today; the point is that a palette
 * change can no longer move them quietly.
 */
describe("semantic label pairs (A11Y)", () => {
  it.each([
    ["ok", "ok-soft"],
    ["warn", "warn-soft"],
    ["danger", "danger-soft"],
    ["teal-strong", "teal-soft"],
    ["ai", "ai-soft"],
    ["muted", "card"],
    ["muted", "bg-elev"],
    ["muted", "card-2"],
    ["muted", "bg"],
    ["ink", "card"],
  ])("--%s on --%s clears 4.5:1 in both themes", (fg, bg) => {
    for (const [name, theme] of [
      ["light", LIGHT],
      ["dark", DARK],
    ] as const) {
      expect(
        ratio(resolveToken(theme, fg), resolveToken(theme, bg)),
        `${name}: --${fg} on --${bg}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});

/**
 * NOT asserted here, deliberately: two mixed surfaces measure below the 3:1
 * non-text floor and are recorded as owner decisions instead of being pinned
 * as passing, because the fix would change a visual decision:
 *
 *   .ring arc vs its track   1.55:1 light / 2.81:1 dark   (R-15)
 *   .card mixed border       1.22:1 light / 1.17:1 dark   (R-16)
 *
 * The ring TRACK itself is asserted above, because that one was unambiguous.
 */
