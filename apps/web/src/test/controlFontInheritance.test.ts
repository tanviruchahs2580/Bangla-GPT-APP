import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Font A fidelity (2026-11-20). The owner kept the shipped type system (Noto
// Sans Bengali, the --fs-* scale); what made it look "below standard" was that
// form controls never inherited it. A browser sweep of every role's routes
// found Bangla labels on .chip, .suggest-chip, .quiz-option, .subject-card,
// the forgot-page mode switch and the admin role <select>s rendering in the
// UA control font (Arial, which falls back to Nirmala UI for Bengali on
// Windows) at the 13.33px UA size. These guards keep the fix in place.
//
// vitest runs with cwd = apps/web (see w2_i18n_css_typography.test.ts).
const ROOT = resolve(process.cwd(), "src");
const css = readFileSync(resolve(ROOT, "styles.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

/** Body of the first rule whose selector list is exactly `selector`. */
function ruleBody(selector: string): string | null {
  const escaped = selector
    .split(",")
    .map((part) => part.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("\\s*,\\s*");
  const match = css.match(
    new RegExp(`(?:^|})\\s*${escaped}\\s*{([^}]*)}`, "m"),
  );
  return match ? match[1] : null;
}

describe("form controls render in the app font", () => {
  it("inherits font-family on every native control element", () => {
    const body = ruleBody("button, input, select, textarea, optgroup");
    expect(body, "global control font rule is missing").not.toBeNull();
    expect(body).toMatch(/font-family:\s*inherit/);
    // Only the family: sizes and line-heights stay with each component so no
    // type-scale token moves (the owner's Font A decision).
    expect(body).not.toMatch(/font-size|line-height|font:\s/);
  });

  it.each([".suggest-chip", ".quiz-option", ".subject-card .subject-name"])(
    "%s sizes its text from the type scale, not the 13.33px UA default",
    (selector) => {
      const body = ruleBody(selector);
      expect(body, `${selector} rule is missing`).not.toBeNull();
      expect(body).toMatch(/font-size:\s*var\(--fs-(?:xs|sm|md|lg)\)/);
    },
  );

  it("stacks stat value and label even when they are spans", () => {
    const body = ruleBody(".stat-value, .stat-label");
    expect(body).not.toBeNull();
    expect(body).toMatch(/display:\s*block/);
  });
});

describe("offline fallback page", () => {
  const publicDir = resolve(process.cwd(), "public");
  const html = readFileSync(resolve(publicDir, "offline.html"), "utf8");

  it("declares the self-hosted Noto faces it names, from files that exist", () => {
    const sources = [
      ...html.matchAll(
        /@font-face\s*{[^}]*font-family:\s*"Noto Sans Bengali"[^}]*src:\s*url\("([^"]+)"\)/g,
      ),
    ].map((m) => m[1]);
    expect(sources.length).toBeGreaterThanOrEqual(2);
    for (const src of sources) {
      expect(src.startsWith("/fonts/"), src).toBe(true);
      expect(existsSync(resolve(publicDir, src.slice(1))), src).toBe(true);
    }
  });
});
