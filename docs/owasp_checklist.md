# OWASP-lite Security Checklist (S5.6)

Compressed OWASP Top 10 (2021) review for Bangla GPT. Every line points at
real code and a real test that runs in CI -- nothing here is aspirational.
Companion scan evidence lives in `docs/security_scans.md`.

Legend: [DONE] implemented + tested | [PARTIAL] implemented, limitation noted
| [RISK] accepted, documented below.

## A01 -- Broken Access Control
- [DONE] Route-level auth on every non-public endpoint via `CurrentUser`
  dependency (JWT bearer); 401 unauthenticated, 403 wrong role.
  Tests: `apps/api/tests/test_security_v2.py::test_audit_view_is_admin_only`,
  `test_security.py`.
- [DONE] Object-level authorization: `authorize_student_access()`
  (`apps/api/src/bangla_gpt_api/main.py`) gates student data to the student
  themselves, their linked guardian, their school_admin (own school), or admin.
  Tests: `test_parent_dashboard.py`, `test_school_dashboard.py`.
- [DONE] Impersonation is admin-only and refuses admin/school_admin targets
  (403 `impersonation_forbidden`).
  Test: `test_security_v2.py::test_impersonation_refuses_admin_and_school_admin_targets`.
- [DONE] Role changes are admin-only and audited (see A09).

## A02 -- Cryptographic Failures
- [DONE] Passwords: PBKDF2-SHA256 with per-user salt and high iteration count
  (`apps/api/src/bangla_gpt_api/auth/security.py`, format
  `pbkdf2_sha256$<iterations>$<salt>$<digest>`). Never logged.
- [DONE] Guardian phone encrypted at rest with Fernet
  (`parents.phone_enc`, `apps/api/src/bangla_gpt_api/security.py`).
  Proof: raw-SQLite inspection asserts the cell starts with `fernet:` and the
  plaintext digits are absent from the entire DB file --
  `test_security_v2.py::test_guardian_phone_encrypted_at_rest_and_roundtrips`.
  Key handling: `PII_ENC_KEY` env var (names only, never values, in docs and
  logs); production boot refuses to start without it (A04).
- [DONE] TLS/HSTS at the edge: Caddy terminates TLS and sends
  `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  (`deploy/caddy/Caddyfile`).
- [PARTIAL] JWT HS256 single shared secret (`JWT_SECRET`). Fine at current
  scale; RS256 keypair rotation is a post-G5 item.

## A03 -- Injection
- [DONE] SQL: SQLAlchemy ORM/Core only; no string-formatted SQL anywhere in
  `apps/api/src`.
- [DONE] Prompt injection: system/user separation + injected-instruction guard
  on tutor input. Tests: `test_injection_guard.py`, `test_safety_v2.py`.
- [DONE] XSS: React escapes by default; the one markdown surface renders
  through a sanitizing path; no `dangerouslySetInnerHTML` of model output.
- [DONE] CSP: API sends a per-response nonce CSP
  (`SecurityHeadersMiddleware`, `main.py`; rotation proven by
  `test_security_v2.py::test_csp_nonce_rotates_per_response`). The SPA ships
  **no inline script at all** (`apps/web/public/theme-boot.js` is a static
  file), so Caddy can hold the strict `script-src 'self'` without a nonce --
  the stock `caddy:2-alpine` image cannot mint nonces (verified on v2.11.4),
  and removing inline script is strictly stronger than adding one. See the
  header comment in `deploy/caddy/Caddyfile`.

## A04 -- Insecure Design
- [DONE] Fail-closed production boot: `enforce_production_safety()`
  (`apps/api/src/bangla_gpt_api/config.py`) refuses mock provider, wildcard
  CORS, default admin password, missing `PII_ENC_KEY`, bad
  `RATE_LIMIT_BACKEND` in prod. Tests: `test_admin_hardening.py`,
  `test_security_v2.py::test_production_boot_requires_pii_enc_key` (with a
  positive control proving the refusal is specific to the missing key).
- [DONE] Child-safety design: guardian consent gate at registration, counts-
  only logging of chat activity (R11), guardian-visible data export.

## A05 -- Security Misconfiguration
- [DONE] Security headers on every API response
  (`SecurityHeadersMiddleware`; `test_security_headers.py`): nosniff,
  frame-ancestors/DENY, referrer-policy, CSP; on the SPA via Caddy
  (`deploy/caddy/Caddyfile`): same set + HSTS includeSubDomains.
- [DONE] CORS: explicit allowlist from `CORS_ORIGINS`; no wildcard in prod
  (enforced at boot). Tests: `test_cors.py`.
- [DONE] `Server` header stripped at the edge (`-Server` in Caddyfile).
- [RISK] `/docs`, `/redoc`, `/openapi.json` are exempt from the API CSP and
  are dev surfaces. Accepted for now because they only appear on the API
  origin (behind Caddy's `/api` path strip) and carry no session state;
  removing them in prod images is a post-G5 hardening ticket.

## A06 -- Vulnerable & Outdated Components
- [DONE] CI gates: `pip-audit` on the API job and
  `npm audit --audit-level=high --omit=dev` on the web job
  (`.github/workflows/ci.yml`). Triage register: `docs/security_scans.md`.
- [DONE] Deployed web artifact is a static nginx image (multi-stage
  `apps/web/Dockerfile`) -- the dev-server advisories in the register never
  ship.

## A07 -- Identification & Authentication Failures
- [DONE] Rate limits at the app layer: `/auth/login` per-IP and tutor
  endpoints per-user (`main.py` limiter table;
  `test_ratelimit_backends.py`, `test_auth_teacher.py`).
- [DONE] Password policy: min length 8, max 128 (`schemas.py`).
- [DONE] Forced rotation: `must_change_password` flag on admin-seeded
  accounts (`test_admin_hardening.py`).
- [DONE] Email verification + reset-token flow with single-use tokens
  (`test_password_reset.py`, `test_email_verification` coverage in
  `test_auth_teacher.py`).
- [PARTIAL] No progressive login lockout beyond the per-IP rate limit;
  accepted at current threat model, revisit with a real user base.

## A08 -- Software & Data Integrity Failures
- [DONE] Migrations are append-only Alembic revisions; CI runs
  upgrade-head -> downgrade-base -> upgrade-head on every push.
- [DONE] Supply chain: lockfiles committed (`package-lock.json`, pinned
  pyproject deps); CI `npm ci` (not `npm install`).
- [PARTIAL] Impersonation tokens are stateless JWTs: a live impersonation
  session cannot be revoked before its hard 15-minute ceiling; stop-endpoint
  plus audit rows make the window attributable. Revocation list is a S5.10
  follow-up. Test: `test_security_v2.py::test_impersonated_token_is_short_lived_and_attributable`.

## A09 -- Logging & Monitoring Failures
- [DONE] Audit trail (`audit_log` table, migration
  `f9a0b1c2d3e4`): role_change, data_export, purge, qp_finalize,
  impersonation -- all five verified end-to-end including actor attribution,
  newest-first admin view with filters/pagination
  (`test_security_v2.py::test_all_five_event_types_write_audit_rows`,
  `test_audit_view_filters_and_pages`).
- [DONE] Privacy-preserving audit detail: purge logs counts only
  (`test_security_v2.py::test_purge_audit_detail_is_counts_only`); chat
  content is never logged (R11).
- [DONE] Structured JSON request logs with request-id correlation
  (`test_request_context.py`, `test_health_observability.py`).

## A10 -- Server-Side Request Forgery
- [DONE] LLM/provider egress goes only to fixed base URLs from config
  (Gemini SDK client in `providers/gemini.py`); no user-controlled URLs are
  fetched server-side.
