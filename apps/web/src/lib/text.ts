import { t } from "../i18n";

/**
 * Truncate `text` to at most `limit` code points, never cutting inside a
 * grapheme cluster.
 *
 * `String.prototype.slice` counts UTF-16 code units, so `"ক্ষম".slice(0, 2)`
 * returns `"ক্"` — a consonant followed by a dangling virama, which renders as
 * a broken conjunct and reads as a typo (AUD-G-04). Bengali builds aksharas
 * from base letters, the virama U+09CD and dependent vowel signs, so the cut
 * has to land on a cluster boundary (UAX #29).
 *
 * The budget stays in code points because that is the unit the API counts:
 * `subject_focus` is validated with Python's `len()` as 1-60 characters
 * (`routers/parent.py`), and one cluster is several code points — a 60-cluster
 * result can be three times the accepted length. `Intl.Segmenter` with
 * `granularity: "grapheme"` does the splitting; runtimes without it (older
 * Safari, some WebViews) fall back to code points, which at least never splits
 * a surrogate pair.
 */
export function truncateGraphemes(text: string, limit: number): string {
  if (limit <= 0) return "";
  let out = "";
  let used = 0;
  for (const cluster of graphemeClusters(text)) {
    const size = Array.from(cluster).length;
    if (used + size > limit) break;
    out += cluster;
    used += size;
  }
  return out;
}

/** Grapheme clusters via `Intl.Segmenter`, or code points without it. */
function graphemeClusters(text: string): string[] {
  if (typeof Intl.Segmenter === "function") {
    const segmenter = new Intl.Segmenter(undefined, {
      granularity: "grapheme",
    });
    return Array.from(segmenter.segment(text), (part) => part.segment);
  }
  return Array.from(text);
}

/**
 * Coerce an unknown value into text that is safe to show a user.
 *
 * `String({})` produces "[object Object]", so anything that is not already a
 * string is serialised instead. Lives here rather than in `api.ts` so that
 * rendering helpers do not depend on the network module (which tests mock
 * wholesale).
 */
export function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  try {
    return JSON.stringify(value) ?? "[unserialisable value]";
  } catch {
    return "[unserialisable value]";
  }
}

/**
 * Render the API's suggestion code + parameters as a localised sentence.
 *
 * The report endpoints return a code and its parameters rather than prose (see
 * `_window_report` in the API), so the sentence is composed here. A caller that
 * drops the parameters leaves placeholders such as `{chapters}` on screen.
 *
 * The report is typed structurally on purpose: `api.ts` imports `asText` from
 * this module, so importing its types back would create an import cycle.
 */
export function suggestionSentence(report: {
  suggestion_code: string;
  suggestion_params?: Record<string, unknown> | null;
}): string {
  const key = report.suggestion_code as Parameters<typeof t>[0];
  const vars: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(report.suggestion_params ?? {})) {
    vars[k] = Array.isArray(v) ? v.map(asText).join(", ") : asText(v);
  }
  try {
    const text = t(key, vars);
    if (text && text !== report.suggestion_code) return text;
  } catch {
    // unknown code falls through to the raw code below
  }
  return report.suggestion_code;
}

/**
 * Bangla-aware string comparison (AUD-G-23).
 *
 * `Array.prototype.sort`'s default order compares UTF-16 code units, which puts
 * Bengali letters in code-point order rather than the order a Bangla reader
 * expects (vowel signs and the reph are not letters at all, so "ক" then "কি"
 * only sorts correctly once the collator looks at them). `Intl.Collator("bn")`
 * implements the CLDR Bengali collation; runtimes without a Bengali collation
 * fall back to a locale-aware comparison and finally to code units, never to a
 * crash.
 */
let bnCollator: Intl.Collator | null | undefined;

function collator(): Intl.Collator | null {
  if (bnCollator === undefined) {
    try {
      bnCollator =
        typeof Intl.Collator === "function" ? new Intl.Collator("bn") : null;
    } catch {
      bnCollator = null;
    }
  }
  return bnCollator;
}

export function compareBn(a: string, b: string): number {
  const collatorInstance = collator();
  if (!collatorInstance) return a < b ? -1 : a > b ? 1 : 0;
  try {
    return collatorInstance.compare(a, b);
  } catch {
    return a < b ? -1 : a > b ? 1 : 0;
  }
}
