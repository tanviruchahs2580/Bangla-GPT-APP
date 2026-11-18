# Data Protection Impact Assessment — Bangla GPT (DRAFT)

| | |
|---|---|
| **Document** | DPIA_BANGLA_GPT_DRAFT.md |
| **Status** | **DRAFT — NOT LEGALLY APPROVED.** Engineering DPIA draft; not legal advice, not certification, not a compliance statement. |
| **Version** | 0.1 (2026-11-18) |
| **Prepared by** | Engineering (evidence-first workstream E of the mobile-platform-hardening release) |
| **Reviewers required** | Platform owner; external legal counsel (Bangladesh law); DPO/Chief Data Officer candidate (see §18–19) |
| **Next review** | On counsel feedback, or at each vendor/contract change, whichever first |
| **Scope** | The full Bangla GPT platform (FastAPI + Postgres/Redis API, React/PWA web app, Capacitor Android app) and the 2026-11-18 hardening release. |

**Labels used throughout:** `VERIFIED` (traced in current code/config), `PARTIALLY VERIFIED`,
`NOT VERIFIED`, `GAP`, `UNKNOWN — OWNER/VENDOR CONFIRMATION REQUIRED`, `LEGAL REVIEW REQUIRED`.
No assumed control is presented as implemented. Evidence pointers cite files at the
2026-11-18 baseline (`d24719a` + this branch); line numbers were current when written.

---

## 1. Executive summary and decision sought

Bangla GPT is a Bangladesh-first, child-focused NCTB learning platform whose users are
predominantly **minors** (students), plus guardians, teachers, school administrators and
platform administrators. It processes children's education records, guardian identity and
consent evidence, tutor chat content, quiz performance, and authentication/telemetry data.

**Decision sought:** (a) owner/counsel review of this draft and its open legal questions;
(b) a go/no-go on the residual high risks in §17 before further production scaling;
(c) assignment of the owners in §14.

**Headline findings:**

1. Bangladesh now has a comprehensive personal-data statute — **ব্যক্তিগত উপাত্ত সুরক্ষা
   আইন, ২০২৬ (Personal Data Protection Act, 2026, Act No. 63 of 2026)**, gazetted
   10 April 2026. The repository's `docs/dpa_template.md` still asserts Bangladesh has no
   comprehensive GDPR-equivalent law. **That premise is stale and is corrected by this
   draft** (§4, E7 correction applied). `LEGAL REVIEW REQUIRED` for all interpretations.
2. The engineering controls relevant to child data are real and partly strong
   (versioned guardian consent with evidence fields, NCTB-only grounding with refusal
   rules, PII redaction before model egress, retention service, JTI revocation) — each is
   labelled with its verification level in §12.
3. The dominant residual risks are **cross-border processing by AI/telemetry vendors**,
   **guardian-consent validity and child participation**, **backup/export propagation of
   erasure**, and **shared-device leakage on the Android app** (§13–§17).
4. No production data flows were changed by the hardening release; the Cloudflare PoC
   (if run) is isolated and is **not** a sub-processor (§16).

## 2. Product description, processing context and purpose boundaries

- **What it is:** NCTB-textbook-grounded Bengali AI tutor (chat with retrieval), quizzes,
  learning progress/analytics, teacher tools (assignments, short tests, question papers,
  analytics), school administration (students/teachers/classrooms/coverage), parent
  monitoring, and an admin console (users, schools, feedback triage, refusal audit,
  version audit). Web app + PWA + Capacitor Android shell; FastAPI/SQLAlchemy 2 API;
  Postgres; Redis (rate limiting, session/JTI revocation, arq jobs); RAG over NCTB corpus.
- **Purpose boundaries (implemented):** the tutor answers **only** from NCTB-grounded
  content; safety screening and refusal rules are product policy and are **out of scope for
  change** in this release (`VERIFIED` in `services/tutor.py` + RAG phase docs).
- **Not done here:** no new product functionality, no consent-semantics change, no
  retention-constant change (E5 boundary respected).

## 3. Data subjects and age groups

| Subject | Age/capacity | Notes |
|---|---|---|
| Students | **Minors** (school classes; exact age range `UNKNOWN — OWNER CONFIRMATION REQUIRED`, design assumption: roughly 10–18) | Primary data subjects; shared Android devices are common |
| Guardians/parents | Adults | Identity + contact + consent evidence |
| Teachers, school admins | Adults | Institutional accounts; classroom records |
| Platform admins | Adults | Impersonation capability exists (audited) — insider-risk item |

## 4. Applicable law and legal-source register

**Primary sources verified 2026-11-18:**

1. Official PDF of the Act, downloaded from the Bangladesh Laws portal
   (`https://bdlaws.minlaw.gov.bd/upload/act/2026-04-30-15-42-43-Act-No.-63-of-2026.pdf`,
   HTTP 200, 308,979 bytes, 28 pages): Bangladesh Gazette extra issue, Thursday
   10 April 2026, publishing **"২০২৬ সনের ৬৩ নং আইন"** (Act No. 63 of 2026). `VERIFIED`.
2. Government Press extraordinary-gazette index for April 2026
   (`dpp.gov.bd/bgpress/bangla/index.php/document/extraordinary_gazettes_monthly/2026-04-14`,
   HTTP 200): entry **"২০২৬ সনের ৬৩ নং আইন।--ব্যক্তিগত উপাত্ত সুরক্ষা আইন, ২০২৬। National
   Parliament of Bangladesh"** — the Personal Data Protection Act, 2026. `VERIFIED`.
   The same index lists a separate **জাতীয় উপাত্ত ব্যবস্থাপনা আইন, ২০২৬** (National Data
   Management Act, 2026) — related statute, interaction unexamined. `LEGAL REVIEW REQUIRED`.
3. The portal HTML page itself (`act-1692.html`) timed out from this environment; the PDF
   above is the authoritative artefact. `PARTIALLY VERIFIED` (portal page not rendered).

**Section index:** the requesting brief supplies a section index (5 lawful basis; 7
sensitive data; 8 processors; 9 children; 11–14 rights/propagation; 15–22
accountability/security/retention/breach/audit; 23 CDO; 29–30 classification/transfer;
31–35 complaints/fines/compensation). The gazette PDF is **Bijoy-legacy-encoded Bangla**;
automated clause-level extraction was not reliable in this environment, so the section
index is recorded as `PARTIALLY VERIFIED` — act identity/publication verified, clause text
**not** independently read. **No obligation is inferred from the index alone** (E1 rule).
Full clause reading, commencement/transition rules and subordinate rules:
`LEGAL REVIEW REQUIRED` (counsel).

**Comparative methodology:** GDPR DPIA concepts (necessity/proportionality, rights, risk
register) are used as a *method*, not as applicable law. Foreign-law comparisons are
labelled as such. No "GDPR compliance" claim is made or implied.

## 5. Controller / processor role analysis by purpose

| Purpose | Likely controller/fiduciary | Processors | Status |
|---|---|---|---|
| Student tuition (tutor, quizzes, progress) | Platform operator (and/or the school, if the school deploys it) | LLM provider, hosting/VPS | `LEGAL REVIEW REQUIRED` — school-vs-operator split is a factual/contractual question per deployment |
| Guardian consent, accounts | Platform operator | — | `LEGAL REVIEW REQUIRED` |
| Teacher materials, school admin | School (likely) / operator (joint?) | — | `LEGAL REVIEW REQUIRED` |
| Security telemetry, error monitoring | Platform operator | Sentry | `VERIFIED` (integration in code) / contract `UNKNOWN` |
| Email delivery | Platform operator | SMTP provider | `VERIFIED` (code) / contract `UNKNOWN` |

Do **not** assume one controller for all purposes. Each deployment (school-procured vs
direct-to-consumer) may change the answer.

## 6. Data inventory and classification (summary)

Full field-level inventory: `docs/data_minimization.md` (cross-checked against
`apps/api/src/bangla_gpt_api/db/models.py` at baseline). Classes:

- **Identity/account:** email, name, role, school/class/section, password hash (never
  plaintext), MFA material. `VERIFIED`.
- **Child education records:** quiz attempts/answers, scores, mastery/ability signals,
  learning preferences, optional AI memory. `VERIFIED`.
- **Tutor content:** chat messages, retrieved NCTB passages, model responses, refusal
  events. `VERIFIED`.
- **Guardian consent evidence:** `consent_version`, `consent_at`, `consent_ip`
  (`VERIFIED` in models/migrations — the IP is personal data; retention of it is a
  minimisation question, `LEGAL REVIEW REQUIRED`).
- **Security/telemetry:** audit logs, sessions, Sentry error payloads (may incidentally
  contain user identifiers — scrubbing rules `PARTIALLY VERIFIED`).
- **Special/sensitive:** the Act's "sensitive personal data" definition (§7 of the Act per
  the index) may capture children's data and education records — classification mapping is
  `LEGAL REVIEW REQUIRED`.

## 7. System architecture (as built)

FastAPI API (VPS) ↔ Postgres (primary + backups) ↔ Redis (rate limit, JTI revocation,
arq) ↔ LLM provider (chat + embeddings per config) ↔ NCTB corpus (RAG). Web/PWA on Vercel;
Android via Capacitor WebView; Cloudflare DNS/CDN in front. Details: `docs/runbook.md`,
`deploy/DEPLOYMENT.md`, `docker-compose.yml`, `docs/hosting_decision.md`. `VERIFIED` at
the level of "these components exist and are wired this way"; per-environment values are
redacted and not reproduced here.

## 8. End-to-end data-flow map and vendor/sub-processor register

Flow (student ask): app → API (auth via session cookie; Redis JTI check) → PII redaction
(`services/pii.py`) → RAG retrieval over NCTB chunks → LLM provider call (redacted prompt
+ retrieved passages) → response streamed (SSE) → chat row persisted → audit log.

Vendor register (status at baseline):

| Vendor | Data seen | Purpose | Region | DPA/contract | Retention/training terms | Transfer question |
|---|---|---|---|---|---|---|
| LLM provider (incl. Gemini while configured) | Redacted prompts, NCTB passages | Generation/embeddings | `UNKNOWN` | `UNKNOWN — OWNER/VENDOR CONFIRMATION REQUIRED` | `UNKNOWN` (training-use terms must be confirmed in writing) | `LEGAL REVIEW REQUIRED` |
| VPS/hosting | All platform data | Hosting | `UNKNOWN` (hosting_decision.md records the choice; jurisdiction wording to confirm) | `UNKNOWN` | n/a | `LEGAL REVIEW REQUIRED` |
| Postgres + backups | All platform data | Storage/DR | Same region as VPS (assumed) `PARTIALLY VERIFIED` | n/a (self-managed) | Backup rotation per `docs/backup_dr.md` `VERIFIED` (documented) | follows VPS |
| SMTP provider | Email addresses, message metadata | Transactional email | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `LEGAL REVIEW REQUIRED` |
| Vercel | Static assets; no student data by design | Static hosting | Global CDN | `UNKNOWN` | n/a | low risk, confirm |
| Cloudflare | DNS/CDN metadata (IP, URLs) for proxied traffic | Edge | Global | `UNKNOWN` | `UNKNOWN` | `LEGAL REVIEW REQUIRED` |
| Sentry | Error payloads (may include user ids) | Error monitoring | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `LEGAL REVIEW REQUIRED` |

**Rule honoured:** no vendor is described as receiving *less* than the code shows; the
LLM egress path was traced (`pii.py` → provider adapter) but payloads were not captured
live in this workstream (synthetic-only environment), so "what exactly leaves" is
`PARTIALLY VERIFIED` — the redaction point is `VERIFIED` in code.

## 9. Necessity and proportionality

- Collection appears bounded to the product's stated purposes (no ad-tech, no third-party
  trackers in the web app; fonts are self-hosted as of this release — zero third-party
  font egress, `VERIFIED` in `FONT_E5_PHASE2.md`).
- Alternatives considered and recorded: smaller chat retention, IP-free consent evidence,
  on-prem LLM. Each has product/quality trade-offs; **decisions belong to the owner with
  counsel** — listed in §14, not decided here.
- `GAP`: consent IP retention period is not separately justified in the inventory.

## 10. Consent, lawful basis, transparency, child rights

- Versioned guardian consent with evidence fields is implemented (`VERIFIED`).
- Whether consent is the correct (or sole) basis per purpose — especially for school
  deployments where the school may be the controller — is `LEGAL REVIEW REQUIRED`.
- Child participation: whether the Act requires age-appropriate notice to the child in
  addition to guardian action is `LEGAL REVIEW REQUIRED`. Product today addresses notices
  to guardians; a child-facing notice is a `GAP` pending counsel.
- Withdrawal/objection/access/portability/correction/erasure flows exist in
  `services/gdpr.py` (`VERIFIED` at code level); **system-wide propagation to processors**
  (per Act §§11–14 per the index) is `GAP` — vendor-side deletion is not evidenced.

## 11. Retention, deletion, export, backups

- `services/retention.py` implements scheduled purge with per-table windows
  (`VERIFIED`); `docs/data_minimization.md` documents the schedule. Discrepancies between
  inventory, code constants and the published privacy policy are listed in the inventory
  doc's gap section (`PARTIALLY VERIFIED`).
- Backups: rotation documented (`docs/backup_dr.md`); **erasure does not rewind backups**
  — deletion takes effect on backup expiry. This is disclosed? `GAP` — confirm the privacy
  notice states it.
- Exports: implemented in `services/gdpr.py` (`VERIFIED`).
- No retention constant was changed in this release (E5 boundary).

## 12. Security and privacy controls evidenced in code

| Control | Evidence | Level |
|---|---|---|
| Session/JTI revocation via Redis | auth services | `VERIFIED` |
| PII redaction before LLM egress | `services/pii.py` | `VERIFIED` (code); live payload `NOT VERIFIED` |
| NCTB-only grounding + refusal | `services/tutor.py`, RAG docs | `VERIFIED` |
| Rate limiting | Redis middleware | `VERIFIED` |
| Audit logging incl. impersonation | audit models/services | `VERIFIED` |
| Password hashing (no plaintext) | models | `VERIFIED` |
| Consent versioning + evidence | models/migrations | `VERIFIED` |
| Secrets management | env/config templates (values redacted) | `PARTIALLY VERIFIED` |
| Encryption at rest (disk/db) | `UNKNOWN — OWNER CONFIRMATION REQUIRED` |

## 13. Threat/risk register (child-focused)

Scale: likelihood L and severity S on 1–5; inherent and residual (after listed controls).

| ID | Risk | L×S (inh→res) | Existing safeguards | Residual treatment |
|---|---|---|---|---|
| R1 | Excessive collection / secondary use of child records | 3×4→2×4 | minimisation inventory; no trackers | owner policy on analytics; `LEGAL REVIEW REQUIRED` |
| R2 | Invalid/unclear guardian consent; no child-facing notice | 3×5→2×5 | versioned consent + evidence | child notice + basis review (§10) |
| R3 | Cross-border vendor processing without confirmed terms | 4×4→3×4 | vendor register (this doc) | written confirmations; transfer assessment |
| R4 | Erasure not propagated to vendors/backups | 3×4→2×4 | gdpr service; backup expiry | vendor deletion workflows; notice wording |
| R5 | Chat/quiz data exposed across students/teachers/schools | 2×5→1×5 | tenancy scoping in queries; role gates; ResponsiveTable preserves boundaries | keep tenancy tests green |
| R6 | Re-identification from school/district aggregates | 2×3→2×3 | aggregation thresholds `PARTIALLY VERIFIED` | k-anonymity review for exports |
| R7 | Model-provider retention/training on child prompts | 3×4→3×4 | redaction pre-egress | zero-retention/training-off contract terms |
| R8 | Inaccurate ability inferences affecting a child | 2×3→2×3 | teacher-in-the-loop review | explainability/override UX decision |
| R9 | Safety/refusal events revealing sensitive child disclosures | 2×5→2×4 | refusal pipeline; audit | access-limit refusal detail; counsel view |
| R10 | Shared-device leakage (Android local cache/session) | 4×3→3×3 | no PII in native diagnostics; back-button dirty-confirm | session timeout UX; device-level guidance |
| R11 | Insider misuse (admin impersonation) | 2×4→1×4 | audited impersonation | periodic audit review procedure |
| R12 | Security incident / backup leak | 2×5→2×4 | runbook, DR docs | breach-notification mapping (§15) |
| R13 | Retention exceeding purpose / premature purge of needed records | 2×3→2×3 | retention service + inventory | reconcile inventory↔policy↔code annually |
| R14 | Vendor change not reflected in notices/contracts | 3×3→2×3 | this register | vendor-change review trigger |

High/critical residual items (R2, R3, R7, R9, R10) each need a named owner and target
date — §14.

## 14. Mitigation plan (owners and dates to be assigned by the owner)

| Action | Risk | Owner (proposed) | Due |
|---|---|---|---|
| Counsel review of Act 63 of 2026 applicability, commencement, bases, child provisions | R2,R3,R7,R9 | Owner + external counsel | before scale-up |
| Written vendor confirmations (retention, training, deletion, region) for LLM/SMTP/Sentry/hosting/CDN | R3,R7 | Owner | before scale-up |
| Child-facing age-appropriate notice (bn/en) | R2 | Product + counsel | next release train |
| Vendor deletion workflow + privacy-notice backup wording | R4 | Owner | next release train |
| Refusal-event access minimisation review | R9 | Eng + counsel | next quarter |
| Shared-device session policy (timeout, "sign out" prominence) | R10 | Product | next release train |
| Reconcile data_minimization inventory ↔ retention code ↔ privacy policy | R13 | Eng | next quarter |

## 15. Breach response and communication

`docs/runbook.md` + `docs/backup_dr.md` cover detection/restore (`VERIFIED` as
documents). **Not yet mapped:** statutory notification thresholds/timelines under Act 63
of 2026, and parent/school communication duties. `LEGAL REVIEW REQUIRED`; add to the
runbook after counsel review.

## 16. Cross-border transfer and data residency

All vendor regions are `UNKNOWN` pending confirmation (§8). The Act's transfer provisions
(§§29–30 per the index) and any data-localisation expectations for education data are
`LEGAL REVIEW REQUIRED`. The hardening release added **no** new cross-border flow; fonts
are self-hosted (removes a potential third-party egress); the Cloudflare investigation is
study-only, and any PoC is isolated with no student data and is **not** a sub-processor.

## 17. Residual high risks and go/no-go conditions

Do not scale production (new schools/regions) until: (1) counsel confirms the applicable
basis/consent model and child-notice duty; (2) written vendor terms for R3/R7 exist;
(3) the child-facing notice ships; (4) breach-notification mapping lands in the runbook.
These are **human decisions**; this draft does not clear them.

## 18. Stakeholder consultation and human approvals required

Owner sign-off; external Bangladesh counsel; school/procurement input where deployments
are school-mediated; DPO/Chief Data Officer determination (Act §23 per the index —
`LEGAL REVIEW REQUIRED`).

## 19. Legal counsel review checklist

- [ ] Commencement/transition of Act 63 of 2026; subordinate rules in force
- [ ] Controller/processor allocation per deployment model (§5)
- [ ] Lawful basis per purpose; consent validity for minors; child participation duty
- [ ] Sensitive-data classification of education/behaviour records (§7 of the Act)
- [ ] Cross-border transfer conditions (§§29–30); vendor transfer assessments
- [ ] CDO/DPO applicability and effective date (§23)
- [ ] Breach notification thresholds/timelines (§§15–22 range)
- [ ] Interaction with the National Data Management Act, 2026
- [ ] Education-sector/procurement-specific requirements

## 20. Evidence appendix (statement → source)

| Statement | Evidence |
|---|---|
| Act identity/publication | gazette PDF + dpp.gov.bd index (§4; retrieval 2026-11-18) |
| Consent fields | `apps/api/.../db/models.py` (consent_version/consent_at/consent_ip) |
| Redaction before egress | `apps/api/.../services/pii.py` |
| Grounding/refusal | `apps/api/.../services/tutor.py`; `docs/rag/v3/CHECKPOINT.md` |
| Retention schedule | `apps/api/.../services/retention.py`; `docs/data_minimization.md` |
| Rights flows | `apps/api/.../services/gdpr.py` |
| Backup rotation | `docs/backup_dr.md` |
| No third-party font egress | `docs/engineering/mobile-platform-hardening/FONT_E5_PHASE2.md` |
| Play data-safety declarations | `docs/playstore/data-safety.md` (discrepancies flagged, not edited) |
| Stale legal premise corrected | `docs/dpa_template.md` (updated in this release) |

**What was NOT verified and why:** live vendor payload capture (synthetic-only
environment); vendor contract terms (owner/vendor action); clause-level text of Act 63 of
2026 (Bijoy-encoded PDF; counsel task); per-environment infrastructure values (redacted).
