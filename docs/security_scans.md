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

```sh
# API
apps/api: python -m pip_audit -r <(python -m pip freeze)   # CI does this in-job
# Web
apps/web: npm audit --omit=dev          # gate: fails on HIGH or above, not on 0
apps/web: npm audit                     # full picture incl. triaged dev deps
```

Update this register whenever the triage set changes.

## DAST baseline (AUD-B-15)

A ZAP 2.17.0 baseline scan against the running test-mode API container
(`http://127.0.0.1:8000`, `ENV=test`) on 2026-10-18 produced
`FAIL-NEW 0 / WARN-NEW 1 / PASS 66`; the single warning is the
storable-and-cacheable-404 rule (no cache headers on 404s). Artifacts from
that run live in `.audit/tmp/zap/` (audit workspace, not committed). That
scan was ad hoc: nothing in `.github/workflows` runs DAST, so there is no
repo-owned baseline and no trend.

Status: **accepted as an ad-hoc cadence for now, with a handoff**. A
scheduled ZAP baseline job (weekly, against the compose test stack, report
archived as a workflow artifact) is specified as an exact YAML block in
`.audit/handoffs/ef-from-b.md`; until that job exists, re-run manually with:

```sh
# test-mode stack up, then:
docker run --rm -v "$(pwd)/.zap:/zap/wrk:rw" -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t http://host.docker.internal:8000 -r zap-baseline.html -J zap-baseline.json
```

Caveat unchanged: an unauthenticated baseline does not exercise
authenticated surfaces (tutor, admin, exports); those are covered by the
authorization/tenancy negative suites.

## SBOM and licence artifacts (AUD-B-16)

`release.yml` builds both images with buildx `sbom: true` and
`provenance: mode=max`, but no release has been cut in this repo, so no SBOM
artifact exists to inspect (`git ls-files` has none) and the licence
inventory lives only as `THIRD_PARTY_NOTICES.md` prose. Status: the licence
inventory is committed; the generated SBOM and a CI licence gate are
handed off as an exact YAML block in `.audit/handoffs/ef-from-b.md`
(CycloneDX per image + a `pip-licenses`/`license-checker` gate against the
existing notices file).
