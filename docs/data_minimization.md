# Data-Minimization Review (S5.8)

Scope: every table in `apps/api/src/bangla_gpt_api/db/models.py` plus the
log surfaces. Reviewer: engineering (self-review). **Bangladesh legal
review is a human step and is NOT done here — see PROGRESS.md S5.8 🖐.**

Legend: **KEEP** = required for the product or a legal obligation;
**MINIMIZED** = stored, but with active reduction (hashing, encryption,
short TTL, sweep); **NONE** = we deliberately do not store it.

## Field-by-field

| Data | Where | Verdict | Why / minimization applied |
| --- | --- | --- | --- |
| Email | `users.email` | KEEP | Login identity; no other contact channel exists. |
| Password | `users.password_hash` | MINIMIZED | Argon2id hash only, never plaintext (S2 hardening). |
| Role / school_id / flags | `users` | KEEP | Authorization model; no extra attributes stored. |
| Name, class_level | `students`, `teachers`, `parents` | KEEP | Product function (addressing, class content). Single field, no birth dates, no addresses, no national IDs — we never ask for them. |
| Guardian phone | `parents.phone_enc` | MINIMIZED | Fernet-encrypted at rest when `PII_ENC_KEY` is set; required in production by config guard (S5.6). Never logged, never exported. Empty when not given. |
| Consent `version` / `at` / `ip` | `students` | KEEP | Legal evidence of guardian consent. `consent_ip` is retained **only** as consent evidence (statutory-limitation horizon), never used for analytics, never joined to logs. S5.8 keeps it current via the re-confirm flow (`/students/{id}/consent`). |
| Chat content | `conversations`, `chat_messages` | MINIMIZED | Needed for multi-turn tutoring and the "ami bujhi na" loop. Retention: `chat_retention_days` (default 180) then hard-deleted by the retention sweep (endpoint + nightly job, S5.8). |
| Quiz attempts / answers | `quiz_attempts`, `answer_logs` | KEEP | Core pedagogy (weak-chapter detection). Content is NCTB corpus text, not user-authored PII. |
| Reset / verification / invite tokens | `password_resets`, `email_verifications`, `parent_invites` | MINIMIZED | Only SHA-256 **hashes** stored; single-use; swept after expiry + 30-day grace (`retention.py`). |
| Feedback (thumbs + optional comment) | `feedback` | KEEP | Product improvement; not joined to chat content beyond ids. Triage queue lands in S5.10. |
| Analytics events | — | NONE | `/events` logs event **name** and prop **keys** only — prop values (arbitrary client input) are never persisted or logged (main.py `record_event`). |
| Audit trail | `audit_log` | MINIMIZED | Append-only, five privileged actions; `detail` holds ids and **counts only** — never message content, never PII (R11). Covered by tests. |
| Provider prompts/responses | — | NONE | No Gemini request/response logging (S5.6). Provider calls keep no raw transcript on our side beyond the chat rows we already own. |
| Server logs | `logs/*.jsonl`, stdout | MINIMIZED | Structured JSON with whitelisted keys; secret redaction + content guard (S5.6); rotation configured in S4.x. |
| Job ledger | `job_runs` | KEEP | Scheduling bookkeeping; period keys and count summaries only. |

## What the S5.8 sweep enforces

`services/retention.py` is the single policy point, used by
`POST /admin/maintenance/purge` (with `dry_run=true` for evidence) and the
nightly arq job:

* Conversations + their messages older than `chat_retention_days` — deleted.
* Expired password-reset / email-verification rows older than 30 days — deleted.
* **Used** parent invites older than 30 days — deleted (unused invites stay
  until their own expiry so a student's shared code still works).
* Report and audit row carry counts only (R11). `PII_ENC_KEY` is
  deliberately NOT in backups (docs/backup_dr.md).

## Honest gaps (not fixed this step)

* No automatic **account-dormancy** purge yet — self-service deletion exists
  (`DELETE /users/me`), but a signed-up-and-abandoned student keeps data
  until admin action. Candidate for a later step.
* `consent_at`/`consent_ip` horizon is policy-on-paper (limitation period),
  not a coded expiry.
* Web analytics: the frontend loads no third-party analytics — but the
  Hind Siliguri font is currently self-hosted; keep it that way (R5 tokens).
* Teacher/parent names have no retention sweep (needed while accounts are
  active; dormancy gap above).
