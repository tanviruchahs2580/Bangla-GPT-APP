/** AUD-G-02: bypass-blocks link (WCAG 2.4.1) on every route.
 *
 * Two guards: the component itself, and a source scan that keeps every page's
 * `<main>` as a valid skip target as the page set grows.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MAIN_CONTENT_ID, SkipLink } from "../components/SkipLink";

function pageFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return pageFiles(path);
    return path.endsWith(".tsx") ? [path] : [];
  });
}

describe("skip link", () => {
  it("is a link to the main landmark", () => {
    render(<SkipLink />);
    const link = screen.getByRole("link", { name: "মূল কনটেন্টে যান" });
    expect(link).toHaveAttribute("href", `#${MAIN_CONTENT_ID}`);
  });

  it("every page renders a <main> that the link can target", () => {
    const root = join(__dirname, "..", "pages");
    const offenders: string[] = [];
    for (const file of pageFiles(root)) {
      const source = readFileSync(file, "utf8");
      const mains = source.match(/<main\b[^>]*>/g) ?? [];
      for (const tag of mains) {
        if (!tag.includes(`id="${MAIN_CONTENT_ID}"`)) {
          offenders.push(`${file}: ${tag}`);
        }
      }
      // A page with no <main> at all would fail the landmark rule instead.
      expect(mains.length).toBeGreaterThan(0);
    }
    expect(offenders).toEqual([]);
  });
});
