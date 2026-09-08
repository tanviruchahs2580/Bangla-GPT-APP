# Dependency Scan Register (S5.6)

CI gates (`.github/workflows/ci.yml`):
- API job: `python -m pip_audit` over the locked venv.
- Web job: `npm audit --audit-level=high --omit=dev` after `npm ci`.

The web gate scans **prod dependencies only** because the deployed artifact
is a static nginx image: `apps/web/Dockerfile` is multi-stage (node build ->
`nginx:1.27-alpine` serving `dist/`), so no JS runtime dependency ships. The
vite/esbuild dev servers never reach a deployment target.

## pip-audit (apps/api)
Latest run (S5.6, this branch): **no known vulnerabilities** across the
locked dependency set.

## npm audit --omit=dev (apps/web)
Latest run: **0 vulnerabilities.** This is what the CI gate enforces.

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
(R10); tracked for the next scheduled toolchain refresh. Dev-workstation
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
