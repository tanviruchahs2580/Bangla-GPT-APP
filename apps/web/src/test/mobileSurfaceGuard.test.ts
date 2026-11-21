import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

// M1 (2026-11-17 mobile audit): the mobile-correctness surfaces are checked
// statically because no Android/iOS device runs on this machine (repo §13) —
// the same reasoning as w2_i18n_css_typography. Each rule here guards a fix
// for a measured defect: the keyboard covering the tutor composer, the notch
// overlapping sticky chrome, the unstyled update banner, and sub-44px touch
// targets.
const ROOT = resolve(process.cwd());
const css = readFileSync(resolve(ROOT, "src/styles.css"), "utf8");
const html = readFileSync(resolve(ROOT, "index.html"), "utf8");

/** Comments out of the way, so a declaration can be attributed to a rule. */
const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");

function ruleFor(selector: string): string {
  const at = stripped.indexOf(selector);
  expect(at, `${selector} must exist in styles.css`).toBeGreaterThanOrEqual(0);
  const open = stripped.indexOf("{", at);
  const close = stripped.indexOf("}", open);
  return stripped.slice(open, close);
}

describe("mobile viewport + PWA meta (index.html)", () => {
  it("resizes the layout viewport for the soft keyboard", () => {
    // Chrome 108+ defaults to resizes-visual, which leaves the sticky tutor
    // composer under the keyboard on mobile. resizes-content restores the
    // classic behaviour the composer's sticky positioning assumes.
    const viewport =
      html.match(/name="viewport"\s+content="([^"]+)"/s)?.[1] ?? "";
    expect(viewport).toContain("viewport-fit=cover");
    expect(viewport).toContain("interactive-widget=resizes-content");
  });

  it("keeps the iOS home-screen label short enough to render", () => {
    const title = html.match(
      /apple-mobile-web-app-title"\s+content="([^"]+)"/s,
    )?.[1];
    expect(title).toBe("বাংলা GPT");
  });
});

describe("safe-area coverage in styles.css", () => {
  it("grows the sticky topbar by the notch inset", () => {
    const rule = ruleFor(".topbar");
    expect(rule).toMatch(
      /height:\s*calc\(var\(--topbar-h\)\s*\+\s*env\(safe-area-inset-top/,
    );
    // The EFFECTIVE top padding must carry the inset. This guard used to pin
    // a `padding-top: env(...)` that a later `padding: 0 ...` shorthand in
    // the same rule silently reset to 0, so it passed while the header
    // content sat partly under the status bar. Now: the inset is the first
    // value of the one shorthand, and no padding-top/shorthand follows it.
    expect(rule).toMatch(/padding:\s*env\(safe-area-inset-top/);
    const paddings = [...rule.matchAll(/padding(-top)?\s*:/g)];
    expect(paddings).toHaveLength(1);
  });

  it("keeps the offline banner clear of the notch when it is the stuck chrome", () => {
    expect(ruleFor(".offline-banner")).toMatch(/env\(safe-area-inset-top/);
  });

  it("pads the modal sheet past the notch and home indicator", () => {
    const rule = ruleFor(".modal-backdrop");
    expect(rule).toMatch(/env\(safe-area-inset-top/);
    expect(rule).toMatch(/env\(safe-area-inset-bottom/);
  });

  it("raises toasts above the bottombar's own safe-area padding", () => {
    expect(ruleFor(".toast-region")).toMatch(/env\(safe-area-inset-bottom/);
  });

  it("pads the splash past the notch and home indicator", () => {
    const rule = ruleFor(".splash");
    expect(rule).toMatch(/env\(safe-area-inset-top/);
    expect(rule).toMatch(/env\(safe-area-inset-bottom/);
  });
});

describe("update banner (PWA-02 surface)", () => {
  it("is styled and fixed above the bottombar", () => {
    // The banner previously had no stylesheet at all: it rendered as an
    // unstyled block behind the fixed bottombar, unreachable on a phone.
    const rule = ruleFor(".update-banner");
    expect(rule).toMatch(/position:\s*fixed/);
    expect(rule).toMatch(/env\(safe-area-inset-bottom/);
    expect(rule).toMatch(/z-index:\s*var\(--z-toast\)/);
  });
});

describe("F-110 tap-target floor extension", () => {
  it("covers the controls the mobile audit measured under 44px", () => {
    const coarse = stripped.slice(stripped.indexOf("@media (pointer: coarse)"));
    const block = coarse.slice(
      0,
      coarse.indexOf("}", coarse.indexOf(".btn-sm")),
    );
    for (const selector of [".source-chip", ".weak-chip", ".btn-sm"]) {
      expect(block).toContain(selector);
    }
    expect(ruleFor(".modal-close")).toMatch(/height:\s*44px/);
  });
});

describe("theme-color meta sync (manual toggle)", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.head.innerHTML =
      '<meta name="theme-color" content="#166534">' +
      '<meta name="theme-color" content="#12140e">';
  });

  it("updates both metas to the active colour on a manual toggle", async () => {
    const { toggleTheme } = await import("../lib/theme");
    toggleTheme();
    const theme = document.documentElement.getAttribute("data-theme");
    const contents = [
      ...document.querySelectorAll('meta[name="theme-color"]'),
    ].map((m) => m.getAttribute("content"));
    // Both metas must agree, whatever the OS preference is — otherwise a
    // forced theme leaves the browser UI in the opposite colour.
    expect(new Set(contents).size).toBe(1);
    expect(contents[0]).toBe(theme === "dark" ? "#12140e" : "#166534");
  });
});
