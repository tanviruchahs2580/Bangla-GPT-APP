import { describe, expect, it } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { SafeMarkdown } from "../lib/safeMarkdown";

describe("SafeMarkdown", () => {
  it("renders inline math as KaTeX once the deferred math chunk arrives", async () => {
    const { container } = render(
      <SafeMarkdown content="Formula $E=mc^2$ test" />,
    );
    // G-19: remark-math + rehype-katex + KaTeX are a deferred chunk now, so
    // the first frame is the raw answer (the same fallback the page uses) and
    // KaTeX replaces it when the chunk resolves. If this ever stops
    // resolving, math silently stays unrendered -- hence the wait.
    expect(container.textContent).toContain("E=mc");
    // 20s: the assertion is "eventually renders", and the cost is importing a
    // 274 kB chunk the whole suite competes for (measured: 306 ms alone,
    // 1.2 s on a normally loaded host, and it exceeded 5 s in a 74-file
    // parallel run on this machine). A generous margin over a measured
    // budget, not a retry: a chunk that never resolves still fails.
    await waitFor(() => expect(container.innerHTML).toContain("katex"), {
      timeout: 20000,
    });
    // KaTeX renders with class 'katex'
    expect(container.textContent).toContain("E=mc");
  });

  it("sanitizes XSS payload — script tag stripped", () => {
    const xss = "Hello <script>alert(1)</script> world";
    const { container } = render(<SafeMarkdown content={xss} />);
    expect(container.innerHTML).not.toContain("<script>");
    expect(container.textContent).toContain("Hello");
    expect(container.textContent).toContain("world");
  });

  // The old hand-rolled regex stripper (removed) let nested payloads
  // through: "<scr<script>ipt>" came out as "<script>". Safety is
  // structural — no rehype-raw — so every raw tag stays inert text.
  it("keeps nested multi-character payloads inert", () => {
    const { container } = render(
      <SafeMarkdown content={"x <scr<script>ipt>alert(1)</scr" + "ipt> y"} />,
    );
    expect(container.querySelectorAll("script")).toHaveLength(0);
    expect(container.querySelectorAll("iframe")).toHaveLength(0);
    expect(container.innerHTML).not.toContain("<script");
    expect(container.textContent).toContain("alert(1)");
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
