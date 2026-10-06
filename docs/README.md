# Documentation index

Living documentation for the Bangla GPT APP. Point-in-time session and audit
reports are **not** kept here — they live in [`archive/`](archive/) and are
never quoted as current state. There is exactly one current QA record
(`qa-audit-YYYY-MM-DD.md`), superseded and archived when the next is written.

## Core

| Doc | Purpose |
|---|---|
| [API.md](API.md) | Hand-written endpoint reference |
| [architecture.md](architecture.md) | System architecture and decisions |
| [architecture/DATABASE_ARCHITECTURE.md](architecture/DATABASE_ARCHITECTURE.md) | Data model |
| [adr/ADRs.md](adr/ADRs.md) | Architecture decision records |
| [runbook.md](runbook.md) | Operations runbook |
| [route_baseline.md](route_baseline.md) | Generated route inventory (regenerate after route changes) |
| [qa-audit-2026-10-06.md](qa-audit-2026-10-06.md) | Current critical QA record |

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
| [data_minimization.md](data_minimization.md) | PII minimization policy |
| [dpa_template.md](dpa_template.md) | Data processing agreement template |
| [mobile_release.md](mobile_release.md) | Android/Capacitor release process |
| [hosting_decision.md](hosting_decision.md) | Hosting choices |
| [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md) | Owner launch gates |
