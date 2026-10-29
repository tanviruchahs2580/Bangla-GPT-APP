# Data-Minimization and Data-Inventory Review

Derived table-by-table from `apps/api/src/bangla_gpt_api/db/models.py` (all 42
ORM classes at the time of writing), the retention policy in
`services/retention.py` and the windows in `config.py`. Reviewer:
engineering (self-review), 2026-10-29. **Bangladesh legal review is a human
step and is NOT done here — see [`archive/PROGRESS.md`](archive/PROGRESS.md).**

Legend:
- **Retention**: `sweep=<n>d` = deleted by the retention job after `n` days
  (`services/retention.py`, nightly arq job + `POST /admin/maintenance/purge`);
  `token` = swept `expires_at + 30 days` (`TOKEN_GRACE_DAYS`); `erasure` =
  deleted on `DELETE /users/me` (`services/gdpr.py::erase_account_everything`);
  `unbounded` = no sweep today, lives until erasure (flagged where that is a
  gap).
- **Access**: which role can read the row back through the API; "aggregates"
  means counts/scores without the row's text content.

## 1. Accounts, profiles and enrollment

| Data | Where (table) | Purpose | Retention | Access | Minimization |
| --- | --- | --- | --- | --- | --- |
| Email | `users.email` | Login identity, reset/verification mail, parent digest recipient | erasure | self; admin (`GET /admin/users`) | The only contact channel; no phone/name on the account row. |
| Password | `users.password_hash` | Authentication | erasure | never returned | Argon2id hash only; `sessions_invalidated_at` invalidates tokens on rotation. |
| Role, school_id, flags | `users` (`role`, `school_id`, `must_change_password`, `email_verified`) | Authorization, tenancy, forced password change after invite | erasure | self; admin | No extra attributes stored. |
| MFA secret | `users.totp_secret` | TOTP second factor | erasure | never returned | Stored only after proof of possession at verify; NULL = MFA off. |
| Login lockout state | `users.failed_login_count`, `locked_until` | Brute-force lockout | erasure | never returned | Counters, no attempt log. |
| Student name, class | `students.name`, `students.class_level` | Addressing, class-appropriate content | erasure | self; teacher of the class; linked parent; admin | Single name field; no birth date, address or national ID anywhere in the schema. |
| Learning prefs / AI memory | `students.learning_prefs` (JSON, whitelisted keys `explanation_style`, `subject_focus`), `students.memory_enabled` | Per-student explanation style + memory opt-out | erasure | self (shown and cleared in the UI); exported | Keyed dict, not free text; annotated as dict (no migration needed). |
| Guardian consent | `students.consent_version`, `consent_at`, `consent_ip` | Legal evidence of guardian consent (D20) | erasure (policy horizon on paper only, see gaps) | self; admin | IP kept only as consent evidence, never joined to logs or analytics. `consent_ip` must be validated as an IP by the confirm flow. |
| Teacher name, prefs | `teachers.name`, `teachers.prefs` | Addressing, teacher UI state | erasure | self; admin | Free-form JSON prefs, teacher-authored. |
| Parent name | `parents.name` | Addressing | erasure | self; admin | — |
| Guardian phone | `parents.phone_enc` | Optional contact field | erasure | never returned by any route; never exported | Fernet-encrypted when `PII_ENC_KEY` is set; production boot requires the key (B-04). |
| Parent↔child link | `parent_student_links` | Who may view a child's progress | erasure (both ends) | parent (link owner) | Pair of ids only; no relationship label. |
| School tenancy | `schools.name/code`, `classrooms.class_level/section`, `class_students`, `class_teachers` | Roster and class scoping | erasure | teacher (own classrooms), school_admin, admin | Institutional data, no personal attributes beyond the code. |
| Invites / claim codes | `parent_invites`, `student_invites`, `school_invites` | Single-use linking / account claim codes | `token` (used parent invites; student/staff invites swept on expiry only via erasure today) | self (code returned once at creation) | Only the SHA-256 hash is stored; plaintext returned exactly once. `student_invites.email` holds the address the roster import will activate. |
| Reset / verification tokens | `password_resets`, `email_verifications` | Single-use credentials for reset / email verification | `token` (`expires_at + 30d`) | never returned | SHA-256 hashes only; `used_at` marks consumption. |

## 2. Learning activity

| Data | Where (table) | Purpose | Retention | Access | Minimization |
| --- | --- | --- | --- | --- | --- |
| Conversations | `conversations` (`student_id`, `title`, `last_strategy`) | Multi-turn tutoring and the "আমি বুঝিন" strategy loop | `sweep=chat_retention_days` (default 180) | owner student | Title truncated from the first question; no separate topic model. |
| Chat turns | `chat_messages` (`role`, `content`, `grounded`, `refused_reason`, `sources_json`, `rating`) | The transcript itself + grounding verdict + thumbs rating | `sweep=180d` (messages deleted with their conversation; feedback pointers nulled first) | owner student; admin sees refusal **counts** by reason/class (`GET /admin/safety/refusals`), never content | Content is the child's own text; PII is redacted at the provider egress (`services/tutor.py::build_evidence_prompt`) but the stored turn is raw by design (shown back to the student). |
| Quiz attempts | `quiz_attempts` (`quiz_json`, `total`, `correct`, `score_pct`) | Grading, weak-chapter detection | erasure (unbounded) | student; teacher (class analytics, short tests, assignments); linked parent (progress); admin | Question sets are NCTB corpus content, not user-authored. |
| Graded answers | `answer_log` (`question_text`, `chosen`, `correct_index`, `chapter`, `book`) | Per-question record; feeds concept mastery | `sweep=answer_log_retention_days` (730) | aggregates to teacher/parent dashboards; student via own progress | Content is curriculum text; the row carries no free text authored by the child. |
| Chapter progress | `chapter_progress` (`read_pct`, `completed`, `bookmarked`) | Reader progress per chapter | erasure | self; teacher (roster); linked parent | Counts/booleans only. |
| Daily activity | `daily_activity` (`date`, `questions`, `quizzes`, `minutes`) | Streaks and heatmap | erasure | self; parent | Minute counts are a coarse 1-per-question estimate, no client timing trusted. |
| Revision queue | `revision_queue` (`question`, `options_json`, `ease_factor`, `due_date`) | SM-2-lite spaced repetition | erasure | self | Curriculum questions + scheduling state. |
| Concept mastery / ability | `concept_mastery`, `student_abilities` | Knowledge-graph rollups | erasure | aggregates on teacher/parent/student dashboards | Per-concept counts and Elo-style ability; no free text. |
| Support plans | `support_plans` (`focus_concepts`, `plan`) | Teacher-facing plan for at-risk students | erasure | teacher (author); admin | Rule-generated from weak concepts. |
| Saved notes | `saved_notes` (`title`, `body`, `source`, `source_ref`) | User notes clipped from tutor/chapter | erasure (unbounded) | owner user | User-authored; no sweep today (gap). |
| Notifications | `notifications` (`kind`, `code`, `params`, `link`, `read_at`) | In-app feed | erasure (unbounded) | owner user | `code` is an i18n key resolved client-side; `params` carries ids/counts/safe labels only. |
| Feedback | `feedback` (`rating`, `comment`, `triaged`, `triage_note`) | Thumbs + triage queue | erasure | targeting user opens it via the owner check; admin triage queue (`GET /admin/feedback`), reporter identity withheld beyond user id | Comment is optional, 500 chars. |
| Chapter content | `chapter_contents` (`payload`, `created_by`) | Generated/edited study material per chapter | unbounded (shared artifact) | students/teachers read it as curriculum | Shared, not per-student; `created_by` is nulled at erasure. |

## 3. Teacher/AI-generated artifacts and ledgers

| Data | Where (table) | Purpose | Retention | Access | Minimization |
| --- | --- | --- | --- | --- | --- |
| Teacher documents | `teacher_documents` (`kind`, `payload`, `title`) | Lesson plans, worksheets, answer keys, homework, rubrics | erasure (unbounded) | owner teacher | Payload is the validated generator output. |
| Question papers | `question_papers` (`difficulty`, `chapters`, `questions`, `meta`) | Draft/final exam papers with the teacher review gate | erasure | owner teacher | HIL gate: finalize only after every question is explicitly reviewed. |
| Question bank | `question_bank` (`dedupe_key`, `question_text`, `options`, `source`) | Reviewed question reuse across papers | erasure | teacher who reviewed it | `dedupe_key` is a content hash, not a person. |
| Short tests / assignments | `short_tests`, `assignments`, `assignment_recipients` | Class-wide and selected-group quizzes | erasure | teacher (owner); student sees own attempt | `attempts` JSON is duplicated membership; `assignment_recipients` is the indexable copy. |
| AI jobs | `ai_jobs` (`kind`, `payload`, `result`, `error`) | Async generation job lifecycle | erasure (unbounded) | owner user | `error` capped at 300 chars; job body is the artifact request. |
| AI usage ledger | `ai_usage` (`route`, `model`, `prompt_tokens`, `completion_tokens`, `estimated_cost_usd`) | Budget gate + cost dashboards | `sweep=ai_usage_retention_days` (365) | aggregated by model on the admin AI-quality board (`GET /admin/ai/quality`) | Token counts are planning estimates (`services/costs.py`), never prompts or answers. |
| Analytics events | `analytics_events` (`name`, `role`, `props`) | Product analytics | `sweep=analytics_retention_days` (180) | admin dashboards, aggregated; row keeps `user_id` until erasure nulls it | See the corrected statement below. |
| Audit trail | `audit_log` (`actor_user_id`, `action`, `target`, `detail`) | Append-only privileged-action record | never deleted; attribution nulled at erasure | admin (`GET /admin/audit`) | `detail` holds ids and counts only — never message content, never PII. |
| Job ledger | `job_runs` (`job`, `period_key`, `outcome`) | Idempotency for scheduled jobs | unbounded | ops | Period keys and outcomes only. |
| KG nodes / practice items | `concepts`, `concept_prerequisites`, `practice_items` | Curriculum knowledge graph and adaptive Elo items | unbounded | all readers (curriculum) | No user identifiers; `practice_items` aggregates attempts/correct. |

## 4. The corrected analytics statement (was wrong)

The previous revision of this file said prop **values** "are never persisted".
That was false when written: `POST /events` persisted any primitive string
under any key not on the drop-list, so a client could store free text or a
phone number in the 180-day trail (audit PRIV-02). The fix (commit
`c56dce8`, F-039) added a **value allowlist** on top of the key drop-list in
`routers/common.py::_sanitize_event_props`. What actually persists today:

- `bool` / `int` / `float` values, key names truncated to 40 chars, keys
  matching the PII drop-list removed (unchanged behaviour).
- A string value only when it is a short machine code: ≤40 chars, lowercase
  ASCII letters/digits plus `_.:-`, no spaces, no non-ASCII (Bangla free text
  is dropped), no run of 6+ digits (BD mobile/NID patterns) and no
  `redact_pii` match. **Free text is dropped, not stored.**
- Trade-off: free-text values no longer persist, which includes the web
  client's `chapter_open`/`chapter_read` `subject`/`chapter` values (Bangla
  strings fail the ASCII machine-code shape) — the endpoint contract (202
  accepted) is unchanged. Events whose props are machine codes, booleans or
  numbers (e.g. `report_viewed` role/period, `tutor_question_sent`
  booleans, `quiz_completed` counts, `tutor_feedback` rating) still persist.

## 5. Retention: what the sweep enforces (and what it does not)

`services/retention.py::run_retention_sweep` runs nightly (`jobs
.run_retention_sweep`) and via `POST /admin/maintenance/purge`
(`dry_run=true` produces the compliance evidence report). Counts-only in
both the report and the audit row; deletes are chunked (`DELETE_CHUNK =
5_000`) with a commit per chunk (DB-03).

Swept: conversations + messages (`chat_retention_days`, 180), analytics
events (`analytics_retention_days`, 180), answer log
(`answer_log_retention_days`, 730), AI usage (`ai_usage_retention_days`,
365), password resets / email verifications / used parent invites
(`expires_at + 30d`).

**Not swept today** (live until account erasure or actor deletion):
`quiz_attempts`, `chapter_progress`, `daily_activity`, `revision_queue`,
`concept_mastery`, `student_abilities`, `support_plans`, `saved_notes`,
`notifications`, `feedback`, `teacher_documents`, `question_papers`,
`short_tests`, `assignments`, `question_bank`, `chapter_contents`, `ai_jobs`,
`student_invites`, `school_invites`, `job_runs`. `audit_log` is append-only by
design. `PII_ENC_KEY` is deliberately NOT in backups (docs/backup_dr.md).

## 6. Third-party flows (where data leaves the platform)

| Flow | Code | What leaves | Minimization |
| --- | --- | --- | --- |
| LLM provider (Gemini / OpenAI-compatible) | `services/tutor.py::build_evidence_prompt`, `providers/` | The assembled prompt: system rules, retrieved corpus evidence, up to `chat_history_messages` (8) prior turns, the current question; the image part on vision turns | Phone/email/NID patterns are redacted from question **and** history before egress (`redact_pii`, metered per kind); evidence/history are delimiter-sanitized; no raw request/response logging (the `ai_call` log line carries char counts and route only). Prompt-side spend is metered per user. |
| SMTP | `services/mailer.py`, `services/verification.py`, `services/parent_digest.py` | Recipient email, reset/verification link, weekly digest (aggregates and chapter labels only) | Mail is optional in production only if SMTP is deliberately configured (boot guard requires it); digest body never contains conversation content. |
| Sentry (optional) | `initialize/observability.py` | Error events, `extra` payloads, breadcrumbs | `before_send=scrub_sentry_event` (F-043) replaces email/phone/Bearer/vendor-token strings and drops unbounded object reprs; only active when `SENTRY_DSN` is set. |
| Web client | `apps/web/src/lib/safeMarkdown.tsx` | Links/images inside rendered answers cannot reach arbitrary hosts (scheme + same-origin + data:image allowlists) | No third-party analytics scripts; fonts self-hosted. |

## 7. Honest gaps (not fixed this step)

- No automatic **account-dormancy** purge: self-service deletion exists and
  cascades every owned row, but a signed-up-and-abandoned student keeps data
  until admin action.
- `consent_at`/`consent_ip` horizon is policy-on-paper (limitation period),
  not a coded expiry.
- The table above marks unswept tables `unbounded`; the largest of those
  (`quiz_attempts`/`answer_log` are partly bounded, but chapter progress,
  daily activity, revision items, notes, notifications, teacher documents,
  AI jobs) have no cadence beyond erasure. Owner decision needed on windows.
- Teacher/parent names have no retention sweep (needed while accounts are
  active; dormancy gap above).
