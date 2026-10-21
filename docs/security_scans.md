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

Status: **repo-owned baseline exists (weekly CI job) and the dated local
report is now committed** under `docs/security/dast/`.

### Committed run — 2026-10-19 (TAG=b2)

Target: a locally started API — `uvicorn bangla_gpt_api.main:app` on
`127.0.0.1:8020` with `ENV=ci LLM_PROVIDER=mock` and a throwaway JWT secret —
reached from the ZAP container as `http://host.docker.internal:8020`. Mock
provider: no LLM key, no outbound traffic. `ENV=ci` keeps `/docs` and
`/openapi.json` enabled exactly as the CI DAST job's test posture does.

Result: **FAIL-NEW 0 / WARN-NEW 1 / PASS 66** (same shape as the 2026-10-18
ad-hoc run).

Artifacts:

- `docs/security/dast/zap-baseline-2026-10-19.json` (machine report)
- `docs/security/dast/zap-baseline-2026-10-19.html` (human report)
- `docs/security/dast/zap-automation-config-2026-10-19.yaml` (the exact
  automation plan ZAP generated for the run)

Image: the workflow pins
`ghcr.io/zaproxy/zaproxy@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6`.
That digest could not be pulled in this environment (two attempts, ~30 min,
no layer progress — the registry transfer stalled), so this run used the
locally available `ghcr.io/zaproxy/zaproxy:stable`, recorded as
`sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2`
(10 days old at run time). Same ZAP 2.17.0 rule pack; **re-run with the pinned
digest before treating numbers as release-grade**. The CI job still uses the
pin.

Triage of the single warning:

| Alert | Instances | Verdict |
|---|---|---|
| 10049 Storable and Cacheable Content (Informational, Medium confidence) | `GET /` 404, `GET /robots.txt` 404 (no `Cache-Control` on the API's 404 bodies) | **Accepted-with-action for the API**; not fixed in this round because the header set lives in `apps/api/src/bangla_gpt_api/middleware.py` (outside this agent's file set). Exact patch + rationale handed to the middleware owner in `.audit/handoffs/middleware-b2.md`. Impact is low: the bodies are the fixed coded 404 envelope, the API sits behind Caddy which can also set the header, and no per-user data is ever served on a 404. The CI ZAP job runs with `-I` (warn-level does not fail), so this stays a tracked warning, not a gate. |

Everything else passed (66 PASS rules), including the security-headers,
anti-CSRF-absence and information-disclosure rule families. Caveat unchanged:
an unauthenticated baseline does not exercise authenticated surfaces (tutor,
admin, exports); those are covered by the authorization/tenancy negative
suites.

Re-run locally (test-mode posture):

```sh
docker run --rm -v "$(pwd)/docs/security/dast:/zap/wrk:rw" \
  ghcr.io/zaproxy/zaproxy@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6 \
  zap-baseline.py -t http://host.docker.internal:8000 -J zap-baseline.json -r zap-baseline.html -I
```

## SBOM and licence artifacts (AUD-B-16)

Status: **fixed**. The CI job `sbom-licence` (`.github/workflows/ci.yml`)
generates both SBOMs and enforces the licence gate on every PR; the missing
piece — a dated, repo-owned artifact — now lives under `docs/security/sbom/`:

- `bangla-gpt-api-2026-10-19.cdx.json` — CycloneDX 1.6, 91 components, the
  runtime set installed from the hash-verified `apps/api/constraints.txt`.
- `bangla-gpt-web-2026-10-19.cdx.json` — CycloneDX 1.6, 127 components, the
  production tree from `package-lock.json` (`--omit dev`, same semantics as
  the CI job).
- `licence-inventory-2026-10-19.md` — machine-derived licence counts plus
  every copyleft/restricted/unresolved component, with review notes
  (LGPL-3.0-only `fpdf2`/`psycopg`(+binary) covered by the existing relink
  note; `pyphen` triple-license; MPL-2.0 file-level set; OFL-1.1 fonts).
- `README.md` — exact regeneration commands, tool pin caveat and the
  release-time buildx attestation note (still unverifiable until a release
  is cut).
