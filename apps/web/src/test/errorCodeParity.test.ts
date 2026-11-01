import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { friendlyError } from "../errors";
import { t } from "../i18n";

// F-111: the error table must name every detail code the API can emit. The
// reverse direction (each named key exists in the dictionary) is enforced by
// scripts/check_i18n.py; this side reads the API sources so a new endpoint
// cannot silently fall through to the generic sentence unnoticed.
const API_ROOT = resolve(
  process.cwd(),
  "..",
  "..",
  "apps",
  "api",
  "src",
  "bangla_gpt_api",
);
const ERRORS_TS = resolve(process.cwd(), "src", "errors.ts");

function pythonFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return pythonFiles(path);
    return entry.name.endsWith(".py") ? [path] : [];
  });
}

/** Every `"code": "..."` / `code="..."` literal the API can put in a body. */
function emittedCodes(): Map<string, string> {
  const patterns = [
    /"code"\s*:\s*"([a-z][a-z0-9_]*)"/g,
    /(?:^|[^A-Za-z0-9_])code\s*=\s*"([a-z][a-z0-9_]*)"/g,
  ];
  const out = new Map<string, string>();
  for (const file of pythonFiles(API_ROOT)) {
    const text = readFileSync(file, "utf8");
    for (const pattern of patterns) {
      for (const match of text.matchAll(pattern)) {
        if (!out.has(match[1])) {
          out.set(match[1], file.slice(API_ROOT.length + 1));
        }
      }
    }
  }
  return out;
}

/** The codes the web error table names. */
function mappedCodes(): Set<string> {
  const source = readFileSync(ERRORS_TS, "utf8");
  const block = source.slice(
    source.indexOf("const KEY"),
    source.indexOf("const ACTION"),
  );
  return new Set(
    [...block.matchAll(/^\s{2}([a-z][a-z0-9_]*):\s*"/gm)].map(
      (match) => match[1],
    ),
  );
}

describe("API detail codes vs the web error table (F-111)", () => {
  it("finds a plausible code population and fails on an unmapped one", () => {
    const emitted = emittedCodes();
    const mapped = mappedCodes();
    // Sanity floor: the extraction itself regressing (a renamed text pattern)
    // must fail loudly instead of reporting an empty set as success.
    expect(emitted.size).toBeGreaterThan(80);
    const missing = [...emitted]
      .filter(([code]) => !mapped.has(code))
      .map(([code, file]) => `${code} (${file})`);
    expect(
      missing,
      `API detail codes with no errors.ts KEY entry:\n${missing.join("\n")}`,
    ).toEqual([]);
  });

  it("routes the audit's quiz-start failure to localized copy, not raw English", () => {
    // F-110: the API answers quiz-start with index_unavailable and an English
    // detail.message; the screen must show the retry sentence instead.
    const copy = friendlyError({
      detail: {
        code: "index_unavailable",
        message: "Curriculum index unavailable",
      },
    });
    expect(copy.text).toBe(t("errLlmUnavailable"));
    expect(copy.text).not.toContain("Curriculum");

    // A representative user-actionable code and the not-found family.
    expect(friendlyError({ detail: { code: "chapter_not_found" } }).text).toBe(
      t("errChapterNotFound"),
    );
    expect(
      friendlyError({ detail: { code: "unsafe_content", message: "blocked" } })
        .text,
    ).toBe(t("errUnsafeContent"));
  });
});
