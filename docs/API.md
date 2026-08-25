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
| POST | `/auth/register` | — | `{email, password(min 8), name, role: student\|teacher\|parent, class_level?}` — `class_level` required for students; admin role cannot be self-registered. Returns 201 `{user_id, role, profile_id}` |
| POST | `/auth/login` | — | `{email, password}` → `{access_token}` (HS256 JWT: `sub`, `role`, `exp`) |
| GET | `/users/me` | any | Profile of the caller: `{user_id, email, role, profile_id, name, class_level}` |
| DELETE | `/users/me` | any | Self-service account deletion (GDPR-style). Removes profile, quiz attempts + answer logs, parent links. Last remaining admin is refused (409). Returns 204 |

Rate limits (per IP, per process): `/auth/login` 10/min, `/tutor/ask` 30/min (configurable).

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
