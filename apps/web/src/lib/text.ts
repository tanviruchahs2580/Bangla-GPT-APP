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
