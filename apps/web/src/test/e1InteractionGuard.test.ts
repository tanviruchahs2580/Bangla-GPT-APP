import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// E1 (interaction integrity), checked statically for the same reason as
// w2_i18n_css_typography and mobileSurfaceGuard: the defects this wave fixes
// are structural, not behavioural — browser-chrome dialogs (window.prompt /
// window.confirm) that no theme, focus trap or axe sweep can see, an inline
// opacity transition that bypassed the motion tokens, and two colour literals
// outside the token blocks. Each rule below guards one of those fixes.
const ROOT = resolve(process.cwd());
const css = readFileSync(resolve(ROOT, "src/styles.css"), "utf8");
const uiTsx = readFileSync(resolve(ROOT, "src/components/ui.tsx"), "utf8");
const toastTs = readFileSync(resolve(ROOT, "src/lib/toast.ts"), "utf8");

/** Comments out of the way, so a declaration can be attributed to a rule. */
const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");

/** Body of the first rule whose selector matches `selector` exactly. */
function ruleFor(selector: RegExp): string {
  const at = stripped.search(selector);
  expect(at, `${selector} must exist in styles.css`).toBeGreaterThanOrEqual(0);
  const open = stripped.indexOf("{", at);
  const close = stripped.indexOf("}", open);
  return stripped.slice(open, close);
}

/** Every .ts/.tsx file under a directory, recursively. */
function tsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...tsFiles(full));
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

/**
 * The header of the CSS block that contains `index` — the text between the
 * previous rule's closing brace and the opening brace that encloses the
 * match. Used to attribute a token declaration to its block.
 */
function blockHeaderAt(index: number): string {
  const open = stripped.lastIndexOf("{", index);
  const previousClose = stripped.lastIndexOf("}", open);
  return stripped
    .slice(previousClose + 1, open)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join(" ");
}

describe("E1: no browser-chrome dialogs in product code", () => {
  it("window.prompt and window.confirm are gone from pages and components", () => {
    const offenders: string[] = [];
    for (const dir of ["src/pages", "src/components"]) {
      for (const file of tsFiles(resolve(ROOT, dir))) {
        const src = readFileSync(file, "utf8");
        if (/window\.prompt\(/.test(src) || /window\.confirm\(/.test(src)) {
          offenders.push(file);
        }
      }
    }
    expect(
      offenders,
      `browser-chrome dialogs still present in:\n${offenders.join("\n")}`,
    ).toEqual([]);
  });

  it("the ConfirmDialog primitive exists in ui.tsx exports", () => {
    expect(uiTsx).toMatch(/export function ConfirmDialog\(/);
    // Built ON the shared Modal, not a second portal/focus-trap.
    expect(uiTsx).toMatch(/<Modal open=\{open\}/);
  });
});

describe("E1: toast motion + tones", () => {
  it("keeps the toast entry on the motion tokens", () => {
    expect(ruleFor(/\.toast\s*\{/)).toMatch(
      /animation:\s*toast-in var\(--m-[\w-]+\) var\(--ease-\w+\)/,
    );
  });

  it("drives the exit from the motion tokens, not an inline transition", () => {
    const rule = ruleFor(/\.toast-out\s*\{/);
    expect(rule).toMatch(
      /animation:\s*toast-out var\(--m-fast\) var\(--ease-out\)/,
    );
    // The inline style this replaces set `transition: opacity 250ms ease`
    // from lib/toast.ts; the CSS owns the timing now.
    expect(rule).not.toMatch(/250ms/);
    expect(stripped).toMatch(/@keyframes toast-out/);
  });

  it("styles the success and danger tones with the semantic tokens", () => {
    expect(ruleFor(/\.toast-success\s*\{/)).toMatch(/var\(--ok-soft\)/);
    expect(ruleFor(/\.toast-success\s*\{/)).toMatch(/var\(--ok\)/);
    expect(ruleFor(/\.toast-danger\s*\{/)).toMatch(/var\(--danger-soft\)/);
    expect(ruleFor(/\.toast-danger\s*\{/)).toMatch(/var\(--danger\)/);
  });

  it("tags every toast with its tone class from lib/toast.ts", () => {
    expect(toastTs).toMatch(/toast-\$\{tone\}/);
    for (const tone of ["info", "success", "danger"]) {
      expect(toastTs).toMatch(new RegExp(`\\b${tone}: \\[`));
    }
  });

  it("the new keyframes are covered by the global reduced-motion kill", () => {
    // The first @media block kills every animation/transition duration for
    // all elements — toast-out (and the entry springs) need no opt-out of
    // their own. This fails if that block is ever narrowed.
    const from = stripped.indexOf("@media (prefers-reduced-motion: reduce)");
    const block = stripped.slice(from, stripped.indexOf("}", from));
    expect(block).toMatch(/animation-duration:\s*0\.001ms\s*!important/);
    expect(block).toMatch(/transition-duration:\s*0\.001ms\s*!important/);
  });
});

describe("E1: themed hero shadow + modal backdrop", () => {
  for (const token of ["hero-shadow", "modal-backdrop"]) {
    it(`--${token} is declared in :root AND in the dark block`, () => {
      const declarations = [
        ...stripped.matchAll(new RegExp(`--${token}\\s*:`, "g")),
      ].map((m) => blockHeaderAt(m.index ?? 0));
      expect(
        declarations.some((h) => h === ":root"),
        `--${token} missing from :root`,
      ).toBe(true);
      expect(
        declarations.some((h) => h.includes('[data-theme="dark"]')),
        `--${token} missing from the dark block`,
      ).toBe(true);
    });
  }

  it("the rules consume the tokens; the literals live only in the tokens", () => {
    expect(ruleFor(/\.modal-backdrop\s*\{/)).toContain("var(--modal-backdrop)");
    expect(stripped).toMatch(/box-shadow:\s*var\(--hero-shadow\)/);
    // Each literal value now exists exactly once — inside its own token
    // declaration — and nowhere as a loose rule value.
    expect(
      stripped.match(/0 18px 44px -14px rgba\(5, 46, 22, 0\.5\)/g)?.length,
    ).toBe(1);
    expect(stripped.match(/rgba\(14, 18, 38, 0\.55\)/g)?.length).toBe(1);
  });
});
