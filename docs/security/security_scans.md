# Security scan register

One register for every scanner that runs against this repository, what it
gates on, and the triage decisions behind anything it is configured to accept.
It merges the former dependency register at `docs/security_scans.md` (now a
pointer) with the wave-2 tool register, so there is one review-by discipline
and one place to read a waiver.

Last reviewed: **2026-10-29** (next review due 2026-11-28, or earlier when a
new advisory lands). Advisory source for the per-alert table: the open
Dependabot alerts on `tanviruchahs2580/Bangla-GPT-APP` (11 open at the check
date, read with `gh api repos/.../dependabot/alerts?state=open`) plus a local
`npm audit` of `apps/web/package-lock.json`.

## CI gates

`.github/workflows/ci.yml`:

- API job: `python -m pip_audit` over the locked venv.
- Web job: `npm audit --audit-level=high --omit=dev` after `npm ci`.
- Guardrails job: semgrep at ERROR severity, hadolint over both Dockerfiles,
  and the trivy filesystem scan of the shipped npm tree.
- Docker job: trivy image scan (fixable HIGH/CRITICAL). Gitleaks full-history
  and CodeQL run as their own workflows.

The web gate scans **prod dependencies only** because the deployed artifact
is a static nginx image: `apps/web/Dockerfile` is multi-stage (node build ->
`nginx:1.29-alpine` serving `dist/`), so no JS runtime dependency ships. The
vite/esbuild dev servers never reach a deployment target. The dev-tree
advisories below are deliberately outside that gate, so they are tracked
here individually.

## Semgrep (SEC-18)

- Version: semgrep 1.182.1. Rulesets: `p/python`, `p/typescript`,
  `p/react`, `p/docker`, `p/github-actions`, `p/secrets`. Run from the
  repository root; CI pins the version and the same command.
- Command: `semgrep --config p/python --config p/typescript --config p/react
  --config p/docker --config p/github-actions --config p/secrets
  --severity ERROR --error --timeout 60 --metrics=off .`
- Gate: any ERROR-severity finding fails the `guardrails` job. WARNING-level
  findings are triaged in this register but do not fail the build, so the
  gate cannot be flipped by a rule that is not a defect.
- Scope and triaged allowlist: `.semgrepignore`. Four entries, each with
  its reason in the file: alembic migrations (append-only DDL, constants
  only), `scripts/backup_loop.py` (operator-configured offsite command),
  `apps/web/Dockerfile` (stock nginx master binds :80; see "hadolint" and
  the DOCK stream for the unprivileged-image follow-up), and the four
  token-construction test files whose literal fixture secrets are the same
  convention ruff's per-file-ignores already records for tests.
- Fixed in this round rather than allowed: `run-shell-injection` in
  `vercel-deploy.yml` (github context was interpolated straight into a
  `run:` block; it now reaches the shell through `env:`).
- Warning-level finding accepted: `insecure-hash-algorithm-sha1` at
  `apps/api/src/bangla_gpt_api/nctb/chunking.py:145` - SHA-1 is used with
  `usedforsecurity=False` as a non-cryptographic stable id for chunk metadata
  (the content fingerprint above it is SHA-256). Switching ids would orphan
  every persisted chunk reference for no security gain.

## hadolint

- Version: hadolint 2.15.1, blocking step in the `guardrails` job over
  `Dockerfile` and `apps/web/Dockerfile`.
- Result on this tree: zero findings. The single rule accepted by design is
  `DL3008` in `.hadolint.yaml` (`postgresql-client` intentionally unpinned;
  openssl and libssl3t64 are pinned in the Dockerfile with the refresh
  procedure documented there).

## Trivy

- Image and filesystem scans; the image gate in the `docker` job (fixable
  HIGH/CRITICAL) already existed. Wave 2 added the filesystem/dependency
  scan to the `guardrails` job and re-ran both locally against the built
  image. Version and results: see the wave-2 evidence folder; the gate is
  `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`.
- Configuration (`--scanners misconfig`) is part of the filesystem scan, so
  Dockerfile/compose hardening drift fails the build.

## pip-audit (apps/api)

Re-run **2026-10-29** against `apps/api/constraints.txt`: **no known
vulnerabilities found** (`python -m pip_audit -r apps/api/constraints.txt`,
exit 0; evidence `.qa-work/evidence/E-FIX-F-057-1/pip-audit.txt`). CI re-runs
the same audit on every push, so that job's log is the current answer.

## npm audit --omit=dev (apps/web)

Re-run **2026-10-29**: **4 low-severity entries, exit 0**, all one advisory -
`katex` GHSA-238p-pmpm-9mq7 ("Existing prototype pollution can bypass trust
restrictions", range 0.11.0-0.18.1, patched 0.18.2). npm attributes the same
advisory to `rehype-katex` and `remark-math` (direct) and
`micromark-extension-math` (transitive) because each still resolves a nested
vulnerable `katex`. The app also depends on `katex` ^0.18.5 directly, but the
markdown render path (`apps/web/src/lib/safeMarkdown.tsx`) uses
`rehype-katex@7.0.1`, which pins its nested `katex@0.16.47`; the browser
bundle therefore still contains the vulnerable copy. The CI gate is
`npm audit --audit-level=high --omit=dev`, so low-severity findings are
reported but do not fail it - "0 vulnerabilities" would be wrong. **No
high/critical advisory ships.**

## Open Dependabot alerts - one row per advisory (2026-10-29)

All web alerts are in `apps/web/package-lock.json`. "Dev" = not in the
deployed bundle (test/dev toolchain); "runtime" = reachable in the built
artifact. Waivers carry an expiry; the deferred fixes are one toolchain
refresh, not piecemeal majors.

| # | GHSA | Severity | Package | Installed | Path | Reachability | Decision |
|---|---|---|---|---|---|---|---|
| 1 | GHSA-67mh-4wv8-2f99 | medium | esbuild | 0.21.5 | dev (transitive of vite 5) | Dev server only: any origin can read responses from a running esbuild service. Needs an attacker who can reach the developer's machine. | Waiver to 2027-01-31 (fix needs vite >=6, a build-toolchain major) |
| 2 | GHSA-4w7w-66w2-5vf9 | medium | vite | 5.4.21 | dev (direct) | Dev-server optimized-deps `.map` path traversal; requires a reachable dev server. | Waiver to 2027-01-31 (patched from 6.4.2) |
| 3 | GHSA-fx2h-pf6j-xcff | medium | vite | 5.4.21 | dev (direct) | `server.fs.deny` bypass on Windows alternate paths; dev server only. | Waiver to 2027-01-31 (patched from 6.4.3) |
| 4 | GHSA-v6wh-96g9-6wx3 | medium | vite (launch-editor) | 5.4.21 | dev (direct) | NTLMv2 hash disclosure via crafted URLs opened by the dev server on Windows. | Waiver to 2027-01-31 (patched from 6.4.3) |
| 6 | GHSA-698v-4r3x-3vcv | medium | vite (launch-editor) | 5.4.21 | dev (direct) | Editor CLI flag misinterpretation can run a command for some editors; dev machine only. | Waiver to 2027-01-31 (patched from 6.4.4) |
| 7 | GHSA-587h-7wmj-h5pm | high | vite (launch-editor) | 5.4.21 | dev (direct) | `fs.existsSync()` existence-check bypass on Windows in the dev-server editor launcher; no production path. | Waiver to 2027-01-31 (patched from 6.4.4) |
| 8 | GHSA-r825-w8mm-5pxw | medium | vite (launch-editor) | 5.4.21 | dev (direct) | Editor CLI flag misinterpretation -> arbitrary command execution for some editors; dev machine only. | Waiver to 2027-01-31 (patched from 6.4.4) |
| 9 | GHSA-rq7h-c2jc-7f22 | medium | vite | 5.4.21 | dev (direct) | Files outside `server.fs.allow` could be served when project paths match system paths; dev server only. | Waiver to 2027-01-31 (patched from 6.4.4) |
| 10 | GHSA-9jrq-w75r-8gcw | low | vite | 5.4.21 | dev (direct) | Cross-origin script execution through Vite custom middleware; dev server only. | Waiver to 2027-01-31 (patched from 6.4.4) |
| 5 | GHSA-238p-pmpm-9mq7 | low | katex | 0.16.47 (nested) | **runtime** (browser bundle) | Requires a prototype-pollution primitive from elsewhere plus KaTeX's `trust` handling; no other prototype-pollution advisory exists in the shipped tree, `rehype-katex@7.0.1` passes no `trust` option (KaTeX default `trust: false`), and `react-markdown` runs without `rehype-raw`, so raw HTML is not rendered. Residual risk accepted. | Waiver to 2027-01-31 (needs a rehype-katex/remark-math range that accepts katex 0.18.x, or an npm `overrides` pin - bundle-wide change, scheduled with the toolchain refresh) |
| 13 | GHSA-xjj6-f33q-929c | high | undici | 8.11.2 -> **8.12.3** | dev (transitive of jsdom 30) | Test environment only (`jsdom` needs `undici ^8.9.0`); never in `dist/`. DoS via unhandled error on excessive content-encodings. | **Fixed 2026-10-29** by an in-range lockfile bump (see below) |

Notes:

- Alert 13 is one Dependabot alert; `npm audit` bundles the eight undici
  sub-advisories (four high: GHSA-xjj6-f33q-929c, GHSA-4w7w-5xrc-9h26,
  GHSA-2m5v-pch6-74hx, GHSA-qrxm-fqhp-jwvm) into a single entry, all with the
  range `>=8.0.0 <8.12.2`. Bumping undici to 8.12.3 cleared the whole bundle:
  the full `npm audit` went from 7 vulnerability entries to 6 and no undici
  entry remains (evidence `.qa-work/evidence/E-FIX-F-057-1/`).
- Alert 1's esbuild is shared by the vite 5 build pipeline
  (`esbuild@0.21.5`); its patched line 0.25+ cannot be reached without the
  same vite major bump.

## Remediation path for the deferred (waived) set

One toolchain refresh: vite 5 -> current major (8.x at the check date),
which brings esbuild >=0.25, launch-editor >= patched and rehype-katex on a
katex 0.18.x range. The lockfile-wide churn plus plugin compatibility
(`@vitejs/plugin-react`, vitest) is why it is not part of a
security-hardening step's smallest-change budget. Dev-workstation mitigation
meanwhile: keep vite's default localhost binding, do not use `--host` on
untrusted networks. Escalate the review-by date early if any of these
advisories is raised to high/critical reachable at runtime.

## Other scanners (unchanged, listed for completeness)

- bandit 1.9.4: the audit's run (9 Low + 1 Medium, 0 High) is triaged
  false-positive-by-design in the wave-1 SEC audit register
  (`.qa-work/audit/SEC/`), alongside the CodeQL triage in
  `docs/security/codeql-triage-2026-10-27.md`.
- ruff `S` (flake8-bandit) is enabled in `pyproject.toml` and clean.
- pip-audit and `npm audit --omit=dev` gate the `api` / `web` jobs (their
  current results are the two sections above).
- gitleaks full-history scan and CodeQL run as their own workflows.
- OWASP ZAP has no automated run in this environment; the hermetic red-team
  gate (`evaluation/cli.py --redteam`) covers the prompt-injection surface
  and is a CI candidate recorded with the TEST stream.

## Re-running the scans

```bash
# API
cd apps/api && python -m pip_audit -r constraints.txt   # CI does the same in-job
# Web
cd apps/web && npm audit --omit=dev          # gate: fails on HIGH or above
cd apps/web && npm audit                     # full picture incl. dev deps
# Advisory register (open alerts, per alert)
gh api "repos/tanviruchahs2580/Bangla-GPT-APP/dependabot/alerts?state=open&per_page=100"
```

Update this register whenever the triage set changes, and record the check
date at the top plus a review-by date per waiver (none of the four
vite/esbuild dev-server advisories and no waiver here may outlive its expiry
without a re-decision).
