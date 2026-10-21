# Bangladesh applicable-law mapping — sources and open questions

Finding: AUD-B-31 / B register B-31 ("no consolidated applicable-law mapping
document with sources and dates"). Collected 2026-10-19.

> **No legal conclusions here.** Every row is a statement about *what was
> found in the cited sources* plus *what the product does today*, and the
> question counsel must answer. Nothing in this document asserts compliance,
> non-compliance, or which law applies. This document is not legal advice.

## Sources checked (fetched 2026-10-19)

| # | Source | What it supports |
|---|---|---|
| S1 | Wikipedia, *Cyber Security Act, 2023* — <https://en.wikipedia.org/wiki/Cyber_Security_Act,_2023> | statute number (Act No. 46 of 2023), enactment date (13 Sep 2023, assented + commenced), predecessor (Digital Security Act 2018), repeal and replacement (May 2025) |
| S2 | DLA Piper, *Data Protection Laws of the World — Bangladesh* — <https://www.dlapiperdataprotection.com/index.html?t=law&c=BD> (page "last modified 3 January 2024") | the *absence* of a comprehensive data-protection statute as of that revision; sector rules; CA 2023's limited data provisions |
| S3 | NIST SP 800-63B Rev. 4 §3.1.1.2 — <https://pages.nist.gov/800-63-4/sp800-63b.html> (page modified 2025-08-26) | the security baseline the password policy is measured against (`docs/security/password-policy.md`) |
| S4 | This repository — `docs/dpa_template.md`, `docs/data_minimization.md` (rows L-1…L-8), `SECURITY.md` | what the product already documents about itself |

## Mapping

| # | Area | What the sources say | What the product does now (anchored) | Requirement to confirm with counsel |
|---|---|---|---|---|
| L-1 | **Cyber-security statute** | S1: Digital Security Act 2018 was replaced by the **Cyber Security Act, 2023** (Act No. 46 of 2023), enacted/brought into force 13 Sep 2023 (S2: "came into force in full on 18 September 2023"); S1 further reports the Act was **repealed in May 2025** (infobox: 21 May 2025; body: 22 May 2025) and replaced by the **Cyber Security Ordinance, 2025**. The secondary sources disagree on the force date and the Ordinance's current status was not confirmable from a primary source here. | The product names "Digital Security Act / Cyber Security Act 2023" in `docs/dpa_template.md`; that naming is now at least one statute-generation behind per S1. | Which instrument is **currently in force** (Ordinance vs Act, and any subsequent Act), its exact commencement, and whether its data-related offences (S2 cites s.26 "identity information") apply to a school-data processor. Update the DPA template wording to the confirmed name. |
| L-2 | **Comprehensive data protection** | S2 (as of its 2024-01-03 revision): no comprehensive data-protection regulation; no sensitive-data category, no registration/DPO duty, no general security duty, no breach-notification duty; consent "advisable". A Personal Data Protection Act has been discussed publicly for years but **no enacted statute could be confirmed from these sources**. | The product applies GDPR-shaped practices voluntarily (consent capture + reconfirm, export, erasure, minimization, retention sweep) and says so without claiming a statutory basis (`docs/data_minimization.md`). | Whether any personal-data-protection ordinance/act has been enacted since 2024-01-03; if yes, its categories, duties, penalties, and applicability to a children's education platform. |
| L-3 | **Children's data / guardian consent** | Neither source identified a Bangladesh provision specific to minors' data in the general online context; sector education rules were not checked. | Guardian consent is mandatory for student registration with versioned reconfirmation (`routers/auth.py`, consent fields on `students`); no targeted advertising; no data sale (`LegalPage` copy). | Whether any education-sector instrument imposes a specific verifiable-parental-consent standard, and whether "guardian" as implemented (self-attested checkbox) satisfies it. |
| L-4 | **Purpose limitation / data minimization** | Not articulated as a statutory duty in S2's summary (no general security/privacy duty described for the private sector). | Field-by-field KEEP/MINIMIZED/NONE review in `docs/data_minimization.md`; flows in `docs/compliance/data-inventory-and-flow-map.md`. | Whether any future or sector instrument imports purpose-limitation duties (e.g. via ICT rules) and what retention horizon it would expect. |
| L-5 | **Cross-border transfer** | S2 lists sector rules only: banks need Bangladesh Bank permission to move records abroad; telecom providers need Commission approval for subscriber data. | The DB lives in the operator's deployment; the LLM processor (Gemini) receives redacted prompts (no identifiers) — flagged in `docs/dpa_template.md` as the named sub-processor. | Whether the (redacted) LLM egress or hosting choice needs any transfer authorisation once the applicable statute is confirmed, and whether the redaction level changes the answer. |
| L-6 | **Breach notification** | S2: no breach-notification duty found as of its revision. | No notification timeline is claimed or coded; incident handling is in `docs/runbook.md`; the gap is listed in `docs/data_minimization.md` L-5. | Who must be notified, within what period, and to whom — **and whether that duty exists at all** under the currently-in-force instrument (S1's Ordinance was not inspectable here). |
| L-7 | **Data-subject rights** | Not specified in the sources checked. | Export (`GET /users/me/export`), erasure (`DELETE /users/me`), consent status/reconfirm endpoints exist and are tested (`test_export_completeness`, `test_account_deletion`). | Whether any access/correction/erasure duty applies, its response deadline, and whether erasure is expected to reach backups (the product documents "where feasible"). |
| L-8 | **Government/authority requests** | S1/S2 do not describe a government-export regime for education data; S2's s.26 offence concerns identity information. | Aggregate export is admin-only, k≥5, PII-scanned, audit-logged (`docs/security/aggregate-export-anonymity.md`). | What legal basis/process a ministry or district authority has to demand student data, and whether the aggregate-only posture suffices. |
| L-9 | **Security baseline** | S3 (NIST SP 800-63B Rev. 4) is not Bangladeshi law; it is cited here as the accepted engineering baseline. | Password/breach/mFA posture in `docs/security/password-policy.md` and `docs/security/mfa-privileged-roles.md`, including the open 15-character single-factor gap. | Not a legal question. Owner decision: adopt the Rev. 4 length floor before scale. |

## Owner action

1. Commission the counsel review (already an owner action in
   `docs/data_minimization.md` and `LAUNCH_READINESS_CHECKLIST.md`) and answer
   L-1 (current instrument) first — it changes the answer to L-6 and possibly
   L-5.
2. When counsel confirms statute names/dates, update `docs/dpa_template.md`
   (it still says "Digital Security Act / Cyber Security Act 2023") and record
   the review date here.
3. Re-check S2 for a revision newer than 2024-01-03 before relying on the
   "no comprehensive statute" statement.
