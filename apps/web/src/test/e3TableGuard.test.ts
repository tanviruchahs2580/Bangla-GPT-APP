import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// E3 (2026-11-17 elevation audit): the staff tables were the loudest
// "demo" surface — 10/12px cells, hairline zebra rows, and a 560px
// min-width that forced horizontal scroll on phones with no fallback.
// These guards pin the elevated table style, the card fallback, and the
// staff page-header layer.
const ROOT = resolve(process.cwd());
const css = readFileSync(resolve(ROOT, "src/styles.css"), "utf8");

const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");

function ruleFor(selector: string): string {
  const at = stripped.indexOf(selector);
  expect(at, `${selector} must exist in styles.css`).toBeGreaterThanOrEqual(0);
  const open = stripped.indexOf("{", at);
  const close = stripped.indexOf("}", open);
  return stripped.slice(open, close);
}

describe("table.data elevation", () => {
  it("drops zebra striping in favour of the hover affordance", () => {
    expect(stripped).not.toMatch(/table\.data tbody tr:nth-child\(even\)/);
    expect(ruleFor("table.data tbody tr:hover")).toMatch(
      /color-mix\(in srgb, var\(--brand-soft\)/,
    );
  });

  it("uses the spacing scale for cell padding and a softer separator", () => {
    const rule = ruleFor("table.data th,");
    expect(rule).toMatch(/padding:\s*var\(--space-3\)\s+var\(--space-4\)/);
    expect(rule).toMatch(/color-mix\(in srgb, var\(--line\) 60%/);
  });

  it("keeps the header quiet (600, not 700) and Bengali-safe", () => {
    const rule = ruleFor("table.data thead th");
    expect(rule).toMatch(/font-weight:\s*600/);
    expect(rule).not.toMatch(/letter-spacing/);
    expect(rule).not.toMatch(/text-transform/);
  });
});

describe("mobile card fallback (cardable)", () => {
  it("collapses opted-in tables into labelled cards under 760px", () => {
    // The card block runs from the first cardable rule up to the
    // page-head block that follows it (prettier separates closing braces
    // with newlines, so brace-counting on "}}" never terminates).
    const media = stripped.slice(stripped.indexOf("table.data.cardable"));
    const block = media.slice(0, media.indexOf(".page-head"));
    expect(block).toMatch(/min-width:\s*0/);
    expect(block).toMatch(/content:\s*attr\(data-label\)/);
    expect(block).toMatch(/clip-path:\s*inset\(50%\)/);
  });

  it("is adopted by the highest-traffic staff tables", () => {
    for (const file of [
      "src/pages/ParentDashboard.tsx",
      "src/pages/AdminDashboard.tsx",
    ]) {
      const src = readFileSync(resolve(ROOT, file), "utf8");
      expect(src, file).toContain('className="data cardable"');
      expect(src, file).toContain("data-label=");
    }
  });
});

describe("staff page-header layer", () => {
  it("adds a context line under the parent and admin titles", () => {
    const parent = readFileSync(
      resolve(ROOT, "src/pages/ParentDashboard.tsx"),
      "utf8",
    );
    const admin = readFileSync(
      resolve(ROOT, "src/pages/AdminDashboard.tsx"),
      "utf8",
    );
    expect(parent).toContain('className="page-sub"');
    expect(admin).toContain('className="page-sub"');
    expect(ruleFor(".page-sub")).toMatch(/var\(--muted\)/);
  });
});
