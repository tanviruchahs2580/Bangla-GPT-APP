# T-17 hardening inventory

Measured 2026-11-20 at `1ef1530` (branch `remediation/0.2.0`). Observed responses come from the local test client (`evidence/T-17/observed-headers.txt`, no network); every code claim is `[F: path:lines]` read this session.

## Response headers (application layer)

| Header | Observed | Where enforced |
|---|---|---|
| `Content-Security-Policy` | default-src 'self'; script-src 'self' 'nonce-<per-response>'; style-src 'self' 'unsafe-inline'; img-src 'self' data:…; frame-ancestors 'none' — on every response incl. 401 | `middleware.py:303-340` (SecurityHeadersMiddleware, nonce per response; `/docs`, `/redoc`, `/openapi.json` exempt by documented list `:321`) |
| `X-Content-Type-Options: nosniff` | yes, every response | `middleware.py:314` |
| `Referrer-Policy: no-referrer` | yes | `middleware.py:316` |
| `X-Frame-Options: DENY` | yes | `middleware.py:315` region |
| `Strict-Transport-Security` | at the TLS edge only (correct layer): `deploy/caddy/Caddyfile:22` max-age=31536000 includeSubDomains; app constant `middleware.py:298-300` matches the edge value | proxy + app mirror |
| `Permissions-Policy` | NOT present — candidate gap | — |
| CORS | `initialize/middleware_stack.py` — CORS registered LAST (outermost); 429/413 carry CORS headers (rate-limited responses readable cross-origin, pinned by tests/test_cors.py) | middleware_stack.py |

## Surface exposure

| Surface | Test env | Production |
|---|---|---|
| `/docs`, `/redoc`, `/openapi.json` | served | **disabled** (`main.py:771` `serve_docs = not settings.is_production`; SEC-15 comment cites the measured 158 KB prod schema leak) |
| `/metrics` | open | bearer-gated when `METRICS_REQUIRE_AUTH` + `METRICS_TOKEN` (`routers/system.py:145-146`; constant-time compare) |
| `/health`, `/live`, `/ready`, `/status` | public, booleans only (`PUBLIC_OPERATIONS`, main.py:667-690) | same |

## Production configuration guards (BC-8) — all wired in `enforce_production_safety` (main.py:140-158)

`_validate_smtp` · `_validate_jwt` (override + entropy + weak-pattern/sequential-run detection) · `_validate_password_hash_parameters` (T-12/BC-8, Argon2id floor) · `_validate_admin` · `_validate_cors` (no wildcard) · `_validate_database` (in-memory refused; file-SQLite refused with >1 worker) · `_validate_pii` · `_validate_metrics` · `_validate_rate_limit_redis` (memory+multi-worker refused) · `_validate_llm_provider` (mock refused unless explicit demo opt-in; unknown names refused) · `_validate_direct_parent_link` · `_validate_corpus` (no bundled-sample with a billable provider) · `_validate_ai_budget` (positive per-user cap) · `_validate_llm_budget` (retry budget < worker timeout) · `_validate_llm_data_use` · `_validate_rag_grounding` (coverage floor 0.5 / top-k ceiling 3) · `_validate_reranker_endpoint`. An unrecognized `ENV` value is guarded AS production (`ENV-gate`, main.py:131-138) — the typo'd-ENV boot refusal is exercised in CI's docker job against the real image.

## Remaining items and their routing

| Item | Status | Route |
|---|---|---|
| `Permissions-Policy` header missing | behavior-preserving addition candidate — NOT added in T-17 (S-3: it changes observable response headers on every route; the card requires S-3 for changes users/operators see) | S-3 record below |
| CSP is ENFORCED, not report-only | exceeds the BC-6 "report-only may ship" default; weakening it to report-only would be a regression — keep enforced, record | contradiction note in STATE.md |
| Upload validation / request-size limits | `BodySizeLimitMiddleware` + image re-encode safety (`providers/image_safety.py`) | tested (test_chat_image_validation) |
| Auth rate limits | login/MFA per-IP + per-user budgets (config.py:422-431) | tested (test_quiz_path_rate_limits, ratelimit suites) |
| Published ports / container user | compose services bind per profile; Postgres runs as `postgres` user (docker-compose.yml:435) | T-33 reviews the compose profile |
