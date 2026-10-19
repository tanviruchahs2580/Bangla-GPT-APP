# Data inventory and flow map (AUD-B-27)

Traced to code on 2026-10-19 at branch `chore/enterprise-hardening-20261018`.
Companion to `docs/data_minimization.md` (field-level verdicts, retention sweep,
honest gaps); this document adds the **flow map** the audit register found
missing and restates the inventory with the schema/code anchor for each store.

Method: every table below is a `__tablename__` in
`apps/api/src/bangla_gpt_api/db/models.py` (the drift test
`apps/api/tests/test_b2_docs_compliance.py::test_every_table_appears_in_the_inventory`
fails when a new table is not added here). Flow arrows are read from the
routers/services named in the last column.

## 1. Stores (inventory)

Classification: **IDENTITY** (directly identifies a person), **CONTENT**
(user-generated or user-linked content), **EVIDENCE** (retained on purpose),
**OPERATIONAL** (no user content), **SECRET** (credential material).

| Table | Class | What it holds | Purpose / minimization | Anchored at |
|---|---|---|---|---|
| `users` | IDENTITY+SECRET | email, Argon2id `password_hash`, role, flags, school_id | login + authorization; no other identity attributes | `db/models.py:User`; `auth/security.py` |
| `students` | IDENTITY | name, class_level, guardian consent version/at/ip | addressing + curriculum fit; consent evidence retained by policy | `db/models.py:Student`; `routers/auth.py:register` |
| `teachers`, `parents` | IDENTITY | name; parent `phone_enc` (Fernet when `PII_ENC_KEY` set) | product function; phone encrypted, never logged/exported | `db/models.py`; `security.py:encrypt_pii` |
| `parent_student_links` | IDENTITY | parent↔student link | guardian access model | `routers/parent.py` |
| `conversations`, `chat_messages` | CONTENT | tutor turns (user + assistant, citations) | multi-turn tutoring; swept after `chat_retention_days` (180) | `routers/tutor.py`; `services/retention.py` |
| `quiz_attempts`, `answer_log` | CONTENT | quiz items/answers/scores | pedagogy (weak-chapter detection) | `routers/learn.py`, `services/quiz.py` |
| `feedback` | CONTENT | rating + optional comment; message FK nulled on chat sweep | product improvement | `services/retention.py:_detach_feedback_from_messages` |
| `revision_queue`, `chapter_progress`, `daily_activity`, `concept_mastery`, `student_abilities`, `saved_notes`, `notifications` | CONTENT | learning state | study features | `db/models.py` |
| `classrooms`, `class_students`, `class_teachers`, `student_invites`, `schools`, `school_invites` | IDENTITY | roster/tenancy anchors | tenancy isolation + classroom ops | `routers/school.py`, `routers/deps.py` |
| `chapter_contents`, `question_papers`, `short_tests`, `assignments`, `question_bank`, `practice_items`, `concepts`, `concept_prerequisites`, `teacher_documents`, `support_plans` | OPERATIONAL | school-authored content/assignments | product content, not personal data | `routers/teacher*.py`, `routers/school.py` |
| `password_resets`, `email_verifications`, `parent_invites` | SECRET | SHA-256 token hashes only, single-use | auth flows; expired + 30-day grace sweep | `auth/single_use.py`; `services/retention.py` |
| `audit_log` | EVIDENCE | five privileged actions; detail = ids/counts | accountability; append-only by convention | `security.py:write_audit`; `routers/admin.py` |
| `analytics_events` | OPERATIONAL | event name + sanitized primitive props (PII-flavoured keys dropped, strings capped at 40 chars) | product metrics; swept like chat | `routers/tutor.py:record_event`; `routers/common.py:_sanitize_event_props`; `services/retention.py` |
| `job_runs`, `ai_jobs`, `ai_usage` | OPERATIONAL | scheduling + token/cost counters | ops; no message content | `jobs.py`, `services/costs.py` |
| `email_bounces` | IDENTITY | bounced address + reason | deliverability hygiene | `services/mailer.py` |

## 2. Flow map

```text
                          ┌─────────────────────────── third parties ───────────────────────────┐
                          │  Google Gemini (LLM)   ·  SMTP provider (operator-configured host) │
                          └───────▲───────────────────────────────▲─────────────────────────────┘
                                  │ F3                            │ F9
 [student browser] ──F1 register──┼──> users / students / parents │
        │          ──F2 login────┼──> JWT (STATELESS) + deny-list cache (jti only)
        │                         │
        ├──F3 tutor chat ─────────┴──> conversations / chat_messages (DB)
        ├──F4 quiz / practice ───────> quiz_attempts / answer_log / progress tables
        ├──F5 events (name only) ────> analytics_events
        └──F6 exports ───────────────> /users/me/export (JSON, to the user)
 [teacher/school] ──F7 content ──────> chapter_contents, assignments, question_papers
 [admin]         ──F8 govt export ───> aggregate (k≥5 cells) + govt_export audit row
 [nightly job]   ──F10 sweep ────────> deletes per retention policy; counts-only audit row
 [pgBackRest]    ──F11 backups ──────> WAL + nightly full (encrypted repo; PII key excluded)
```

### F1 Registration and guardian consent

`POST /auth/register` (`routers/auth.py`) → `users` (email, Argon2id hash) +
`students`/`teachers`/`parents` profile; student rows carry the guardian
consent version/at/ip. Password candidates are checked against the offline
common/breached lists before hashing (AUD-B-06). If SMTP is configured, a
verification token (hash stored) is mailed (F9).

### F2 Session

Login verifies Argon2id, then mints a stateless HS256 JWT (60-min) carrying
`sub`/`role`/`jti`/`iat`. No session table. Logout and impersonation write
only the `jti` into the shared cache deny-list; password change rotates
`sessions_invalidated_at`.

### F3 Tutor chat → LLM provider (the third-party flow)

`routers/tutor.py` → `services/tutor.py:build_evidence_prompt_with_selection`:
the provider payload is **(a)** retrieved NCTB passages, **(b)** the redacted
prior conversation, **(c)** the redacted question. Student-pasted
phone/email/NID-shaped strings are replaced at this egress boundary
(`services/pii.py:redact_pii`, metered per kind); account identifiers
(name/email/user id) are never added to the prompt. Optional chat images are
validated (mime allowlist, size, magic bytes) and forwarded inline.
Provider request/response bodies are not logged on our side
(`docs/data_minimization.md`; `providers/gemini.py` sends
`{"contents":[{"parts":[{"text": …}]}]}`).

### F4–F7 Product data in the DB

Quiz/practice answers and progress land in the tables above; school-authored
content is separate from user data. Events: `POST /events` logs the event
**name** and prop **keys** only, and persists a sanitized copy (PII-flavoured
keys dropped, primitives only, strings capped at 40 chars)
(`routers/tutor.py:record_event`, `routers/common.py:_sanitize_event_props`).
Note: `docs/data_minimization.md`'s "prop values are never persisted" line is
stale against this newer sanitize-and-persist path; the behavior described
here is the code's.

### F8 Government/authority aggregate export

`GET /admin/reports/aggregate` (`routers/school.py`) reads aggregates only,
suppresses cells below `min_cell` (floor 5), PII-scans the serialized output,
and writes a `govt_export` audit row. Review notes: `docs/security/aggregate-export-anonymity.md`.

### F9 Email (SMTP)

`services/mailer.py` sends verification and password-reset messages via the
operator-configured SMTP host. The only data sent is the recipient address and
the token/message body. Bounces are recorded in `email_bounces`.

### F10 Retention sweep

`services/retention.py` (admin endpoint + nightly arq job) deletes old
conversations/messages, expired tokens beyond the 30-day grace, used invites,
and old analytics events; report + audit row carry counts only.

### F11 Backups

`deploy/postgres/pgbackrest.conf` archives WAL + nightly fulls to an
encrypted repository; `PII_ENC_KEY` is deliberately excluded
(`docs/backup_dr.md`). Consequence: `parents.phone_enc` is unreadable from a
backup alone, while other rows appear as in the DB.

## 3. Processors and outbound endpoints

| Processor | Data it receives | Where configured | Doc |
|---|---|---|---|
| Google Gemini (or OpenAI-compatible, or `mock`) | redacted question + passages + conversation; optional inline image | `config.py:llm_provider`; `providers/*` | `docs/dpa_template.md` |
| SMTP provider (operator choice) | recipient address, transactional body | `config.py:smtp_*` | `docs/dpa_template.md` |
| Redis (self-hosted) | jti deny-list entries, rate-limit counters | `docker-compose.yml` | — |
| PostgreSQL (self-hosted) | all tables above | `docker-compose.yml` | `docs/backup_dr.md` |

No third-party analytics, CDN or font host is loaded by the SPA (fonts are
self-hosted — verified in `apps/web`).

## Open items (honest)

- Account-dormancy purge and the consent-evidence expiry horizon remain
  policy-on-paper (same gaps as `docs/data_minimization.md`).
- `email_bounces` has no retention sweep.
- Whether any processor needs a written DPA under Bangladesh law is a counsel
  question, tracked in `docs/compliance/bangladesh-law-mapping.md`.
