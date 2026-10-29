# Threat model — Bangla GPT API and web app

State at BASE_SHA `7e8525e2` (2026-10-29), refreshed on branch
`qa/enterprise-v2-hardening` after the fix wave. Derived from the D1 security
audit (`.qa-work/audit/SEC/report.md`, evidence ids `E-SEC-*`) and its code
reads; every mitigation cites a repository `file:line` or an evidence id.
Where a control is partial the audit finding id is stated; entries marked
`FIXED (<sha>)` were remediated on this branch and carry a regression test.
This is a working document, not a certification; keep it in step with
`docs/owasp_checklist.md`. Companion documents: `docs/ai/system-card.md`,
`docs/ai/risk-register.md`, `docs/ai/incident-response.md`.

## 1. Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| Child accounts and sessions | `users`, `students`, access JWTs | account takeover exposes a minor's data |
| Child content: chat messages, quiz answers, progress | `conversations`, `chat_messages`, `quiz_attempts`, `answer_log`, learning tables (`db/models.py`) | sensitive personal data of minors |
| Guardian contact phone | `parents.phone_enc`, encrypted with the app Fernet key | guardian PII, never exported |
| Credentials | Argon2id password hashes, MFA secrets, hashed single-use reset/verification tokens | authentication integrity |
| Teacher and school content | `teacher_documents`, `question_papers`, `question_bank`, assignments | school IP and assessment integrity |
| Corpus and retrieval index | `data/nctb`, in-process index (`initialize/dependencies.py:240-311`) | answer grounding and availability |
| Audit trail | append-only `audit_log` | incident reconstruction |
| Provider and infrastructure secrets | environment (`GEMINI_API_KEY`, `OPENAI_API_KEY`, JWT and encryption keys) | external cost and data exposure |

## 2. Actors

- Anonymous internet user (credential stuffing, probing public routes).
- Student (minor; the actor whose data is most sensitive).
- Teacher, parent, school admin (legitimate, scoped roles).
- Platform admin, and separately a platform admin operating an impersonation
  session (support mode with its own token claims).
- Malicious or compromised school staff (insider with a legitimate role).
- Malicious content: a poisoned corpus document, a prompt-injection question,
  or text inside an uploaded image.
- Third parties: LLM provider (Gemini/OpenAI), SMTP relay, Sentry (optional).

## 3. Trust boundaries

1. Browser → TLS edge (Caddy/nginx/Vercel) → `api:8000`. The API refuses a production boot with the mock provider, SQLite + multi-worker, or wildcard CORS (`main.py:78-372`; `main.py:324-345`).
2. API → Postgres/SQLite and Redis (sessions, rate limits, revocation, cache). Redis-backed revocations are fail-closed: a cache failure answers 503 rather than permitting a revoked token (`routers/deps.py:102-140`).
3. API → LLM provider. Prompts carry the redacted question, retrieved passages and limited history; provider logs record character counts, not text (audit PRIV-06).
4. API → SMTP (recipient address + message).
5. Ingestion → corpus → index. Corpus text is untrusted data: filtered at ingest and sanitized at prompt assembly (`services/safety.py:139-207`; `services/tutor.py:132-141`).
6. Admin → impersonation session → user-scoped routes.

## 4. Threats and controls by surface

### 4.1 Authentication

Threats: credential stuffing and brute force; token forgery or replay; session
theft persistence; account enumeration through error differences.

Controls:
- Argon2id at the OWASP parameters (`auth/security.py:9-22,159-165`).
- Login throttling 10/min per IP, MFA challenge 5/min, lockout counters (`config.py:218-219`; `routers/auth.py:336-371`).
- JWT HS256 pinned, `iss`/`aud` required, unique `jti` on every access token, per-token deny-list and an epoch invalidation stamp (`auth/security.py:218-251,257-266`; `routers/deps.py:187-196`).
- Single-use, SHA-256-hashed password-reset and verification tokens with expiry and a 30-day grace sweep (audit SEC-03, E-SEC-03-1).
- Identity fields (name, email, guardian phone, invite code, school name) reject U+0000 and the bidi formatting controls with a stable 422 `invalid_characters`; free-text bodies keep them deliberately (`schemas.py:59-73`, `schemas.py:203-217`; `tests/test_qa_control_chars.py`, FIXED c98dead).
- Failed logins, armed lockouts and attempts against a locked account emit WARNING `json_log` lines with ids/counts and a truncated SHA-256 for unknown addresses — never the raw email (`routers/auth.py:336-350,413-470`; `tests/test_qa_auth_logging.py`, FIXED 075cc00). The log line is the only trace: no `audit_log` action exists for auth events by design (row volume under attack).
- 71 auth tests plus the OpenAPI auth matrix passed (E-SEC-03-1, E-SEC-04-1); `tests/test_jwt_claims.py`, `tests/test_round2_auth_hardening.py`, `tests/test_single_use_tokens.py`.
- Shared-password test accounts cannot be published to a real database: the e2e seeder refuses unless ENV names a development/CI lane (`apps/web/e2e/seed_e2e_users.py:88-107`; `tests/test_qa_e2e_seeder_guard.py`, FIXED ab84a94).

Partial / open:
- `POST /auth/register` answers 409 `email_taken`, an enumeration oracle the other credential routes do not have (F-SEC-3, owner decision).
- Password floor is 8 characters with no tracked NIST citation (F-SEC-2, owner decision).

### 4.2 Tutor chat and the LLM path

Threats: prompt injection through the question, history or corpus; harmful or
age-inappropriate output; PII reaching the provider; provider outage; cost
abuse.

Controls:
- Query screen with six refusal categories plus an academic-context exception (`services/safety.py:25-106`); injection patterns refuse before retrieval.
- Corpus-side: instruction-override sentences removed at ingest; `<evidence>` and `<user_question>` delimiters sanitized; the system prompt declares both as quoted data and forbids disclosing its own instructions (`services/safety.py:139-207`; `services/tutor.py:104-122,132-141`).
- Pasted phone/email/NID redacted before the provider call (`services/pii.py:29`; `services/tutor.py:160-198`).
- Coverage gate refuses questions the corpus does not support (`services/tutor.py:272-388`).
- Rate limit 30 requests/minute per user (`config.py:229`); output-token cap (`config.py:86`); optional fallback provider and circuit breaker (`providers/__init__.py:77-125`).
- Per-user monthly AI budget enforced reserve-before-call (`services/costs.py:143-158`); a production boot with a billable provider and budget 0 is refused (`main.py:380-405`; `tests/test_qa_boot_guards.py`, FIXED 52efb6b).
- The bundled synthetic sample corpus cannot serve a billable production tutor: boot refuses with `NCTB_CORPUS_DIR` empty or unusable unless the explicit offline-demo opt-in is set (`main.py:352-377`, `initialize/dependencies.py:265-285`; `tests/test_qa_boot_guards.py`, FIXED 58a682a).
- Red-team gate: 23/23 probes refused with no leak markers (SEC-20, E-SEC-20-1); `tests/test_injection_screen.py`, `tests/test_injection_guard.py`, `tests/test_chat_route_safety.py`, `tests/test_safety_v2.py`.

Partial / open:
- Tutor answers are not output-screened, only teacher-path outputs are (F-LLM-2); no hate or bullying category (F-LLM-1); text inside an image is not declared untrusted data (F-LLM-3).
- Live-model behaviour is UNVERIFIED-LIVE; all injection evidence is hermetic.

### 4.3 Uploads (chat images)

Threats: malicious file upload; metadata (GPS, device) leakage; an image
carrying smuggled instructions into the model.

Controls:
- The only upload path is an inline image on a chat turn; there is no multipart upload endpoint (SEC-12, E-SEC-12-1).
- Mime allow-list (png/jpeg/webp), strict base64 decode, 1.5 MB cap, and magic-byte sniffing that rejects a declared/actual mismatch (`routers/common.py:218-221,242-300`).
- Server-side Pillow re-encode strips EXIF/GPS and bounds pixel count before forwarding (`providers/image_safety.py:47,98-152`).
- The mock provider answers with an explicit cannot-see-images refusal rather than a fabricated description (`routers/tutor.py:624,735`).
- `tests/test_chat_image_validation.py` and `tests/test_image_metadata_stripping.py` passed (25 assertions, E-LLM-12).

Partial / open:
- The attached image is not named in the prompt's data-only rules (F-LLM-3).
- Real-image vision behaviour is UNVERIFIED-LIVE and the quality gate lives on a separate branch (`providers/image_safety.py:25-30`).

### 4.4 Parent-child linking

Threats: invite-code guessing; a leaked code staying redeemable; a guardian
attaching to the wrong child; unattributed linking during incident review.

Controls:
- The code is 64-bit, stored hashed, single-use, atomic under redeem, TTL bounded, and the redeem endpoint is limited to 10/min per IP (`routers/parent.py:156,330`; `config.py:253`; SEC-06, E-SEC-06-1).
- Linked guardians see progress only, never chat transcripts (audit PRIV inventory: parent access is "report only").

Partial / open:
- Create and redeem are not written to the audit trail, and a code cannot be revoked before its TTL (F-SEC-5).

### 4.5 Impersonation (support sessions)

Threats: abuse of a support session; confusion between an impersonated and a
real session; persistence after sign-out.

Controls:
- Impersonation tokens are 15-minute, `jti`-bound, audited, and the UI shows an impersonation banner; sensitive routes refuse impersonated tokens via `forbid_impersonation` (`routers/auth.py:510-511,781-819`; `routers/deps.py:117-140`).
- Renewal refuses impersonated tokens (`routers/auth.py:510-511`).

Partial / open:
- `POST /auth/logout` answers 204 for an impersonation token without revoking it — proven by probe (token still valid afterwards); the exit endpoint does revoke (F-SEC-6, E-SEC-07-1).

### 4.6 Tenancy and authorization

Threats: horizontal access across schools; role escalation; sequential-id
enumeration.

Controls:
- Role guards with school scoping (`routers/deps.py:243,354-376,379-396`), a last-admin guard (`routers/admin.py:113`), and no self-escalation path (SEC-04, E-SEC-04-1).
- 87 authorization/tenancy tests plus the OpenAPI auth matrix passed (E-SEC-04-1); `tests/test_school_tenancy_isolation.py`, `tests/test_openapi_auth_matrix.py`, `tests/test_school_admin_edges.py`.
- Privileged actions are audited append-only with redacted detail (SEC-15, E-SEC-15-1).

Partial / open:
- Cross-tenant requests answer 403 `other_school` for existing objects but 404 for absent ones, an existence oracle across tenants (F-SEC-4).
- `/auth/join-school` — unauthenticated and creating staff accounts — is not rate-limited (F-SEC-7).

### 4.7 Exports, erasure and retention

Threats: data exfiltration through export; one account exhausting resources;
destructive maintenance misuse; incomplete erasure.

Controls:
- Self-service export and erasure with password re-authentication (`routers/users.py:82-151,152-157`); erasure cascade verified by 44 targeted tests (PRIV-03, E-PRIV-3).
- The export now carries the graded-answer record, the AI-memory preferences and each attempt's `quiz_json` (`services/gdpr.py:97,140,174,490-552`; `tests/test_qa_export.py`, FIXED 62fa487).
- Purge windows documented and enforced (180/180/730/365 days) with dry-run and admin gate (PRIV-04, E-PRIV-3).
- School-level aggregate export enforces a k-anonymity floor of 5 (PRIV-05, E-PRIV-3); `tests/test_account_deletion.py`, `tests/test_delete_cascade_v2.py`, `tests/test_export_completeness.py`.
- The analytics trail stores booleans/numbers and short machine-code strings only: prop values that look like free text, Bangla text or PII (phone/email/NID shapes) are dropped before the row is written (`routers/common.py:113-166`; `tests/test_qa_event_prop_values.py`, FIXED c56dce8).
- Sentry events pass through the same redactor every log line uses before leaving the process (`initialize/observability.py:25-47`; `tests/test_qa_sentry_scrub.py`, FIXED fcb7e13).

Partial / open:
- `/users/me/export` and `/admin/reports/aggregate` are unrated (F-SEC-8).
- The retention purge is neither confirmation-gated nor rate-limited (F-SEC-10).
- Sentry has no user-facing consent gate; the web client still initialises without a scrubber (F-PRIV-7, web part open; the API `before_send` hook above is the API half).

## 5. Out of scope / not verified here

- Live-model injection resistance: hermetic red-team only (SEC-20 note). ZAP baseline not run; semgrep not installed (SEC-18).
- TLS protocol/cipher posture: Caddy defaults, nothing pinned in `deploy/` (SEC-14 sub-item UNVERIFIED).
- Postgres-only concurrency paths: two tests skip without `BGPT_TEST_DATABASE_URL` (SEC report).
- Static-host runtime headers (Caddy/nginx) were read, not served; only the API's own headers were observed live (SEC-10).
- Android/Capacitor network configuration and browser-side CSRF/clickjacking in a real browser — not checked in the audit (bearer tokens, no cookies, so CSRF is N/A by design: SEC-09, E-SEC-09-1).
- Legal conclusions: none. Privacy and child-data obligations require legal review (`docs/ai/risk-register.md` row 4; PRIV-10).
