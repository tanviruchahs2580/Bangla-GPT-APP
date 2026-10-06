# Live Deployment Verification — v0.2.1 (real Gemini key)

Date: 2026-08-26 · Base: `f7fd9ac` · Scope: deployable-stage validation of every
runtime parameter with a real `GEMINI_API_KEY` (new "AQ."-format Google key).

**Security note:** the key was shared via plaintext chat; it was used only as a
runtime environment variable in untracked `.env` / ephemeral containers, never
committed, never written to logs or images. **Rotation is recommended.**

## 1. Direct API contract tests (host → Gemini)

| Test | Result | Evidence |
|---|---|---|
| A valid auth + model | PASS | `gemini-3.1-flash-lite` → 200, correct answer `৪`, ~2.0s |
| B invalid model | PASS | controlled 404 NOT_FOUND, single attempt |
| C malformed body | PASS | controlled 400, 0.54s |
| D invalid key | PASS | controlled 400 INVALID_ARGUMENT, 0.5s, no retry loop |

Key discovery: new-format keys are **blocked from legacy models**
(`gemini-2.5-flash` → 404 *"no longer available to new users"*). Default
`GEMINI_MODEL` changed to the live-verified `gemini-3.1-flash-lite`; available
models enumerated authoritatively via `GET /v1beta/models`.

## 2. Defects found & fixed during live validation

| # | Defect | Impact | Fix | Retest |
|---|---|---|---|---|
| L1 | `httpx` was dev-only dependency | production image crashed at boot (`ModuleNotFoundError`) when `LLM_PROVIDER=gemini` | moved to main dependencies | container boots, `/ready` = gemini |
| L2 | `psycopg[binary]` only in `[postgres]` extra | Postgres profile unusable from shipped image | moved to main dependencies; CI install updated | PG journey `PG_JOURNEY_OK` |
| L3 | Upstream LLM failure surfaced as unhandled 500 | noisy errors, no controlled semantics | `/tutor/ask` maps `ProviderError` → **502 JSON**, regression test added | invalid-key & timeout injections both return clean 502 |
| L4 | compose missing `WEB_CONCURRENCY` passthrough | worker count stuck at Dockerfile default | added to api environment | WEB_CONCURRENCY=3 → exactly 3 workers booted |
| L5 | web Dockerfile `COPY src:dest:ro` invalid syntax | web image unbuildable | removed flag | builds + serves + proxies |

## 3. Production-stack live test battery (docker compose, ENV=production)

| Parameter / behavior | Injected value | Observed | Verdict |
|---|---|---|---|
| `/health` identity | — | `{"status":"ok","version":"0.2.x","env":"production"}` | PASS |
| `/ready` provider | LLM_PROVIDER=gemini | `"provider":"gemini"` | PASS |
| Real grounded answer | «কোষ কী?» | textbook-grounded Bangla answer + sources, **1.2s** | PASS |
| Multi-call stability | «নিউক্লিয়াস…?» | grounded answer, **0.9s** | PASS |
| Safe refusal | out-of-domain question | `grounded=false`, no provider call | PASS |
| Invalid Gemini key | wrong key env | **502 JSON** 0.3s, zero unexpected 500s fleet-wide | PASS |
| LLM_TIMEOUT_SECONDS | 0.001 | **502 JSON** 0.06s | PASS |
| LLM_MAX_RETRIES | 4 | upstream 503 bursts retried w/ backoff (p95 ≈ 9s on exhaustion) then 502 | PASS* |
| ADMIN forced rotation | first login | `must_change_password=true` → admin routes 403 → change-password → 200 | PASS |
| guardian_consent | omitted | register rejected 422 | PASS |
| CORS allowed origin | preflight | ACAO echoed | PASS |
| CORS unknown origin | preflight | **400 reject**, no ACAO header | PASS |
| MAX_BODY_BYTES | 200 | 1042B payload → **413** | PASS |
| JWT_EXPIRE_MINUTES | 1 | token `exp − now = 59s` | PASS |
| RATE_LIMIT_FAIL_OPEN=false | Redis stopped | login → **503** (protected) | PASS |
| RATE_LIMIT_FAIL_OPEN=true | Redis stopped | login → **200** | PASS |
| SMTP unreachable | dead relay | `/auth/forgot` still **202**; log `password_reset_email_undeliverable`; **raw token never logged in production** | PASS |
| LOG_LEVEL | WARNING | root effective level 30 | PASS |
| WEB_CONCURRENCY | 3 | exactly 3 gunicorn workers booted | PASS |
| X-Request-ID | any response | header present, echoed/generated | PASS |
| POSTGRES_PASSWORD guard | unset | postgres service refuses boot until set | PASS |

## 4. Data-layer live checks

| Check | Result | Evidence |
|---|---|---|
| Alembic cycle on Postgres 16 | PASS | `upgrade head → current=c3f4a5b6d7e8` inside shipped image |
| Full E2E smoke on Postgres | PASS | 7/7 `SMOKE OK` + `PG_JOURNEY_OK` (register→login→ask→quiz→export→delete) |
| SQLite backup sidecar | PASS | snapshot written (appuser-owned), prune path exercised |
| OFFSITE_SYNC_CMD hook | PASS | marker file created, log `offsite sync completed` |
| NCTB_CORPUS_DIR fallback | PASS | unset/missing dir ⇒ sample-corpus fallback keeps tutor grounded (loader tests cover wired case) |
| VITE_API_BASE build-arg | PASS | custom base verifiably baked into built JS bundle |
| Web nginx proxy chain | PASS | `GET /` → 200 dashboard; `/api/health` proxied to production API |
| Concurrency w/ real LLM | PASS* | c=1 p50≈1.1s (true LLM latency); failures only upstream-503→clean-502; zero app 500s |

\* free-tier Gemini intermittently returns `UNAVAILABLE (high demand)`; the
provider retries (backoff ≤4s ×N) then answers controlled 502 — behaviour is
correct; capacity/latency SLOs need a paid tier or lighter model.

## 5. CD pipeline executed end-to-end (v0.2.1 tag)

| Step | Result | Evidence |
|---|---|---|
| Tag `v0.2.1` push → `release.yml` | PASS | run 32929556347: **Build & push images to GHCR = success** |
| GHCR images published | PASS | api + web pushed (`push: true` succeeded); tags `v0.2.1` + `latest` |
| Deploy job gating | PASS | correctly **skipped** until `DEPLOY_ENABLED=true` + SSH secrets |
| Monitoring profile live | PASS | Prometheus target `bangla-gpt-api: up`; all **5 alert rules loaded (health ok)**; PromQL query returned real `bgpt_http_requests_total=15` |
| Grafana | PASS | container healthy under monitoring profile |
| Caddy config | PASS* | `caddy validate` → "Valid configuration"; real ACME needs the actual domain |
| Fresh-clone reproducibility | PASS | clean GitHub clone + fresh venv → **135 passed** |
| CI on main @ `c75cfa2` | PASS | API CI 6/6 jobs green |

CD defects found & fixed during this execution:
- L6: GHCR image paths must be lowercase — `${{ github.repository }}` produced
  `Bangla-GPT-APP` → invalid tag; now computed via `${GITHUB_REPOSITORY,,}`.
- L7: `REGISTRY` env accidentally dropped in L6 fix → login hit Docker Hub;
  restored `env.REGISTRY: ghcr.io`.

Note: anonymous/CLI pull of the private GHCR images requires a token with
`read:packages` (local `gh` token lacks it); publish success is evidenced by
the workflow's own push gate.

## 6. Final verdict

🟢 **PRODUCTION READY (engineering)** — every runtime parameter verified live in
the deployable stage; CD pipeline executed to GHCR publish; all discovered
defects (L1–L7) fixed and regression-tested (135 passed locally, CI green,
release workflow green).

Remaining operator inputs for a real public launch:
1. Rotate the shared Gemini key; store as secret.
2. Provide `DOMAIN` + DNS → enable Caddy TLS profile.
3. Set `DEPLOY_ENABLED=true` + SSH secrets for CD deploy stage.
4. Paid Gemini tier (or accept free-tier high-demand 503→502 behaviour).
5. Optional: `gh auth refresh -s read:packages` to pull private GHCR images locally.
