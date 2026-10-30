/**
 * FE-05: the client/API contract check.
 *
 * The web app's types and paths are hand-written while the API ships a live
 * OpenAPI document; a renamed route or a dropped method fails at render time
 * in production instead of at review. Without adding a dependency (the
 * register's `openapi-typescript` suggestion would), this module extracts
 * every call the client makes and answers one question against the served
 * schema: does this path exist with this method?
 *
 * Two consumers: `src/test/apiContract.test.ts` pins the extractor's
 * behaviour, and the e2e suite fetches the *served* `/openapi.json` and
 * compares it with the real sources in this build.
 */

export interface ClientCall {
  method: string;
  path: string;
}

export interface OpenApiSchema {
  paths?: Record<string, Record<string, unknown>>;
}

/** HTTP verbs `src/api.ts` expresses through the `get`/`post`/... helpers. */
const METHOD_BY_HELPER: Record<string, string> = {
  get: "get",
  post: "post",
  patch: "patch",
  del: "delete",
  postStream: "post",
};

/**
 * `del` is never called with a type parameter in this codebase, and the other
 * helpers sometimes are not either — a regex that required `<…>` silently
 * skipped every `del(...)`, so deletes were never contract-checked.
 */
const CALL_RE =
  /\b(get|post|patch|del|postStream)(?:<[^>]*>)?\(\s*([`"][^`"]*)/g;

/**
 * Reduce one captured path literal to an OpenAPI path template:
 *  * `${...}` directly after a `/` is a path parameter -> `{param}`;
 *  * `${...}` directly after any other character starts the query string or
 *    an optional tail -> nothing after it belongs to the path;
 *  * everything from the first `?` on is dropped.
 *
 * A nested template literal inside a slot truncates the capture; that is the
 * query-string shape in `src/api.ts`, so treating the truncated slot as a tail
 * yields the correct route prefix.
 */
function normalizePath(raw: string): string | null {
  let out = "";
  for (let i = 0; i < raw.length; i += 1) {
    const ch = raw[i];
    if (ch === "`" || ch === '"' || ch === "?") break;
    if (ch === "$" && raw[i + 1] === "{") {
      const end = raw.indexOf("}", i);
      if (out.endsWith("/") && end > -1) {
        out += "{param}";
        i = end;
        continue;
      }
      // Query string or nested template: the path ends here.
      break;
    }
    out += ch;
  }
  return out || null;
}

/**
 * Extract `{method, path}` pairs from an `api.ts`-shaped source string.
 * Query strings and non-route literals are dropped; the result is sorted and
 * de-duplicated so the caller can compare it with the schema as a set.
 */
export function extractClientCalls(source: string): ClientCall[] {
  const calls = new Map<string, ClientCall>();
  for (const match of source.matchAll(CALL_RE)) {
    const method = METHOD_BY_HELPER[match[1]];
    const path = normalizePath(match[2].slice(1));
    if (!path || !path.startsWith("/")) continue;
    calls.set(`${method} ${path}`, { method, path });
  }
  return [...calls.values()].sort((a, b) =>
    `${a.method} ${a.path}`.localeCompare(`${b.method} ${b.path}`),
  );
}

/**
 * Schema placeholders carry names (`{subject}`, `{item_id}`) while the client
 * extractor emits `{param}`; both are canonicalized here. Segment structure
 * survives, so a renamed segment still fails the comparison.
 */
const canonical = (path: string): string =>
  path.replace(/\{[^}]*\}/g, "{param}");

/** `{path: {get: ..., post: ...}}` -> Set of `"method path"` keys. */
export function openApiOperations(schema: OpenApiSchema): Set<string> {
  const out = new Set<string>();
  for (const [path, operations] of Object.entries(schema?.paths ?? {})) {
    for (const method of Object.keys(operations ?? {})) {
      if (["get", "post", "put", "patch", "delete"].includes(method)) {
        out.add(`${method} ${canonical(path)}`);
      }
    }
  }
  return out;
}

/**
 * Every extracted call that the schema does not declare. Path templates are
 * compared shape-for-shape (`{param}` on both sides), so a renamed segment
 * fails as loudly as a removed route.
 */
export function missingFromSchema(
  calls: ClientCall[],
  schema: OpenApiSchema,
): string[] {
  const operations = openApiOperations(schema);
  return calls
    .map(({ method, path }) => `${method} ${path}`)
    .filter((key) => !operations.has(key));
}
