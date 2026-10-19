/**
 * G-20: ICU-style plurals and missing-key detection.
 *
 * Two defects the audit named:
 *
 *  * plurals were handled by choosing between two hand-written keys at the
 *    call site (`d.questions === 1 ? "activityQuestion" : "activityQuestions"`),
 *    i.e. grammar in a component, unverifiable and wrong for any language
 *    whose plural rules are not "1 vs rest";
 *  * `t()` returned the key silently when it was absent, so a mistyped key
 *    shipped as the literal text `streakLabel` on a child's screen.
 *
 * The third test here is the one a dictionary file cannot give you: it scans
 * every `t("...")` call site in the source tree and requires the key to exist
 * in both dictionaries, which is what "missing-key detection" has to mean to
 * be worth anything.
 */
import { afterEach, describe, expect, it } from "vitest";
import {
  clearMissingTranslationKeys,
  formatMessage,
  missingTranslationKeys,
  setLang,
  t,
} from "../i18n";

afterEach(() => {
  setLang("bn");
  clearMissingTranslationKeys();
});

describe("plural messages (G-20)", () => {
  it("selects the arm Intl.PluralRules selects, in both languages", () => {
    setLang("en");
    expect(t("activityQuestions", { n: 0 })).toBe("No questions");
    expect(t("activityQuestions", { n: 1 })).toBe("1 question");
    expect(t("activityQuestions", { n: 6 })).toBe("6 questions");

    setLang("bn");
    expect(t("activityQuestions", { n: 0 })).toBe("কোনো প্রশ্ন নেই");
    // `#` is formatted in the reader's own digits.
    expect(t("activityQuestions", { n: 6 })).toBe("৬টি প্রশ্ন");
  });

  it("prefers an exact `=N` arm over the category arms", () => {
    const message = "{n, plural, =0 {none} one {one} other {#}}";
    expect(formatMessage(message, { n: 0 }, "en")).toBe("none");
    expect(formatMessage(message, { n: 1 }, "en")).toBe("one");
    expect(formatMessage(message, { n: 2 }, "en")).toBe("2");
  });

  it("still substitutes plain placeholders in the same message", () => {
    const message =
      "{name} has {n, plural, one {# question} other {# questions}}";
    expect(formatMessage(message, { name: "রাফি", n: 3 }, "bn")).toBe(
      "রাফি has ৩ questions",
    );
  });

  it("leaves a string that is not a plural message untouched", () => {
    // A literal `{` in copy must not be eaten by the formatter.
    expect(formatMessage("set {a} and {b}", { a: 1, b: 2 }, "en")).toBe(
      "set 1 and 2",
    );
    expect(
      formatMessage("{n, plural, other {x}}", { n: "not-a-number" }, "en"),
    ).toBe("{n, plural, other {x}}".replace("{n}", "not-a-number"));
  });
});

describe("missing-key detection (G-20)", () => {
  it("records the key and returns it instead of crashing", () => {
    const missing = t("definitelyNotAKey" as never);
    expect(missing).toBe("definitelyNotAKey");
    expect(missingTranslationKeys()).toEqual(["definitelyNotAKey"]);
  });

  it("records each key once, and clears on request", () => {
    t("nope1" as never);
    t("nope1" as never);
    t("nope2" as never);
    expect(missingTranslationKeys().sort()).toEqual(["nope1", "nope2"]);
    clearMissingTranslationKeys();
    expect(missingTranslationKeys()).toEqual([]);
  });
});

/**
 * Every literal key a `t("...")` call site asks for, across the source tree.
 *
 * The sources are pulled in through Vite's `?raw` glob rather than read with
 * `node:fs`: the earlier `readdirSync`/`readFileSync` walk tripped CodeQL's
 * dynamic-filesystem queries (a new high-severity alert on a test file with no
 * untrusted input -- noise that would have hidden a real one), and the glob is
 * both simpler and resolved at build time, so the scan cannot wander outside
 * `src/`.
 */
const SOURCES: Record<string, string> = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  eager: true,
  import: "default",
});

function literalTranslationKeys(): Map<string, string> {
  const keys = new Map<string, string>();
  for (const [path, source] of Object.entries(SOURCES)) {
    // Tests may legitimately poke at the detection path with fake keys.
    if (path.includes("/test/")) continue;
    for (const match of source.matchAll(/\bt\(\s*"([A-Za-z0-9_]+)"/g)) {
      keys.set(match[1], path);
    }
    for (const match of source.matchAll(/\bt\(\s*'([A-Za-z0-9_]+)'/g)) {
      keys.set(match[1], path);
    }
  }
  return keys;
}

describe("every literal key used in the source exists (G-20)", () => {
  it("resolves in both dictionaries, and the scan really saw the codebase", () => {
    const keys = literalTranslationKeys();
    // A guard against a silently broken scan: the app asks for hundreds.
    expect(keys.size).toBeGreaterThan(200);

    const unknown: string[] = [];
    for (const lang of ["bn", "en"] as const) {
      setLang(lang);
      clearMissingTranslationKeys();
      for (const key of keys.keys()) t(key as never);
      for (const key of missingTranslationKeys()) {
        unknown.push(`${lang}: ${key} (used by ${keys.get(key) ?? "?"})`);
      }
    }
    expect(unknown).toEqual([]);
  });
});
