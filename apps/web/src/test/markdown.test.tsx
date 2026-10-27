import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { SafeMarkdown } from "../lib/safeMarkdown";

describe("SafeMarkdown", () => {
  it("renders inline math as KaTeX", () => {
    const { container } = render(
      <SafeMarkdown content="Formula $E=mc^2$ test" />,
    );
    // KaTeX renders with class 'katex'
    expect(container.innerHTML).toContain("katex");
    expect(container.textContent).toContain("E=mc");
  });

  it("sanitizes XSS payload — script tag stripped", () => {
    const xss = "Hello <script>alert(1)</script> world";
    const { container } = render(<SafeMarkdown content={xss} />);
    expect(container.innerHTML).not.toContain("<script>");
    expect(container.textContent).toContain("Hello");
    expect(container.textContent).toContain("world");
  });

  it("renders markdown headings and lists", () => {
    const md = "## Title\n- item 1\n- item 2";
    const { container } = render(<SafeMarkdown content={md} />);
    expect(container.innerHTML).toContain("<h2");
    expect(container.innerHTML).toContain("<li");
  });

  // F-039: only same-origin paths may be an image source — an <img> fetches
  // automatically, so a model-authored remote URL leaked the reader's IP and
  // confirmed the answer was seen wherever no CSP was deployed.
  it("renders a same-origin image path and lazy-loads it", () => {
    const { container } = render(
      <SafeMarkdown content="![cell diagram](/assets/cell.png)" />,
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe("/assets/cell.png");
    expect(img?.getAttribute("loading")).toBe("lazy");
    expect(img?.getAttribute("alt")).toBe("cell diagram");
  });

  it("drops a remote image and keeps only its alt text", () => {
    const { container } = render(
      <SafeMarkdown content="![tracker](https://evil.example/pixel.png)" />,
    );
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.textContent).toContain("tracker");
  });

  it("drops a protocol-relative image (remote host in disguise)", () => {
    const { container } = render(
      <SafeMarkdown content="![x](//evil.example/pixel.png)" />,
    );
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });
});

// CodeQL js/bad-tag-filter triage (docs/security/codeql-triage-2026-10-27.md):
// the primary xss control is the *absence* of rehype-raw -- react-markdown
// renders raw HTML as text while that plugin list stays clean. The regex
// scrub in safeMarkdown.tsx is only the belt-and-suspenders pass. Pin the
// invariant here so a future "add rehype-raw" change cannot slide the whole
// guard away without failing CI.
describe("safeMarkdown plugin invariants", () => {
  it("never enables the raw-HTML rehype lane", async () => {
    const module = await import("../../src/lib/safeMarkdown");
    // no configurable plugin surface exposed: re-render is the assertion
    expect(typeof module.SafeMarkdown).toBe("function");
    const src = (await import("node:fs"))
      .readFileSync(resolve(process.cwd(), "src/lib/safeMarkdown.tsx"), "utf8")
      // strip comments first: the guard exists precisely so even a comment
      // mentioning the plugin keeps documenting WHY it must not appear.
      .replace(/\/\/[^\n]*/g, "")
      .replace(/\/\*[\s\S]*?\*\//g, "");
    expect(src, "rehype-raw must never enter the plugin lane").not.toContain(
      "rehype-raw",
    );
    expect(src, "sanitizer must never parse HTML into the DOM").not.toContain(
      "dangerouslySetInnerHTML",
    );
  });
});
