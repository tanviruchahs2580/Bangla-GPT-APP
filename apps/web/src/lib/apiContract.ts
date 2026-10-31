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
  /**
   * Every distinct type argument the call sites for this route pass
   * (`undefined` when all sites are untyped). A route can be reached from
   * several files with different shapes, and each shape is part of the
   * F-157 contract, so none of them may be silently dropped by dedupe.
   */
  typeArgs?: string[];
}

export interface OpenApiSchema {
  paths?: Record<string, Record<string, unknown>>;
  components?: { schemas?: Record<string, unknown> };
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
 * skipped every `del(...)`, so deletes were never contract-checked. The type
 * group tolerates one level of angle-bracket nesting (`Record<string, T>`):
 * a flat `<[^>]*>` stopped at the first `>` and the `(` then failed to match,
 * so nested-generic calls (the data export, the admin purge) were invisible
 * to the contract check.
 */
const CALL_RE =
  /\b(get|post|patch|del|postStream)(?:<((?:[^<>]|<(?:[^<>]|<[^<>]*>)*>)+)>)?\(\s*([`"][^`"]*)/g;

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
    const path = normalizePath(match[3].slice(1));
    if (!path || !path.startsWith("/")) continue;
    const key = `${method} ${path}`;
    const typeArg = match[2]?.trim();
    const existing = calls.get(key);
    if (existing) {
      if (typeArg && !existing.typeArgs?.includes(typeArg)) {
        existing.typeArgs = [...(existing.typeArgs ?? []), typeArg];
      }
      continue;
    }
    calls.set(key, {
      method,
      path,
      ...(typeArg ? { typeArgs: [typeArg] } : {}),
    });
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

/* ------------------------------------------------------------------------ */
/* F-157: the response half of the contract (schema component vs TS type).   */
/*                                                                          */
/* The extractor above proves the *routes* line up; these helpers let the   */
/* test prove the *payload types* line up: every 2xx JSON response the API  */
/* declares as a named component must be mirrored by the TS type the client */
/* hands the same call.                                                     */
/* ------------------------------------------------------------------------ */

/** What the API declares as a 2xx `application/json` body for one operation. */
export type JsonResponse =
  | { kind: "none" }
  /** A free-form object (`additionalProperties`, no named properties): an
   * index-signature type or an untyped call is the correct client shape. */
  | { kind: "free-form" }
  | {
      kind: "ref";
      /** Component name the `$ref` points at ("" for an inline object schema). */
      component: string;
      /** True when the response is an array of that component. */
      array: boolean;
      /** The body's declared properties (the names are the contract). */
      properties: Record<string, unknown>;
      /** The body's required property names. */
      required: string[];
    };

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Follow one `$ref` into the document's components; null when not a ref. */
function derefRef(schema: unknown, doc: OpenApiSchema): string | null {
  if (!isRecord(schema) || typeof schema["$ref"] !== "string") return null;
  const name = schema["$ref"].split("/").pop();
  if (!name || !doc.components?.schemas?.[name]) return null;
  return name;
}

/** One schema body's shape, dereferenced far enough to compare names. */
function componentShape(
  schema: unknown,
  doc: OpenApiSchema,
): JsonResponse | null {
  if (!isRecord(schema)) return null;
  const ref = derefRef(schema, doc);
  if (ref) return shapeFor(ref, doc);
  // `anyOf: [T, null]` is pydantic's Optional: unwrap the null branch.
  if (Array.isArray(schema["anyOf"])) {
    const nonNull = (schema["anyOf"] as unknown[]).find(
      (branch) => !(isRecord(branch) && branch["type"] === "null"),
    );
    return nonNull === undefined ? null : componentShape(nonNull, doc);
  }
  if (schema["type"] === "array") {
    const item = componentShape(schema["items"], doc);
    return item && item.kind === "ref" ? { ...item, array: true } : null;
  }
  if (schema["type"] === "object") {
    const properties = schema["properties"];
    if (!isRecord(properties) || Object.keys(properties).length === 0) {
      return { kind: "free-form" };
    }
    return {
      kind: "ref",
      component: "",
      array: false,
      properties,
      required: Array.isArray(schema["required"])
        ? (schema["required"] as string[])
        : [],
    };
  }
  return null;
}

function shapeFor(
  componentName: string,
  doc: OpenApiSchema,
): JsonResponse | null {
  const schema = doc.components?.schemas?.[componentName];
  if (!isRecord(schema)) return null;
  const properties = isRecord(schema["properties"]) ? schema["properties"] : {};
  return {
    kind: "ref",
    component: componentName,
    array: false,
    properties,
    required: Array.isArray(schema["required"])
      ? (schema["required"] as string[])
      : [],
  };
}

/**
 * Resolve the declared JSON body of `method path` against an OpenAPI
 * document. Paths are canonicalized to `{param}` on both sides, exactly like
 * `openApiOperations` does. 2xx statuses are tried in numeric order; a
 * non-JSON media type, an empty schema (the SSE endpoints) or a scalar body
 * resolve to `none` — no named component, nothing for the client to mirror.
 */
export function resolveJsonResponse(
  doc: OpenApiSchema,
  method: string,
  path: string,
): JsonResponse {
  const operations = doc.paths ?? {};
  for (const [schemaPath, methods] of Object.entries(operations)) {
    if (canonical(schemaPath) !== path) continue;
    const operation = isRecord(methods) ? methods[method] : undefined;
    if (!isRecord(operation)) continue;
    const responses = operation.responses;
    if (!isRecord(responses)) continue;
    const statuses = Object.keys(responses)
      .filter((status) => /^2/.test(status))
      .sort();
    for (const status of statuses) {
      const response = responses[status];
      if (!isRecord(response)) continue;
      const content = response.content;
      if (!isRecord(content)) continue;
      const media = content["application/json"];
      if (!isRecord(media)) continue;
      const shape = componentShape(media.schema, doc);
      if (shape) return shape;
    }
    break;
  }
  return { kind: "none" };
}

/** One parsed TS property: its name and whether it is optional (`?:`). */
export interface TsProperty {
  name: string;
  optional: boolean;
}

/** A parsed TS `interface`/`type` object declaration. */
export interface TsDeclaration {
  name: string;
  extends?: string;
  properties: TsProperty[];
}

const PROPERTY_RE = /^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)(\?)?\s*:/;

/**
 * Parse `interface X … {…}` and `type X = {…}` declarations out of TS source.
 * Property bodies are scanned line-wise at brace depth 0, so a nested object
 * literal on a property (`difficulty: { easy: number; … }`) contributes its
 * braces to the depth but not phantom properties.
 */
export function parseTypeDeclarations(
  source: string,
): Map<string, TsDeclaration[]> {
  const out = new Map<string, TsDeclaration[]>();
  const push = (decl: TsDeclaration) => {
    const list = out.get(decl.name) ?? [];
    list.push(decl);
    out.set(decl.name, list);
  };
  const header =
    /(?:\binterface\s+([A-Za-z0-9_]+)(?:\s+extends\s+([A-Za-z0-9_.]+))?|\btype\s+([A-Za-z0-9_]+)\s*=\s*)\s*\{/g;
  for (const match of source.matchAll(header)) {
    const name = match[1] ?? match[3];
    if (!name) continue;
    const bodyStart = match.index + match[0].length;
    const body = balancedBraces(source, bodyStart - 1);
    if (body === null) continue;
    push({
      name,
      extends: match[2],
      properties: parsePropertyLines(body),
    });
  }
  return out;
}

/** The balanced `{…}` block starting at `openBrace`, or null when unbalanced. */
function balancedBraces(source: string, openBrace: number): string | null {
  let depth = 0;
  for (let i = openBrace; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(openBrace + 1, i);
    }
  }
  return null;
}

function parsePropertyLines(body: string): TsProperty[] {
  const properties: TsProperty[] = [];
  let depth = 0;
  for (const line of body.split("\n")) {
    if (depth === 0) {
      const match = PROPERTY_RE.exec(line);
      // The optional marker must sit right after the name: a nested object
      // literal on the same line (`plan: { weeks?: … }`) contains `?:` too.
      if (match)
        properties.push({ name: match[1], optional: match[2] === "?" });
    }
    for (const ch of line) {
      if (ch === "{" || ch === "(") depth += 1;
      if (ch === "}" || ch === ")") depth -= 1;
    }
    if (depth < 0) depth = 0;
  }
  return properties;
}

/**
 * The TS side of one client type argument: unwrapped (null unions stripped,
 * `import("./types").` prefix removed, array suffix detected) and either an
 * inline object literal's properties or the named declaration to look up.
 */
export interface ResolvedTypeArg {
  array: boolean;
  /** `Record<...>` — an index signature, the right shape for free-form maps. */
  indexSignature: boolean;
  /** Inline object literal (`{ id: number }`): properties parsed directly. */
  inline?: TsProperty[];
  /** Named type to resolve against the parsed declarations (no array suffix). */
  name?: string;
}

export function resolveTypeArg(raw: string): ResolvedTypeArg | null {
  let arg = raw
    .replaceAll("import('./types').", "")
    .replaceAll('import("./types").', "")
    .trim();
  arg = arg
    .split("|")
    .map((part) => part.trim())
    .filter((part) => part !== "null" && part !== "undefined")
    .join(" | ");
  if (arg.startsWith("Record<")) return { array: false, indexSignature: true };
  let array = false;
  if (arg.endsWith("[]")) {
    array = true;
    arg = arg.slice(0, -2).trim();
  }
  if (arg.startsWith("{")) {
    const open = arg.indexOf("{");
    const body = balancedBraces(arg, open);
    return {
      array,
      indexSignature: false,
      inline: body === null ? [] : parsePropertyLines(body),
    };
  }
  if (!/^[A-Za-z0-9_]+$/.test(arg)) return null;
  return { array, indexSignature: false, name: arg };
}

/**
 * Compare one schema body against one TS declaration. Returns the problems
 * found (empty when the client type mirrors the schema):
 *  - every schema property must be declared on the TS side (a schema field
 *    the client never sees is exactly the drift this contract exists for);
 *  - every TS property must exist in the schema (a renamed server field
 *    would otherwise read `undefined` at runtime with no type error);
 *  - a schema-required property must not be optional on the TS side.
 */
export function typeMismatches(
  body: { properties: Record<string, unknown>; required: string[] },
  tsProperties: TsProperty[],
  label: { call: string; tsType: string; component: string },
): string[] {
  const byName = new Map(tsProperties.map((p) => [p.name, p]));
  const problems: string[] = [];
  for (const name of Object.keys(body.properties)) {
    const tsProperty = byName.get(name);
    if (!tsProperty) {
      problems.push(
        `${label.tsType} is missing schema property \`${name}\` (${label.call})`,
      );
      continue;
    }
    if (body.required.includes(name) && tsProperty.optional) {
      problems.push(
        `schema property \`${name}\` is required but ${label.tsType} declares it optional (${label.call})`,
      );
    }
  }
  for (const tsProperty of tsProperties) {
    if (!(tsProperty.name in body.properties)) {
      problems.push(
        `${label.tsType} declares property \`${tsProperty.name}\` the schema component ` +
          `${label.component || "response"} does not have (${label.call})`,
      );
    }
  }
  return problems;
}

/** Flatten `interface X extends Y` so the parent's fields count as present. */
export function flattenDeclaration(
  declaration: TsDeclaration,
  declarations: Map<string, TsDeclaration[]>,
): TsProperty[] {
  if (!declaration.extends) return declaration.properties;
  const [parent] = declarations.get(declaration.extends) ?? [];
  return parent
    ? [...flattenDeclaration(parent, declarations), ...declaration.properties]
    : declaration.properties;
}
