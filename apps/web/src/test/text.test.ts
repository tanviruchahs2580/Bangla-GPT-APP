/**
 * AUD-G-04: `MePage` cut the subject-focus field with `slice(0, 60)`, which
 * counts UTF-16 code units. Bengali aksharas are multi-code-point ("ক্ষ" is
 * ক + ্ + ষ), so a limit that lands mid-cluster leaves a consonant with a
 * dangling virama — a visibly broken conjunct — and that is what got stored.
 */
import { describe, expect, it } from "vitest";
import { truncateGraphemes } from "../lib/text";

describe("truncateGraphemes", () => {
  it("keeps a Bangla conjunct intact instead of splitting it", () => {
    // The old code cut at two code units: one full code point and a bare
    // virama (U+09CD), i.e. a broken akshara.
    expect("ক্ষম".slice(0, 2)).toBe("ক্");
    // Budget 3 = exactly the cluster "ক্ষ" (ক + ্ + ষ); "ম" does not fit.
    expect(truncateGraphemes("ক্ষম", 3)).toBe("ক্ষ");
    expect(truncateGraphemes("ক্ষম", 4)).toBe("ক্ষম");
    // A budget that lands inside the cluster yields no partial cluster at all.
    expect(truncateGraphemes("ক্ষম", 2)).toBe("");
  });

  it("never returns a trailing virama at any limit", () => {
    const word = "ক্ষমতা ও বিজ্ঞান";
    for (let limit = 1; limit <= word.length; limit += 1) {
      expect(truncateGraphemes(word, limit).endsWith("\u09CD")).toBe(false);
    }
  });

  it("counts a dependent vowel sign as part of its cluster", () => {
    // "কি" = ক + ি (U+09BF); cutting between them drops the vowel sign.
    expect(truncateGraphemes("কি", 1)).toBe("");
    expect(truncateGraphemes("কি", 2)).toBe("কি");
    expect(truncateGraphemes("কিতাব", 4)).toBe("কিতা");
  });

  it("handles the edges: zero, empty and over-long limits", () => {
    expect(truncateGraphemes("বাংলা", 0)).toBe("");
    expect(truncateGraphemes("", 10)).toBe("");
    expect(truncateGraphemes("বাংলা", 99)).toBe("বাংলা");
  });

  it("keeps the API's 60-code-point budget, not 60 clusters", () => {
    // The server validates subject_focus with Python's len() (1-60 code
    // points); 40 copies of "ক্ষ" are 120 code points but 40 clusters.
    const word = "ক্ষ".repeat(40);
    expect(truncateGraphemes(word, 60)).toHaveLength(60);
    expect(Array.from(truncateGraphemes(word, 60)).length).toBe(60);
  });

  it("falls back to code points when Intl.Segmenter is unavailable", () => {
    const intl = Intl as unknown as { Segmenter?: unknown };
    const original = intl.Segmenter;
    intl.Segmenter = undefined;
    try {
      // A surrogate pair (😀) survives the fallback; a code-unit slice would
      // return half of it. Conjuncts degrade to code points, which is the
      // documented floor of the fallback.
      expect(truncateGraphemes("😀abc", 1)).toBe("😀");
      expect(truncateGraphemes("ক্ষম", 1)).toBe("ক");
    } finally {
      intl.Segmenter = original;
    }
  });
});
