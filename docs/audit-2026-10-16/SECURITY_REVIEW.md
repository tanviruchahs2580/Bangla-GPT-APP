# SECURITY REVIEW — Bangla GPT APP (2026-10-16)

Scope: source review + local execution + the isolated local stack. No probe was
ever aimed at production, and no destructive or intrusive test was run. Remote
provider settings were not accessible, so anything about them is marked
`NOT VERIFIED`.

Threat context: an education product for Bangladesh with minors as primary
users. The assets that matter most are student records (progress, quiz history,
tutor conversations), the parent↔child link, teacher/school tenancy, and the
AI spend/abuse surface.

## 1. Threat model (abbreviated)

| Actor | Goal | Relevant controls reviewed |
|---|---|---|
| Unauthenticated internet | enumerate accounts, brute-force codes/credentials, abuse costly endpoints | rate limiting, invite entropy, register/login/MFA-challenge limits, body-size cap |
| Authenticated student | read another student's data; bypass consent gates | `authorize_student_access`, per-object ownership, parent link consent gate |
| Authenticated teacher | reach another school's roster/content or another teacher's artifacts | school tenancy helpers (`_tenant_school_id`, `_assert_room_in_school`), `created_by` filters |
| Malicious/compromised school staff | escalate to admin, exfiltrate via exports | role allowlists, last-admin guard, impersonation audit + revocation |
| Prompt attacker (student text or retrieved corpus) | jailbreak, extract system prompt, exfiltrate data, poison content | delimiter hardening, ingestion-time injection stripping, refusal tests |
| Cost abuser | burn LLM budget | per-user budget ledger, per-route rate limits, provider circuit breaker |
| Supply-chain attacker | inject code via dependency or CI | SHA-pinned actions, hash-pinned installs, gitleaks, provenance attestations |

## 2. What was verified as solid

**Authentication and session handling**

- Argon2id password hashing with OWASP-recommended parameters (`auth/security.py`); TOTP MFA is implemented with a ±1 step window and its own 5/min IP limit (`routers/auth.py`, `middleware_stack.py:28`).
- `get_current_user` (`routers/deps.py:139`) rejects MFA step-up tokens as API credentials (`:168-169`), enforces a token epoch so logout/password change invalidates older tokens, and fails **closed** (503) when the impersonation revocation store is unavailable (`:159-165`) rather than allowing a revoked session through.
- The forced-password-change gate is exempted only for a fixed path list (`deps.py:123-133`).
- Registration clamps the role to student/teacher/parent (`schemas.py:167`) — verified by `test_admin_hardening.py` (register cannot create an admin).
- Guardian consent is enforced at registration: a student signup without `guardian_consent` is refused (`{"code":"guardian_consent_required"}`) — confirmed live against the running API, not just in tests.
- Account deletion guards the last admin (`test_account_deletion.py`).

**Authorization and tenancy**

- Every operation's public/protected status is asserted against an explicit allowlist (`PUBLIC_OPERATIONS` + `test_openapi_auth_matrix.py`), so adding an unauthenticated endpoint fails the suite; `test_openapi_contract.py` requires 401/403 to be documented on protected operations.
- Object-level access goes through `authorize_student_access` / `_assert_student_in_school` / `_assert_room_in_school` (`deps.py:282-320`) with dedicated isolation tests (`test_auth_teacher.py`, `test_school_tenancy_isolation.py`, `test_school_routes_coverage.py`).
- Admin-only surfaces are covered by `test_admin_center.py`, `test_metrics_auth.py`, `test_support_ops.py`, `test_security_v2.py` (including refusal to impersonate an admin).
- Impersonation is audited, expires, and is revocable; the exit endpoint only ends the caller's own session.

**Secrets and exposure**

- No hard-coded credential, private key, or provider key was found in the working tree (patterns: `sk-…`, `AIza…`, `BEGIN … PRIVATE KEY`, assignment-style literals; every non-test hit is an env reference or a local-only smoke default).
- Only `.env.example` and `.env.production.example` are tracked; the real `.env.production.local`, the dev SQLite file and `.vercel/` are git-ignored (`git check-ignore` confirmed for the DB and env file).
- Provider API keys are read server-side only (`config.py`, providers); `/docs`, `/redoc` and `/openapi.json` are disabled in production (`main.py:396-402`), and `/metrics` requires a bearer token in production with a boot-time guard that refuses to start otherwise (`main.py::_validate_metrics`, `routers/system.py:99-115`).
- CI uses `persist-credentials: false`, SHA-pinned actions, a minimal `GITHUB_TOKEN` scope, and gitleaks with artifact upload disabled.

**AI-specific controls**

- Trusted instructions are separated from untrusted text: evidence is wrapped in `<evidence>` and the question in `<user_question>`, delimiter breakouts are escaped (`services/tutor.py:118-128,146-184`), and the system prompt states that both are quoted data (`:90-108`). Ingestion strips injection attempts from corpus text (`services/safety.py:109-178`) and `test_injection_guard.py` proves a poisoned chunk cannot break out.
- Failures do not fabricate: provider errors surface as 502 `llm_unavailable`, unconfigured providers as 503, and the mock provider is refused in production unless explicitly allowed (`main.py:217-238`, `test_production_guards.py`).
- Cost controls: per-user monthly ledger with a 429 `ai_budget_exceeded` at the cap (`services/costs.py:88-103`), a circuit breaker with a single half-open probe (`services/circuit_breaker.py`), and per-user rate limits on every costly route.
- Citations are derived from indexed metadata (`services/tutor.py:294-307`), not invented by the model; the model is never asked to emit chapter/page numbers.

## 3. Findings affecting security

| ID | Severity | Status | Summary |
|---|---|---|---|
| `SEC-007` / `F-04` | P2 | **FIXED** | Parent invite code was 32 bits — the only secret guarding a link onto a child's record. Now 64 bits; old codes still redeem. |
| `SEC-009` / `F-09` | P1 | OPEN | `ChapterContent` has no owner/tenancy column, so `GET/PUT /teacher/content` let any teacher read and extend another school's generated content. Needs a product decision + migration. No student-facing endpoint reads this table. |
| `SEC-008` / `F-11` | P2 | OPEN | CSV roster import performs up to 200 Argon2id hashes per request (bounded and rate-limited at 30/min/user). Correctness fine; quota/CPU risk only. |
| `F-19` | P3 | OPEN | School invite code 50 bits, school code 40 bits (both rate-limited, longer TTLs). Parent invite was the only materially short one. |
| `F-13` | P2 | OPEN | Accessibility gaps (no skip link/`<h1>`, `aria-live` on the whole chat thread, unlabelled inputs). Not a security issue, but it is a user-exclusion issue and is listed here for completeness of the "user-facing risk" picture. |
| `F-12` | P1 (mobile release) | BLOCKED | Android wrapper/assets untracked → release APKs are not reproducible from the repository. Owner action. |

Nothing in this round is a P0. No exploitable authorization bypass, injection
path, secret exposure or cross-tenant *student-data* leak was confirmed.

## 4. Privacy review

- **Data classification present and enforced in code:** student PII (name, class, guardian phone) is Fernet-encrypted at rest for the phone field (`routers/system.py` migration `f9a0b1c2d3e4_audit_log_phone_enc`, `security.py`), conversations are owner-scoped, and the audit log stores events rather than message bodies.
- **Logging discipline:** provider prompts, tokens and private content are not logged; the API logs request ids and error codes. Metrics expose counts, not content (`/metrics` docstring and admin AI-quality endpoints return aggregate counts only — "Counts only, never message content" appears on the admin schema).
- **AI data flow:** conversation history and retrieved chunks are sent to the configured provider only server-side; the mock provider is the default locally and is refused in production unless explicitly allowed. What a *real* provider retains or trains on was **not** verified here — that depends on the account's terms and configuration (`NOT VERIFIED`), and the owner should record it before launch.
- **Children's data:** consent is gated at registration and at parent linking; retention/purge exists (`/admin/maintenance/purge`, `services/retention.py`) and the parent digest reads aggregates only. Jurisdictional obligations (e.g. Bangladesh's data-protection act, app-store child policies) require qualified review — this audit makes no compliance claim.
- **Export/delete:** self-service export and account deletion exist and are tested; deletion cascades to dependent rows (`test_delete_cascade_v2.py`, `test_new_tables_deletion.py`).
- **Audit logs:** privileged actions (role change, impersonation, purge, triage) are recorded without secrets or message content.

## 5. Residual risk and recommendations (in priority order)

1. **Decide `ChapterContent` tenancy** (`F-09`) — the only confirmed cross-tenant read of generated content. Either add `school_id` + scoping with a migration, or document the shared-cache model explicitly and add a test that pins the intended behaviour.
2. **Bind releases to verified commits and immutable artifacts** (`F-10`). A tag currently deploys without CI and pulls a mutable tag instead of the recorded digest. This is the highest-leverage release-integrity fix.
3. **Close the eval-gate/deploy gap** (`F-24`) so a failed AI regression cannot ship behind a green API workflow.
4. **Re-check third-party AI retention/training settings** and record them in the privacy docs before launch (no evidence available here).
5. **Make the eval gate fail closed** if its baseline is missing (`F-20`), and hash-pin the eval-gate install (`F-21`).
6. **Add `apps/web/.dockerignore`** (`F-23`) — a Vercel OIDC token currently sits in the web image's build context.
7. **Bind the compose API port to loopback when unpublished** (`F-22`).
8. **Keep the new negative tests** (rejection readability, preflight budget) alongside the auth matrix so error-path regressions stay caught.

## 6. Explicitly not verified

GitHub branch protection, required status checks, secret scanning/push
protection, environment protection and reviewers; production TLS/HSTS/CSP as
served by the edge; whether the deployed image matches the attested digest;
live provider (Gemini/OpenAI) request/response handling and retention; app-store
child-safety review status; penetration testing of any kind; screen-reader
verification of the auth flows. `NOT VERIFIED — access unavailable`.
