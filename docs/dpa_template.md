# Data Processing Agreement — Template (School ⇄ Bangla GPT)

> **TEMPLATE — DRAFT, NOT LEGAL ADVICE.** This is an engineering-authored
> starting point for a controller (school) / processor (platform) agreement.
> It must be reviewed by a Bangladeshi lawyer before any school signs it —
> that review is a 🖐 human step tracked in PROGRESS.md (S5.8) and **has not
> been performed**. Bangladesh's Digital Security Act / Cyber Security Act
> 2023 and any applicable student-data rules must be checked by counsel; the
> country has no comprehensive GDPR-equivalent statute yet, so contract terms
> carry more weight than usual.

## 1. Parties & roles

* **Data Controller:** [SCHOOL NAME], determining the purposes of processing
  student data ([ADDRESS], contact [NAME/EMAIL]).
* **Data Processor:** [OPERATING ENTITY], operator of the Bangla GPT learning
  platform ([DEPLOYMENT URL], contact [DPO/EMAIL]).

## 2. Subject matter & data

Processing exists to provide tutoring, quiz, and progress features to
students of the school. Data categories (full inventory in
docs/data_minimization.md):

| Category | Examples | Special note |
| --- | --- | --- |
| Identity | name, class level, school role | no birth dates, addresses, or national IDs are collected |
| Contact | account email; guardian phone (parents) | phone encrypted at rest (Fernet) |
| Consent evidence | accepted consent version/timestamp/IP | legal evidence only |
| Learning content | chat messages with the tutor, quiz answers | retained 180 days by default, then hard-deleted |
| Derived metrics | chapter mastery, daily activity, digests | aggregate of the above |

**Children's data:** the service is designed for students in classes 6–10.
No student feature is usable without recorded guardian consent
(`guardian_consent` at registration; versioned re-confirm flow).

## 3. Processor obligations

1. Process personal data **only** on documented instructions (the product
   features above); no secondary use, no ad-tech, no model training on
   student chats or answers by the processor.
2. Confidentiality commitments for all personnel; access is role-gated.
3. Security measures: TLS in transit, Argon2id password hashing, Fernet
   encryption for guardian phone, encrypted/managed database, nightly
   pgBackRest backups (14 fulls, restricted access), append-only audit log
   for privileged actions, OWASP-aligned review (docs/owasp_checklist.md),
   dependency scanning in CI (docs/security_scans.md).
4. Assist the controller with data-subject requests: export
   (`/account/export`, admin `/admin/users/{id}/export`) and deletion
   (`/users/me`, admin deletion, plus the retention sweep for aged data).
5. **Deletion SLA:** deletion requests executed within **[14] days**;
   backup media fall out per backup rotation (up to 14 days; documented in
   docs/backup_dr.md).
6. **Breach notification:** notify the controller without undue delay and
   no later than **[48/72] hours** after becoming aware of a personal-data
   breach, with nature, categories, approximate volumes, and remediation.
7. Sub-processors (§4); assist with audits (§5); end-of-contract deletion or
   return (§6).

## 4. Sub-processors (current)

| Sub-processor | Purpose | Data seen | Notes |
| --- | --- | --- | --- |
| [HOSTING PROVIDER] | compute + database hosting | all persisted data | contract/TBD |
| **Google Gemini (Google LLC)** | answers the tutoring/quiz-generation prompts | the student's prompt + retrieved NCTB textbook passages; no name/email is included in provider calls | provider terms & regional routing to be confirmed by counsel |
| [SMTP PROVIDER] | verification/reset/digest emails | recipient email + message content | TLS |
| [CDN/DNS — if any] | static asset delivery | IP, User-Agent via web server logs | TBD |

The controller may object to a new sub-processor on reasonable data-
protection grounds within [14] days of notice.

## 5. Audits

The controller may request, at most once per contract year, (a) the
security documents listed in §3.3, (b) the retention-sweep dry-run report,
and (c) a Q&A session with the processor's engineer. On-site audit requires
mutual scheduling; the processor may redact secrets and other schools' data.

## 6. Term & data return/deletion

On termination, the processor deletes or returns all personal data of the
school's users within [60] days (export provided as JSON), except the
consent-evidence fields retained for the limitation period stated in
docs/data_minimization.md.

## 7. Governing law

Laws of the People's Republic of Bangladesh; courts of Dhaka. **[Awaiting
counsel — lawyer to confirm clause validity, cross-border transfer stance
for Gemini/Google, and any government-access disclosure rights.]**

---

Signature blocks: controller ______ / processor ______ / date ______.
