import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

/**
 * `npm run deadcode` — knip with its raw-transfer parser disabled.
 *
 * knip's oxc parser reserves a ~6 GiB ArrayBuffer up front on Node >= 22
 * (experimental raw transfer). On a memory-pressured developer machine that
 * reservation fails with "RangeError: Array buffer allocation failed" before
 * any file is analysed, on a run that exited 0 a minute earlier. knip's own
 * documented escape hatch (KNIP_DISABLE_RAW_TRANSFER=1) parses without the
 * reservation; set it here so the script behaves the same in cmd, Git Bash
 * and CI.
 */
const require = createRequire(import.meta.url);
const knipBin = join(
  dirname(dirname(fileURLToPath(import.meta.resolve("knip")))),
  "bin",
  "knip.js",
);

const result = spawnSync(process.execPath, [knipBin, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, KNIP_DISABLE_RAW_TRANSFER: "1" },
});
process.exit(result.status ?? 1);
