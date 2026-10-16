# Dependency Scan Register

CI gates (`.github/workflows/ci.yml`):
- API job: `python -m pip_audit` over the locked venv.
- Web job: `npm audit --audit-level=high --omit=dev` after `npm ci`.

The web gate scans **prod dependencies only** because the deployed artifact
is a static nginx image: `apps/web/Dockerfile` is multi-stage (node build ->
`nginx:1.27-alpine` serving `dist/`), so no JS runtime dependency ships. The
vite/esbuild dev servers never reach a deployment target.

## pip-audit (apps/api)
Re-run 2026-10-16 against this venv: **no known vulnerabilities found**
(`python -m pip_audit`, exit 0; the only skipped entry is the local
`bangla-gpt-api` package itself, which is not on PyPI). CI re-runs the same
audit on every push, so that job's log is the current answer.

## npm audit --omit=dev (apps/web)
Re-run 2026-10-16: **4 low-severity advisories in the markdown/katex render
chain, exit 0.** `katex` 0.16.47 (via `micromark-extension-math`,
`remark-math`, `rehype-katex`) carries GHSA-238p-pmpm-9mq7, "Existing
prototype pollution can bypass trust restrictions" (range 0.11.0–0.18.1);
the fix is a semver-major `rehype-katex` bump. The CI gate is
`npm audit --audit-level=high --omit=dev`, so low-severity findings are
reported but do not fail it — "0 vulnerabilities" would be wrong, and the
earlier "0 vulnerabilities" line here was that mistake. No high/critical
advisory ships.

## npm audit (dev deps) -- triaged, not gate-blocking
Full `npm audit` reports advisories in the dev toolchain. Each requires a
running dev server on the developer's own machine, so none is reachable in
production. Triaged 2026-09-06:

1. vite <= 6.4.2 -- dev-server optimized-deps `.map` path traversal.
   Requires an attacker who can already reach your dev server's port.
2. vite <= 6.4.2 -- launch-editor handler can be driven to NTLMv2 hash
   leakage on Windows via crafted URLs. Dev-machine-only, same reachability
   precondition.
3. vite <= 6.4.2 -- `server.fs.deny` bypass on Windows path normalization.
   `server.fs` is only active on the dev server.
4. esbuild <= 0.24.2 (GHSA-67mh-4wv8-2f99) -- dev-server CORS: any origin
   could read responses from a running esbuild service. Transitive of vite's
   dev pipeline only.

Remediation path: fixed by vite >= 6.4.3 / current major line, which is a
major-version bump of the build toolchain (lockfile-wide churn, plugin
compatibility checks). Deliberately deferred -- a build-toolchain major
bump does not belong in a security-hardening step's smallest-change budget
; tracked for the next scheduled toolchain refresh. Dev-workstation
mitigation meanwhile: keep vite's default localhost binding, do not use
`--host` on untrusted networks.

## Re-running the scans
```
# API
apps/api: python -m pip_audit -r <(python -m pip freeze)   # CI does this in-job
# Web
apps/web: npm audit --omit=dev          # gate (must stay 0)
apps/web: npm audit                     # full picture incl. triaged dev deps
```
Update this register whenever the triage set changes.
