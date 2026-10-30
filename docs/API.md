# API Reference — Bangla GPT APP

Base URL (local): `http://127.0.0.1:8000` · Interactive docs: `/docs` (OpenAPI at `/openapi.json`)
All authenticated endpoints expect `Authorization: Bearer <JWT>` from `POST /auth/login`.
Errors use `{"detail": "..."}` with correct semantics: 401 unauthenticated · 403 forbidden ·
404 not found · 409 conflict · 413 too large · 422 validation · 429 rate-limited · 503 not ready.

This file is hand-written and covers the core surface below plus the streaming
and pagination contracts. The **full** surface is the served schema at
`/openapi.json` (the authority for tooling and tests); `docs/route_baseline.md`
is a dated inventory snapshot that can lag it. Operations this file does not
describe (short tests, bulk assignments, question papers, schools,
notifications, KG re-teach, admin center, status page, …) exist and are
documented there — never assume the absence of a section here means the
absence of an operation.

## Health & observability

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | — | Liveness only (`{"status":"ok"}`); version/env live on the authenticated `GET /admin/system/info` |
| GET | `/live` | — | Process alive |
| GET | `/ready` | — | DB reachable AND provider configured; else 503 |
| GET | `/metrics` | open in dev; `Bearer $METRICS_TOKEN` in production | Prometheus exposition (`bgpt_http_requests_total`, `bgpt_http_request_duration_seconds`, …) |

Every non-preflight response carries `X-Request-ID` (echoed if supplied, otherwise generated); CORS preflight responses are answered before the request-id middleware runs.

## Auth

| Method | Path | Auth | Body / notes |
|---|---|---|---|
| POST | `/auth/register` | - | `{email, password(min 8), name, role: student\|teacher\|parent, class_level?, guardian_consent?}` - `class_level` AND `guardian_consent: true` required for students; admin role cannot be self-registered. Returns 201 `{user_id, role, profile_id}` |
| POST | `/auth/login` | - | `{email, password}` → `{access_token, must_change_password}` (HS256 JWT: `sub`, `role`, `exp`). MFA-enabled accounts get HTTP 202 + `token_type: "mfa"` step-up token (5 min, rejected by normal routes) — complete with `/auth/mfa/challenge` |
| POST | `/auth/forgot` | - | `{email}` → always `202 {"status":"accepted"}` (anti-enumeration). Emails a single-use reset token (30 min); token stored only as SHA-256 hash. Dev fallback logs the token to console when SMTP is off and ENV≠production |
| POST | `/auth/reset` | - | `{token, new_password(min 8)}` → fresh `{access_token}`; single-use + expiry enforced |
| POST | `/auth/verify-email` | - | `{token}` → marks the account verified, returns `{access_token}`. Single-use, 24 h expiry |
| POST | `/auth/resend-verification` | — (optional Bearer) | `{email?}` → always `202 {"status":"accepted"}` (anti-enumeration). Works WITHOUT a session (login issues no token for unverified accounts); an attached session wins over the body email |
| POST | `/auth/change-password` | Bearer | `{current_password, new_password}` → rotates password and clears the forced-change flag |
| POST | `/auth/mfa/enroll` | Bearer | Returns unstored `{secret, otpauth_uri}` for the authenticator app; nothing is enabled yet. Refused (403 `impersonation_forbidden`) from an impersonated session |
| POST | `/auth/mfa/verify` | Bearer | `{secret, code, password}` → proves possession and stores the secret (= MFA enabled). The current password is required (401 `bad_current_password`), because binding a factor outlives the token that binds it. 409 if already enabled; 403 from an impersonated session |
| POST | `/auth/mfa/disable` | Bearer | `{password}` → clears the secret (= disabled). 409 if not enabled; 403 from an impersonated session |
| POST | `/auth/mfa/challenge` | - | `{mfa_token, code}` → real bearer `{access_token}`. 401 on wrong/expired token or code; the step-up token is burned atomically, and one without a `jti` is refused rather than accepted un-burned |
| GET | `/users/me` | any | Profile of the caller: `{user_id, email, role, profile_id, name, class_level}` |
| GET | `/users/me/export` | any | GDPR-style data export: account, profile, quiz attempts, parent links (`Content-Disposition: attachment`) |
| DELETE | `/users/me` | any | Self-service account deletion (GDPR-style). **Requires the current password in the body** (`{"password": ...}`, F-142 — a bearer token alone must never erase an account irreversibly; missing/wrong password → 401 `bad_current_password`). Removes profile, quiz attempts + answer logs, parent links, bulk-assignment recipients. Last remaining admin is refused (409); an impersonated session is refused (403 `impersonation_forbidden`); the erasure writes an `account_erase` audit row. Returns 204 |
| POST | `/users/me/sessions/revoke` | any | Sign out everywhere: stamps the token epoch so every outstanding session token fails its next request. Returns 204 |
| POST | `/auth/logout` | any | End THIS session: parks the presented token's jti in the fail-closed revocation store for its remaining life. Returns 204 |

Rate limits (per client IP unless noted): `/auth/login`, `/auth/forgot`,
`/auth/reset`, `/auth/register`, `/auth/resend-verification`,
`/auth/verify-email` 10/min, `/auth/mfa/challenge` 5/min and `/tutor/ask`
30/min by default — configurable via `RATE_LIMIT_*_PER_MINUTE` and the
`rate_limit_rules` table (`config.py`). The authenticated MFA legs
(`/auth/mfa/enroll|verify|disable`) are limited per user (20/min) rather than
per IP. Backend is per-process memory or shared Redis
(`RATE_LIMIT_BACKEND=redis`; answers 503 on protected routes when Redis is down
and `RATE_LIMIT_FAIL_OPEN=false`).

When `must_change_password=true` (production admin bootstrap), every endpoint
except health/metrics, `/users/me*` and `/auth/change-password` returns 403
until the password is rotated.

## Tutor

| Method | Path | Auth | Body / notes |
|---|---|---|---|
| POST | `/tutor/ask` | any | `{question(3..1000), class_level(1-12), subject?}` → `{answer, grounded, sources[]}`. Refuses (`grounded=false`) without retrieval evidence — hallucination guard |
| POST | `/tutor/conversations/{conversation_id}/messages/stream` | owner | SSE twin of `POST .../messages` — see "Streaming (SSE)" below |

## Streaming (SSE)

`POST /tutor/conversations/{conversation_id}/messages/stream` takes the same
body as the JSON send (`{message(3..1000), class_level?, subject?, chapter?,
reteach?, low_data?, strategy?, image?}`) and answers
`Content-Type: text/event-stream`. Conversation ownership is checked exactly as
for the JSON route (404 for a foreign id).

Frames, in order (blank line terminated, `data:` is JSON):

| Event | Payload | When |
|---|---|---|
| `token` | `{"text": "..."}` | One per provider chunk; concatenate. The vision-unsupported refusal arrives as a single token |
| `: ping` | — | SSE comment every 15 s of inactivity (retrieval and time-to-first-token can take tens of seconds). Ignore comment lines |
| `done` | `{user_message_id, message_id, answer, grounded, sources[], refused_reason, citation_verified, confidence}` | Turn finished and persisted; `confidence` is recomputed from the cited evidence (`[0,1]`) |
| `error` | `{"code": "llm_unavailable"}` | Provider failed mid-turn (or produced nothing): the user turn stays persisted, **no** assistant message is created, and no `done` follows |

Client contract: **the absence of `done` is a failure**, not an empty answer.
The shipped web client treats a stream that ends without a terminal frame as a
502 and drops any partial text. A `reset` frame is reserved for fallback
restarts; the current server does not emit one.

Behaviour notes:

- Persistence: the user turn is committed before streaming starts; the
  assistant reply is written when the stream completes.
- Abort: closing the connection cancels the provider work and records the
  partial text in the usage ledger. A client-side `AbortController` does the
  same (the web client's `postStream` uses one).
- Auth: `EventSource` cannot set an `Authorization` header, so integrators
  must use `fetch` and read the body stream — which is what the web client
  does.
- Rate limits: the request counts against every matching rule — `/tutor`
  (60/min per IP) **and** `/tutor/conversations` (30/min per user by default;
  unauthenticated callers fall back to their IP).
- Proxies: the response carries `Cache-Control: no-cache` and
  `X-Accel-Buffering: no`, which nginx honours per response. A proxy that
  ignores the header still needs buffering disabled for this path: the bundled
  nginx sets `proxy_buffering off` and a 3600 s read timeout
  (`apps/web/deploy/nginx.conf`), and the bundled Caddy already disables
  response buffering. Any proxy you add must do the same, or tokens arrive in
  one blob or the stream is cut mid-answer.

## Pagination

Admin list endpoints share one offset/limit contract — no cursor, no
`Link` header. `limit` is 1–200 (default 50), `offset` is ≥ 0 (default 0);
`total` is the count **after** the filters and is the number to page over:

| Endpoint | Query | Response |
|---|---|---|
| `GET /admin/users` | `q` (email substring), `role`, `limit`, `offset` | `{total, items: [{id, email, role, created_at}]}` |
| `GET /admin/audit` | `action`, `limit`, `offset` | `{rows: [{id, created_at, actor_user_id, actor_role, action, target, detail}], total, limit, offset}` — newest first |
| `GET /admin/feedback` | `status` (`open`\|`all`), `limit`, `offset` | `{rows: [...], total, open_count, limit, offset}` — oldest first |

Page with `offset += limit` until `offset >= total`; a page may be shorter than
`limit` while `total` still grows (inserts are not snapshot-isolated). Keep
`limit` at the 200 maximum only when the caller can handle the payload —
`/admin/audit` rows carry an arbitrary `detail` object.

Two list endpoints are **not** paginated by design: `GET
/tutor/conversations/{conversation_id}/messages` returns the newest `limit`
messages (default 200, max 500) in chronological order — a payload cap, not a
pager — and `GET /tutor/messages/search` always returns the newest 25 hits.

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
