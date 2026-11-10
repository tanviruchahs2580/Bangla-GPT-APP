#!/usr/bin/env node
/**
 * CI-FIX-002: `vitest run` can exit 0 while part of the suite never executed.
 *
 * Measured on this tree with vitest 4.1.12: the run printed
 * "Test Files 84 passed (84) ... Errors 13 errors" and exited 0 -- the files
 * whose workers failed to start were reported as errors, not as failures,
 * and did not reach the exit code. `npm test` therefore reported green while
 * ~14% of the suite had not run, which is worse than a slow gate: a check
 * that cannot fail is not a check.
 *
 * vitest 4.1.12 exposes `--dangerouslyIgnoreUnhandledErrors` (default off),
 * but the observed errors are not the ones that option controls -- the run
 * exited 0 with them off -- so this wrapper goes the robust route instead of
 * trusting a flag: run vitest once (default reporter for humans, plus the
 * json reporter for the machine), then compare the test files the run
 * actually recorded against the test files vitest discovers on disk. A
 * shortfall exits non-zero and names the files that never ran.
 *
 * Reproduced on 2026-11-10 on a loaded machine: 97 test files on disk, the
 * run's JSON report recorded 66 (57 passed + 9 failed) and reported
 * "31 errors" -- every one of them a `[vitest-pool]: Failed to start forks
 * worker` timeout. `discovered (97) != reported (66)` is exactly the signal
 * the old exit code did not carry.
 *
 * Discovery mirrors the `test.include`/`test.exclude` in vite.config.ts:
 * the vitest default glob (`**\/*.{test,spec}.?(c|m)[jt]s?(x)`, never
 * overridden there) scoped to `src/`, minus node_modules/e2e/dist. The only
 * `exclude` entry that matters under `src/` is `**\/node_modules/**`;
 * `e2e/` and `dist/` never hold test files under `src/`. Verified on
 * 2026-11-10 that the walk finds 97 files and `find src -name
 * '*.test.ts*'` agrees.
 *
 * Filtered runs (`npm test -- src/test/foo.test.tsx`) are forwarded but the
 * completeness cross-check is skipped with an explicit notice: a positional
 * filter (or `-t`/`--changed`/`--shard`) makes "discovered" intentionally
 * incomparable to "ran", and a gate that guesses would be another lie.
 *
 * Usage: node scripts/check_vitest_ran.mjs [any vitest run flags]
 */

import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

// The vitest include pattern (its default, not overridden by vite.config.ts).
const TEST_FILE_RE = /\.(?:test|spec)\.(?:c|m)?[jt]sx?$/;
// vite.config.ts `test.exclude`, as path segments relative to apps/web.
const EXCLUDED_SEGMENTS = new Set(["node_modules", "e2e", "dist"]);

/** Every test file vitest would collect under `dir` (default: src/). */
export function discoverTestFiles(dir = path.join(webRoot, "src"), out = []) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDED_SEGMENTS.has(entry.name)) continue;
      discoverTestFiles(full, out);
      continue;
    }
    if (entry.isFile() && TEST_FILE_RE.test(entry.name)) {
      out.push(path.relative(webRoot, full).split(path.sep).join("/"));
    }
  }
  return out;
}

function main() {
  const args = process.argv.slice(2);

  const vitestBin = path.join(
    path.dirname(createRequire(import.meta.url).resolve("vitest/package.json")),
    "vitest.mjs",
  );

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "vitest-ran-"));
  const reportFile = path.join(tmpDir, "vitest-run.json");

  const run = spawnSync(
    process.execPath,
    [
      vitestBin,
      "run",
      "--reporter=default",
      "--reporter=json",
      `--outputFile.json=${reportFile}`,
      ...args,
    ],
    { cwd: webRoot, stdio: "inherit", env: process.env },
  );

  const vitestExit = run.status ?? 1;
  const positional = args.filter((arg) => !arg.startsWith("-"));
  // Flags that select a subset of the collected suite for the same reason a
  // positional filter does: with any of them, "ran" is not comparable to
  // "discovered" and the cross-check must stand aside (loudly) rather than
  // invent a failure.
  const subsetFlags = ["-t", "--testNamePattern", "--changed", "--shard"];
  const subsetFilters = args.filter((arg) =>
    subsetFlags.some((flag) => arg.startsWith(flag)),
  );

  if (!fs.existsSync(reportFile)) {
    console.error(
      `::error::vitest wrote no JSON report (exit ${vitestExit}); cannot prove the run was complete`,
    );
    process.exit(vitestExit === 0 ? 1 : vitestExit);
  }

  const report = JSON.parse(fs.readFileSync(reportFile, "utf8"));
  const reported = new Map(
    (report.testResults ?? []).map((file) => [
      path.relative(webRoot, file.name).split(path.sep).join("/"),
      file.status,
    ]),
  );
  const passedFiles = [...reported.values()].filter(
    (status) => status === "passed",
  ).length;

  if (positional.length > 0 || subsetFilters.length > 0) {
    const what = [...positional, ...subsetFilters].join(", ");
    console.log(
      `::notice::filtered run (${what}): the completeness cross-check did NOT run, ` +
        `so a green result here does not prove the whole suite ran. Run \`npm test\` with no filter for that.`,
    );
    process.exit(vitestExit);
  }

  const discovered = discoverTestFiles().sort();
  const missing = discovered.filter((file) => !reported.has(file));

  console.log(
    `vitest completeness: ${passedFiles} passed of ${discovered.length} discovered test file(s)` +
      (reported.size !== passedFiles
        ? ` (${reported.size - passedFiles} of the reported files did not pass)`
        : ""),
  );

  if (missing.length > 0) {
    for (const file of missing) {
      console.error(
        `::error file=${file}::test file discovered but never ran (no result recorded)`,
      );
    }
    console.error(
      `::error::${missing.length} of ${discovered.length} test file(s) did not run; ` +
        `the suite result is incomplete and cannot be trusted as green`,
    );
  }

  if (
    missing.length > 0 ||
    reported.size < discovered.length ||
    vitestExit !== 0
  ) {
    process.exit(1);
  }
  process.exit(0);
}

const isEntry =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) ===
    path.resolve(fileURLToPath(import.meta.url));
if (isEntry) main();
