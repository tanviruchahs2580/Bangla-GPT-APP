/**
 * FE-05: the client/OpenAPI contract module's own contract.
 *
 * The live comparison runs in the e2e suite (it needs the served
 * `/openapi.json`); these cases pin the extractor so a regex that silently
 * stops matching cannot make the live check vacuous. The fixture strings
 * mirror the shapes that actually occur in `src/api.ts` and the pages.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  extractClientCalls,
  missingFromSchema,
  openApiOperations,
} from "../lib/apiContract";

function clientSourceText(): string {
  const files: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!["node_modules", "test"].includes(entry.name)) walk(path);
      } else if (/\.(ts|tsx)$/.test(entry.name)) {
        files.push(path);
      }
    }
  };
  walk(join(process.cwd(), "src"));
  return files.map((file) => readFileSync(file, "utf8")).join("\n");
}

describe("normalizePath", () => {
  it("turns path parameters into {param} and drops query strings", () => {
    const calls = extractClientCalls(`
      get<A>(\`/learn/subjects/\${encodeURIComponent(subject)}/chapters\`);
      get<B>(\`/learn/progress?\${qs}\`);
      get<C>(\`/learn/subjects\${classLevel ? \`?class_level=\${classLevel}\` : ""}\`);
      get<D>("/users/me");
    `);
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "get /learn/progress",
      "get /learn/subjects",
      "get /learn/subjects/{param}/chapters",
      "get /users/me",
    ]);
  });

  it("maps the helper verbs the client uses", () => {
    const calls = extractClientCalls(`
      post<A>("/quizzes/1/submit", {});
      patch<B>("/notes/2", {});
      del("/notes/2");
      postStream<C>("/tutor/conversations/1/messages/stream", {}, () => {}, {});
    `);
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "delete /notes/2",
      "patch /notes/2",
      "post /quizzes/1/submit",
      "post /tutor/conversations/1/messages/stream",
    ]);
  });

  it("ignores non-route and non-literal calls", () => {
    const calls = extractClientCalls(`
      localStorage.getItem("bgpt_token");
      const qs = new URLSearchParams();
      get<A>(somePath);
      post(helper());
    `);
    expect(calls).toEqual([]);
  });
});

describe("missingFromSchema", () => {
  const schema = {
    paths: {
      "/learn/subjects/{subject}/chapters": { get: {} },
      "/notes/{note_id}": { delete: {}, patch: {} },
    },
  };

  it("accepts calls whose path and method the schema declares", () => {
    const calls = extractClientCalls(`
      get<A>(\`/learn/subjects/\${s}/chapters\`);
      del(\`/notes/\${id}\`);
    `);
    expect(missingFromSchema(calls, schema)).toEqual([]);
  });

  it("flags a renamed segment and a wrong method", () => {
    const calls = extractClientCalls(`
      get<A>(\`/learn/subjects/\${s}/chapters\`);
      get<B>(\`/learn/topics/\${s}/chapters\`);
      post<C>(\`/notes/\${id}\`, {});
    `);
    expect(missingFromSchema(calls, schema)).toEqual([
      "get /learn/topics/{param}/chapters",
      "post /notes/{param}",
    ]);
  });

  it("canonicalizes placeholder names on both sides only", () => {
    const operations = openApiOperations(schema);
    expect(operations.has("get /learn/subjects/{param}/chapters")).toBe(true);
    expect(operations.has("get /learn/topics/{param}/chapters")).toBe(false);
  });
});

/**
 * F-157 residual: the extractor's own cases above run on fixtures, and the
 * live schema comparison needs servers (e2e). These cases run the extractor
 * over the shipped client sources, so regex rot or a client call that stops
 * being a plain literal fails here too -- next to the code that parses it.
 */
describe("the extractor against the shipped client", () => {
  const calls = extractClientCalls(clientSourceText());
  const keys = new Set(calls.map((c) => `${c.method} ${c.path}`));

  it("still finds the >60 calls the e2e floor claims", () => {
    expect(calls.length).toBeGreaterThan(60);
  });

  it("finds the release-critical calls", () => {
    for (const expected of [
      "post /auth/register",
      "post /auth/login",
      "get /users/me",
      "post /tutor/conversations/{param}/messages/stream",
      "post /quizzes/{param}/submit",
    ]) {
      expect(keys.has(expected), `missing ${expected}`).toBe(true);
    }
  });
});
