# DAST artifacts

Dated ZAP baseline outputs. Triage lives in
`docs/security_scans.md` §"DAST baseline (AUD-B-15)" — keep the two in sync
when a new run is added; never overwrite an existing dated pair.

| File | Run |
|---|---|
| `zap-baseline-2026-10-19.json` / `.html` / `zap-automation-config-2026-10-19.yaml` | TAG=b2 against `uvicorn` on 127.0.0.1:8020 with `ENV=ci LLM_PROVIDER=mock`. FAIL-NEW 0 / WARN-NEW 1 (Storable and Cacheable Content on 404s) / PASS 66. Image: `ghcr.io/zaproxy/zaproxy:stable` repo digest `sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2` — the `ci.yml` pinned digest could not be pulled from this environment (see the register). |

The scan is unauthenticated by design; authenticated surfaces are covered by
the authorization/tenancy negative suites, not by these artifacts.
