/**
 * QE-06: the release version is double-entered (apps/api/pyproject.toml and
 * apps/web/package.json) and the Android shell reads package.json too. A
 * drift ships an API image or an AAB labeled with the wrong version — one
 * trivial test pins them together so the next bump cannot split them.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("release version parity", () => {
  it("pyproject.toml and package.json agree", () => {
    // vitest runs with cwd = apps/web (jsdom import.meta.url is an http
    // URL, so file resolution goes through the process working directory).
    const pkg = JSON.parse(
      readFileSync(resolve(process.cwd(), "package.json"), "utf8"),
    ) as { version: string };
    const pyproject = readFileSync(
      resolve(process.cwd(), "../api/pyproject.toml"),
      "utf8",
    );
    const match = /^version\s*=\s*"([^"]+)"/m.exec(pyproject);
    expect(match, "pyproject.toml must declare a version").toBeTruthy();
    expect(pkg.version).toBe(match![1]);
  });
});
