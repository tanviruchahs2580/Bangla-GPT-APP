import { t } from "../i18n";

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
