/**
 * F-149/F-200 (SLOP-B4, UX-12): the icon language is lucide-react, sized and
 * aria-hidden. Two classes of glyph broke it and both shipped: vendor emoji
 * (the robot on AnalyticsPage rendered differently on Samsung and Tecno
 * handsets, which is a different picture per device) and text dingbats in
 * button labels (a bare arrow ahead of the label reads as an icon but is
 * announced as punctuation by a screen reader).
 *
 * The repo-wide slop scan (`.qa-work/tools/slop_scan.py`, B4) is a QA-side
 * script; this is the guard that runs with the product's own suite. Comments
 * are skipped -- an arrow between two words is punctuation -- and i18n.ts is
 * out of scope for the same reason: there the arrow is copy, not iconography.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const ROOTS = ["src/pages", "src/components"];

/** Emoji, dingbats and the arrow blocks that read as iconography in the UI. */
const GLYPH =
  /[\u2190-\u21FF\u2300-\u23FF\u2460-\u24FF\u25A0-\u27BF\u2B00-\u2BFF\uFE0F\u{1F000}-\u{1FAFF}]/u;

/** Comment shapes that legitimately contain an arrow or a tick. */
const COMMENT_LINE = /^\s*(\/\/|\/\*|\*|\{\/\*|<!--)/;
const INLINE_JSX_COMMENT = /\{\/\*[\s\S]*?\*\/\}/g;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (!/\.(ts|tsx)$/.test(entry.name)) return [];
    if (/\.(test|spec)\.(ts|tsx)$/.test(entry.name)) return [];
    return [path];
  });
}

describe("UI iconography (F-149/F-200)", () => {
  it("no emoji or dingbat glyphs in the UI source outside comments", () => {
    const hits: string[] = [];
    for (const root of ROOTS) {
      for (const file of sourceFiles(root)) {
        readFileSync(file, "utf8")
          .split("\n")
          .forEach((line, index) => {
            if (COMMENT_LINE.test(line)) return;
            const code = line.replace(INLINE_JSX_COMMENT, "");
            if (GLYPH.test(code)) {
              hits.push(`${relative(process.cwd(), file)}:${index + 1}: ${line.trim()}`);
            }
          });
      }
    }
    expect(hits, `glyph iconography:\n${hits.join("\n")}`).toEqual([]);
  });
});
