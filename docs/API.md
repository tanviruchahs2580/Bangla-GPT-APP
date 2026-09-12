# API Reference — Bangla GPT APP

Base URL (local): `http://127.0.0.1:8000` · Interactive docs: `/docs` (OpenAPI at `/openapi.json`)
All authenticated endpoints expect `Authorization: Bearer <JWT>` from `POST /auth/login`.
Errors use `{"detail": "..."}` with correct semantics: 401 unauthenticated · 403 forbidden ·
404 not found · 409 conflict · 413 too large · 422 validation · 429 rate-limited · 503 not ready.

## Health & observability

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | — | Liveness + app/version/env |
| GET | `/live` | — | Process alive |
| GET | `/ready` | — | DB reachable AND provider configured; else 503 |
| GET | `/metrics` | — | Prometheus exposition (`bgpt_http_requests_total`, `bgpt_http_request_duration_seconds`, …) |

Every response carries `X-Request-ID` (echoed if supplied, otherwise generated).

## Auth

| Method | Path | Auth | Body / notes |
|---|---|---|---|
| POST | `/auth/register` | - | `{email, password(min 8), name, role: student\|teacher\|parent, class_level?, guardian_consent?}` - `class_level` AND `guardian_consent: true` required for students; admin role cannot be self-registered. Returns 201 `{user_id, role, profile_id}` |
| POST | `/auth/login` | - | `{email, password}` → `{access_token, must_change_password}` (HS256 JWT: `sub`, `role`, `exp`). MFA-enabled accounts get HTTP 202 + `token_type: "mfa"` step-up token (5 min, rejected by normal routes) — complete with `/auth/mfa/challenge` |
| POST | `/auth/forgot` | - | `{email}` → always `202 {"status":"accepted"}` (anti-enumeration). Emails a single-use reset token (30 min); token stored only as SHA-256 hash. Dev fallback logs the token to console when SMTP is off and ENV≠production |
| POST | `/auth/reset` | - | `{token, new_password(min 8)}` → fresh `{access_token}`; single-use + expiry enforced |
| POST | `/auth/change-password` | Bearer | `{current_password, new_password}` → rotates password and clears the forced-change flag |
| POST | `/auth/mfa/enroll` | Bearer | Returns unstored `{secret, otpauth_uri}` for the authenticator app; nothing is enabled yet |
| POST | `/auth/mfa/verify` | Bearer | `{secret, code}` → proves possession and stores the secret (= MFA enabled). 409 if already enabled |
| POST | `/auth/mfa/disable` | Bearer | `{password}` → clears the secret (= disabled). 409 if not enabled |
| POST | `/auth/mfa/challenge` | - | `{mfa_token, code}` → real bearer `{access_token}`. 401 on wrong/expired token or code |
| GET | `/users/me` | any | Profile of the caller: `{user_id, email, role, profile_id, name, class_level}` |
| GET | `/users/me/export` | any | GDPR-style data export: account, profile, quiz attempts, parent links (`Content-Disposition: attachment`) |
| DELETE | `/users/me` | any | Self-service account deletion (GDPR-style). Removes profile, quiz attempts + answer logs, parent links. Last remaining admin is refused (409). Returns 204 |

Rate limits (per client IP): `/auth/login`, `/auth/forgot`, `/auth/reset`
10/min and `/tutor/ask` 30/min by default — configurable via
`RATE_LIMIT_*_PER_MINUTE`. Backend is per-process memory or shared Redis
(`RATE_LIMIT_BACKEND=redis`; answers 503 on protected routes when Redis is down
and `RATE_LIMIT_FAIL_OPEN=false`).

When `must_change_password=true` (production admin bootstrap), every endpoint
except health/metrics, `/users/me*` and `/auth/change-password` returns 403
until the password is rotated.

## Tutor

| Method | Path | Auth | Body / notes |
|---|---|---|---|
| POST | `/tutor/ask` | any | `{question(3..1000), class_level(1-12), subject?}` → `{answer, grounded, sources[]}`. Refuses (`grounded=false`) without retrieval evidence — hallucination guard |

## Students & quizzes

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/students/{id}` | owner/teacher/admin | `{id, name, class_level}` |
| GET | `/students/{id}/progress` | owner/teacher/admin | Chapter accuracy (<60% flagged weak), attempts, avg score |
| POST | `/quizzes` | owner/teacher | `{student_id, class_level?, subject?, num_questions(1-10)}` → questions WITHOUT answer keys |
| POST | `/quizzes/{attempt_id}/submit` | owner/teacher | `{answers: int[]}` → score + review. Double-submit → 400; answers never exposed before grading |

## Teacher

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/teacher/students?class_level=` | teacher/admin | Roster with per-student attempts/avg |
| GET | `/teacher/classes/{level}/analytics` | teacher/admin | Chapter accuracy table + weak chapters + student detail |

## Parent

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/parents/link` | parent | `{student_id}` → 201; duplicate 409; unknown student 404 |
| GET | `/parents/me/children` | parent | Linked children briefs |
| GET | `/parents/me/children/{student_id}/progress` | parent (linked) | Same shape as student progress; 404 when not linked |

## Admin

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/admin/users` | admin | All users |
| PATCH | `/admin/users/{id}/role` | admin | Role change; demoting the last admin → 409 |
| GET | `/admin/analytics/overview` | admin | Platform totals incl. parents count |

## Configuration (env)

See `.env.example`: `ENV`, `LLM_PROVIDER=mock`, `DATABASE_URL`, `JWT_SECRET`,
`JWT_EXPIRE_MINUTES`, `RATE_LIMIT_LOGIN_PER_MINUTE`, `RATE_LIMIT_TUTOR_PER_MINUTE`,
`MAX_BODY_BYTES`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`. Real `.env` files are never committed.
