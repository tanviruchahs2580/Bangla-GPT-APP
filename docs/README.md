# Documentation index

Living documentation for the Bangla GPT APP. Point-in-time session and audit
reports are **not** kept here — they live in [`archive/`](archive/) and are
never quoted as current state. There is exactly one current QA record, under
[`qa/`](qa/) (`qa/QA_REPORT_YYYY-MM-DD.md`), superseded and archived when the
next is written.

## Core

| Doc | Purpose |
|---|---|
| [API.md](API.md) | Hand-written endpoint reference (core surface, SSE stream and pagination contracts; see `route_baseline.md` + `/openapi.json` for the full route list) |
| [architecture.md](architecture.md) | System architecture and decisions |
| [architecture/DATABASE_ARCHITECTURE.md](architecture/DATABASE_ARCHITECTURE.md) | Data model |
| [architecture/TARGET_ARCHITECTURE.md](architecture/TARGET_ARCHITECTURE.md) | Target architecture (bounded contexts) |
| [adr/ADRs.md](adr/ADRs.md) | Architecture decision records |
| [runbook.md](runbook.md) | Operations runbook |
| [ci.md](ci.md) | What every workflow runs, what blocks a merge, and how to reproduce it locally |
| [route_baseline.md](route_baseline.md) | Route inventory regenerated 2026-10-30 from the app's own schema (143 method+path routes); regenerate the same way when routes change |
| [qa/QA_REPORT_2026-10-29.md](qa/QA_REPORT_2026-10-29.md) | Current QA record |

## AI / data

| Doc | Purpose |
|---|---|
| [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md) | Retrieval + grounding design |
| [NCTB_DATA_PIPELINE.md](NCTB_DATA_PIPELINE.md) | Corpus acquisition → retrieval pipeline |
| [ai/system-card.md](ai/system-card.md) | AI system card: purpose, users, models, data, limitations, baseline measurements |
| [ai/risk-register.md](ai/risk-register.md) | AI risk register with owners, mitigations and testing check ids |
| [ai/incident-response.md](ai/incident-response.md) | AI incident severities, procedures, rollback and generation-disable steps |

## Retrieval (rag/)

| Doc | Purpose |
|---|---|
| [rag/architecture.md](rag/architecture.md) | As-built map of the retrieval/answering subsystem (verified against the code) |
| [rag/golden-set-v3.md](rag/golden-set-v3.md) | Golden-set v3 design, composition, labelling and leakage rules |
| [rag/target-architecture.md](rag/target-architecture.md) | Target retrieval architecture and phased roadmap (a plan, not current state) |

## Language

| Doc | Purpose |
|---|---|
| [glossary-bn.md](glossary-bn.md) | Proposed canonical Bangla terms (one per concept) and the numeral policy proposal |

## Operations & compliance

| Doc | Purpose |
|---|---|
| [operations/PRODUCTION_DEPLOYMENT.md](operations/PRODUCTION_DEPLOYMENT.md) | Deployment architecture + procedure |
| [backup_dr.md](backup_dr.md) | Backup and disaster recovery |
| [capacity_plan.md](capacity_plan.md) | Capacity planning |
| [owasp_checklist.md](owasp_checklist.md) | OWASP review checklist |
| [security/threat-model.md](security/threat-model.md) | Threat model: assets, actors, trust boundaries, mitigations by surface |
| [security/codeql-triage-2026-10-27.md](security/codeql-triage-2026-10-27.md) | CodeQL/Scorecard alert triage record |
| [security_scans.md](security_scans.md) | Security scan records |
| [dependency_waivers.md](dependency_waivers.md) | Dependency risk waiver register |
| [type-checking-plan.md](type-checking-plan.md) | mypy strictness plan |
| [scale_report.md](scale_report.md) | Scale audit + local load-test numbers |
| [data_minimization.md](data_minimization.md) | PII minimization policy |
| [dpa_template.md](dpa_template.md) | Data processing agreement template |
| [mobile_release.md](mobile_release.md) | Android/Capacitor release process |
| [hosting_decision.md](hosting_decision.md) | Hosting choices |
| [feature_flags.md](feature_flags.md) | Runtime switches with owner + exit condition per switch |
| [tech_debt.md](tech_debt.md) | Technical debt register (effort / risk / owner) |
| [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md) | Owner launch gates |

## Store & native review

| Doc | Purpose |
|---|---|
| [playstore/LAUNCH.md](playstore/LAUNCH.md) | Play Console launch runbook (repo-side vs owner-side steps) |
| [playstore/listing.md](playstore/listing.md) | Store listing copy, `bn-BD` + `en-US` |
| [playstore/data-safety.md](playstore/data-safety.md) | Play Data safety form answers |
| [playstore/content-rating.md](playstore/content-rating.md) | IARC content-rating questionnaire answers |
| [native-review-sheet.md](native-review-sheet.md) | Native-speaker review record for the Bangla copy |
| [native-review/ui-strings.md](native-review/ui-strings.md) | Generated list of every user-facing Bangla string (regenerate with `scripts/gen_native_review.py`) |
