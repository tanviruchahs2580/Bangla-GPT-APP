# Documentation index

Living documentation for the Bangla GPT APP. Point-in-time session and audit
reports are **not** kept here — they live in [`archive/`](archive/) and are
never quoted as current state. There is exactly one current QA record, under
[`qa/`](qa/) (`qa/QA_REPORT_YYYY-MM-DD.md`), superseded and archived when the
next is written.

## Core

| Doc | Purpose |
|---|---|
| [API.md](API.md) | Hand-written endpoint reference (core surface; see `route_baseline.md` + `/openapi.json` for the full route list) |
| [architecture.md](architecture.md) | System architecture and decisions |
| [architecture/DATABASE_ARCHITECTURE.md](architecture/DATABASE_ARCHITECTURE.md) | Data model |
| [adr/ADRs.md](adr/ADRs.md) | Architecture decision records |
| [runbook.md](runbook.md) | Operations runbook |
| [route_baseline.md](route_baseline.md) | Route inventory captured 2026-09-11 from the running app — no in-repo generator; re-verify against `/openapi.json` when routes change |
| [qa/QA_REPORT_2026-10-17.md](qa/QA_REPORT_2026-10-17.md) | Current QA record |

## AI / data

| Doc | Purpose |
|---|---|
| [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md) | Retrieval + grounding design |
| [NCTB_DATA_PIPELINE.md](NCTB_DATA_PIPELINE.md) | Corpus acquisition → retrieval pipeline |

## Operations & compliance

| Doc | Purpose |
|---|---|
| [operations/PRODUCTION_DEPLOYMENT.md](operations/PRODUCTION_DEPLOYMENT.md) | Deployment architecture + procedure |
| [backup_dr.md](backup_dr.md) | Backup and disaster recovery |
| [capacity_plan.md](capacity_plan.md) | Capacity planning |
| [owasp_checklist.md](owasp_checklist.md) | OWASP review checklist |
| [security_scans.md](security_scans.md) | Security scan records |
| [dependency_waivers.md](dependency_waivers.md) | Dependency risk waiver register |
| [type-checking-plan.md](type-checking-plan.md) | mypy strictness plan |
| [scale_report.md](scale_report.md) | Scale audit + local load-test numbers |
| [data_minimization.md](data_minimization.md) | PII minimization policy |
| [dpa_template.md](dpa_template.md) | Data processing agreement template |
| [mobile_release.md](mobile_release.md) | Android/Capacitor release process |
| [hosting_decision.md](hosting_decision.md) | Hosting choices |
| [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md) | Owner launch gates |
