# Data-Minimization Review

Scope: every table in `apps/api/src/bangla_gpt_api/db/models.py` plus the
log surfaces. Reviewer: engineering (self-review). **Bangladesh legal
review is a human step and is NOT done here — see
[`archive/PROGRESS.md`](archive/PROGRESS.md).**

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
| Guardian phone | `parents.phone_enc` | MINIMIZED | Fernet-encrypted at rest when `PII_ENC_KEY` is set; required in production by config guard. Never logged, never exported. Empty when not given. |
| Consent `version` / `at` / `ip` | `students` | KEEP | Legal evidence of guardian consent. `consent_ip` is retained **only** as consent evidence (statutory-limitation horizon), never used for analytics, never joined to logs. Consent evidence stays current via the re-confirm flow (`GET /students/{id}/consent`, `POST /students/{id}/consent/reconfirm`). |
| Chat content | `conversations`, `chat_messages` | MINIMIZED | Needed for multi-turn tutoring and the "ami bujhi na" loop. Retention: `chat_retention_days` (default 180) then hard-deleted by the retention sweep (endpoint + nightly job — see "What the sweep enforces" below). |
| Quiz attempts / answers | `quiz_attempts`, `answer_log` | KEEP | Core pedagogy (weak-chapter detection). Content is NCTB corpus text, not user-authored PII. |
| Reset / verification / invite tokens | `password_resets`, `email_verifications`, `parent_invites` | MINIMIZED | Only SHA-256 **hashes** stored; single-use; swept after expiry + 30-day grace (`retention.py`). |
| Feedback (thumbs + optional comment) | `feedback` | KEEP | Product improvement; not joined to chat content beyond ids. Triage queue lands in `GET /admin/feedback` (oldest open first). |
| Analytics events | — | NONE | `/events` logs event **name** and prop **keys** only — prop values (arbitrary client input) are never persisted or logged (main.py `record_event`). |
| Audit trail | `audit_log` | MINIMIZED | Append-only, five privileged actions; `detail` holds ids and **counts only** — never message content, never PII. Covered by tests. |
| Provider prompts/responses | — | NONE | No Gemini request/response logging. Provider calls keep no raw transcript on our side beyond the chat rows we already own. |
| Server logs | `logs/*.jsonl`, stdout | MINIMIZED | Structured JSON with whitelisted keys; secret redaction + content guard; rotation configured in S4.x. |
| Job ledger | `job_runs` | KEEP | Scheduling bookkeeping; period keys and count summaries only. |

## What the sweep enforces

`services/retention.py` is the single policy point, used by
`POST /admin/maintenance/purge` (with `dry_run=true` for evidence) and the
nightly arq job:

- Conversations + their messages older than `chat_retention_days` — deleted.
- Expired password-reset / email-verification rows older than 30 days — deleted.
- **Used** parent invites older than 30 days — deleted (unused invites stay
  until their own expiry so a student's shared code still works).
- Report and audit row carry counts only. `PII_ENC_KEY` is
  deliberately NOT in backups (docs/backup_dr.md).

## Honest gaps (not fixed this step)

- No automatic **account-dormancy** purge yet — self-service deletion exists
  (`DELETE /users/me`), but a signed-up-and-abandoned student keeps data
  until admin action. Candidate for a later step.
- `consent_at`/`consent_ip` horizon is policy-on-paper (limitation period),
  not a coded expiry.
- Web analytics: the frontend loads no third-party analytics — but the
  Hind Siliguri font is currently self-hosted; keep it that way (tokens).
- Teacher/parent names have no retention sweep (needed while accounts are
  active; dormancy gap above).

## Applicable-law mapping (AUD-B-12) — requirements to confirm with counsel

This is an engineering inventory, not legal advice and not a legal
conclusion (I10). Source column = where the statement comes from today;
each row is an item for counsel to confirm, amend or delete.

| # | Requirement area | What the product does today | Source / status |
| --- | --- | --- | --- |
| L-1 | Bangladesh data-protection statutes: the Digital Security Act / Cyber Security Act 2023 and any successor or education-sector rules | No compliance claim is made. The DPA template names the statutes and states counsel review has not been performed | `docs/dpa_template.md` (checked 2026-10-18); no comprehensive GDPR-equivalent statute is asserted there. **Counsel to confirm** current statute names, commencement status and applicability to a school-data processor |
| L-2 | Children's data and guardian consent | Guardian consent is mandatory for student registration, versioned (`CONSENT_VERSION`) and re-confirmed on version change; consent evidence (`consent_ip`, `consent_at`) is stored for exactly that purpose | Code: `routers/auth.py`, `routers/deps.py`; verified by `tests/test_compliance_v2.py`. **Counsel to confirm** the required consent form, age of digital consent and whether school-mediated consent replaces guardian consent |
| L-3 | Purpose limitation, minimisation, retention | Field-level inventory above; hard-delete retention sweep (`services/retention.py`); self-service export and erasure | `docs/data_minimization.md` (this file); `tests/test_data_export.py`, `tests/test_delete_cascade_v2.py`. **Counsel to confirm** retention periods are defensible |
| L-4 | Cross-border transfer / processor terms | Student prompts and retrieved textbook passages go to Google Gemini; no name, email or phone is included in the payload. Provider terms acknowledgement is an owner action | `docs/dpa_template.md` (sub-processor table). **Counsel/provider to confirm** regional routing, retention and the correct contractual basis for minors' data |
| L-5 | Breach notification duties | No notification timeline is claimed or coded. Incident runbooks currently contain no "suspected breach" page and name no escalation contacts (tracked separately) | Honest gap; **counsel to confirm** who must be notified, within what period, and to whom |
| L-6 | Data-subject rights | Export and delete are implemented end-to-end in code; server logs are documented as not subject-deletable ("where feasible") | Code + `docs/dpa_template.md` §3.5. **Counsel to confirm** whether access/erasure must extend to logs |
| L-7 | Government/authority reporting exports | Aggregate-only, k-anonymity floored in the service, PII scan fails the export closed, and every successful export now writes an audit row | `services/govt_report.py`, `routers/school.py`, audit action `govt_export`. **Counsel to confirm** any additional disclosure-authority requirements |
| L-8 | Security of processing (GDPR-style baseline) | Argon2id, JWT with revocation, tenancy isolation, rate limits, at-rest encryption for PII and backups, append-only audit trail | `SECURITY.md`, `docs/backup_dr.md`. Treated as the baseline where Bangladesh-specific rules are silent |

Open owner actions from this table: commission the counsel review, record the
decision here with the date, and convert each confirmed item into either a
code change or a documented acceptance.
