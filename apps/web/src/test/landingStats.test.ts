/**
 * The landing page must not state a coverage range the product cannot back
 * (CONTENT-001).
 *
 * Three claims about which classes are covered existed in the repo and none
 * of them agreed: the meta description said 1-12, the Bengali landing stat
 * said 1-12, and the English landing stat said 6-10. The shipped, bundled
 * corpus (`apps/api/src/bangla_gpt_api/data/sample_nctb/`) is classes 6-10,
 * and the teacher classroom selectors cap at 10.
 *
 * These assertions only check internal consistency between the surfaces the
 * user sees. The authoritative source of truth is the corpus directory, and
 * the API test suite verifies the app serves exactly what is bundled.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { getLang, setLang, t } from "../i18n";

const WEB_ROOT = process.cwd();
const API_CORPUS = join(
  WEB_ROOT,
  "..",
  "api",
  "src",
  "bangla_gpt_api",
  "data",
  "sample_nctb",
);

function bundledClasses(): number[] {
  const levels = readdirSync(API_CORPUS)
    .filter((f) => f.endsWith(".md"))
    .map((f) => Number(/^class(\d+)_/.exec(f)?.[1]))
    .filter((n) => Number.isFinite(n));
  return [...new Set(levels)].sort((a, b) => a - b);
}

/**
 * "৬–১০" and "6–10" both parse to [6, 10].
 *
 * NFKC is not enough here: it folds Arabic-Indic and Devanagari digits to
 * ASCII, but Bengali-Indic (U+09E6..U+09EF) has no compatibility
 * decomposition and survives unchanged.
 */
function toAsciiDigits(s: string): string {
  return [...s]
    .map((c) => {
      const cp = c.codePointAt(0) ?? 0;
      return cp >= 0x09e6 && cp <= 0x09ef ? String(cp - 0x09e6) : c;
    })
    .join("");
}

function parseRange(label: string): [number, number] {
  const normalised = toAsciiDigits(label.normalize("NFC")).replace(
    /\u2013/g,
    "-",
  );
  const m = /(\d+)\s*-\s*(\d+)/.exec(normalised);
  expect(m, `no class range found in ${JSON.stringify(label)}`).toBeTruthy();
  return [Number(m?.[1]), Number(m?.[2])];
}

/** Read the landing stat exactly as the page renders it. */
function statIn(lang: "bn" | "en"): string {
  setLang(lang);
  return t("statClassesValue");
}

describe("landing page coverage claim", () => {
  const original = getLang();
  afterEach(() => setLang(original));

  it("the bundled corpus spans classes 6-10", () => {
    expect(bundledClasses()).toEqual([6, 7, 8, 9, 10]);
  });

  it("both languages state the same range", () => {
    expect(parseRange(statIn("bn"))).toEqual(parseRange(statIn("en")));
  });

  it("the stated range matches the bundled corpus", () => {
    const actual = bundledClasses();
    const [lo, hi] = parseRange(statIn("en"));
    expect(lo).toBe(actual[0]);
    expect(hi).toBe(actual[actual.length - 1]);
  });

  it("the meta description agrees with the landing stat", () => {
    const html = readFileSync(join(WEB_ROOT, "index.html"), "utf8");
    const description =
      /name="description"[\s\S]*?content="([^"]+)"/.exec(html)?.[1] ?? "";
    const actual = bundledClasses();
    const [lo, hi] = parseRange(description);
    expect(lo).toBe(actual[0]);
    expect(hi).toBe(actual[actual.length - 1]);
  });
});
