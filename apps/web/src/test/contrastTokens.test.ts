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
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(resolve(process.cwd(), "src", "styles.css"), "utf8");

const LIGHT = parseBlock(CSS, ":root {");
const DARK = { ...LIGHT, ...parseBlock(CSS, '[data-theme="dark"] {') };

function parseBlock(css: string, marker: string): Record<string, string> {
  const start = css.indexOf(marker);
  const block = css.slice(start, css.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    out[m[1]] = m[2].trim();
  }
  return out;
}

function toRgb(hex: string): [number, number, number] {
  const h = hex.trim().replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [
    number,
    number,
    number,
  ];
}

function channel(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const [r, g, b] = toRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function ratio(fg: string, bg: string): number {
  const [lo, hi] = [luminance(fg), luminance(bg)].sort((a, b) => a - b);
  return (hi + 0.05) / (lo + 0.05);
}

/** rgba(255,255,255,alpha) composited over a fill — .btn-primary/.btn-teal
    layer a 14% white highlight on their top edge. */
function overWhite(hex: string, alpha: number): string {
  const comp = toRgb(hex).map((c) => c * (1 - alpha) + 255 * alpha);
  return comp.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("");
}

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
