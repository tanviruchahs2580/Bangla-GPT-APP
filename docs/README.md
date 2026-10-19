# Documentation index

Living documentation for the Bangla GPT APP. Point-in-time session and audit
reports are **not** kept here — they live in [`archive/`](archive/) and are
never quoted as current state. There is exactly one current QA record, under
[`qa/`](qa/) (`qa/QA_REPORT_YYYY-MM-DD.md`), superseded and archived when the
next is written.

This page is the curated shortlist; [INDEX.md](INDEX.md) is the full tracked
inventory — every document, one line each — and is the page to check before
adding a file to `docs/`.

## Core

| Doc | Purpose |
|---|---|
| [INDEX.md](INDEX.md) | Full tracked inventory + the `docs/` tree |
| [API.md](API.md) | Generated endpoint reference (regenerate with `apps/api/scripts/gen_api_docs.py`; drift-checked in CI) |
| [architecture.md](architecture.md) | System architecture and decisions |
| [architecture/DATABASE_ARCHITECTURE.md](architecture/DATABASE_ARCHITECTURE.md) | Data model |
| [code-style.md](code-style.md) | House conventions beyond the linters |
| [ci.md](ci.md) | What each workflow checks and how to reproduce it locally |
| [requirements-traceability.md](requirements-traceability.md) | Requirement → test → evidence matrix |
| [testing-strategy.md](testing-strategy.md) | Test pyramid, suites and gates |
| [adr/ADRs.md](adr/ADRs.md) | Architecture decision records (0001–0010; 0011 is a standalone file below) |
| [adr/ADR-0011-data-and-artifact-management.md](adr/ADR-0011-data-and-artifact-management.md) | What lives in git vs out-of-band (corpus, screenshots, evals) |
| [runbook.md](runbook.md) | Operations runbook |
| [route_baseline.md](route_baseline.md) | Route inventory captured 2026-09-11 from the running app — no in-repo generator; re-verify against `/openapi.json` when routes change |
| [qa/QA_REPORT_2026-10-17.md](qa/QA_REPORT_2026-10-17.md) | Current QA record |

## AI / data

| Doc | Purpose |
|---|---|
| [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md) | Retrieval + grounding design |
| [NCTB_DATA_PIPELINE.md](NCTB_DATA_PIPELINE.md) | Corpus acquisition → retrieval pipeline |
| [ai-system-card.md](ai-system-card.md) | AI system card: intended use, data sources, measured evaluation results, failure modes, oversight, update process |
| [threat-model.md](threat-model.md) | STRIDE per trust boundary, OWASP LLM Top 10 (2025) mapping, LINDDUN-lite for minors' data |
| [uiux_renovation_evidence/README.md](uiux_renovation_evidence/README.md) | Why the UI evidence screenshots are committed |

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
| [openssf-self-assessment.md](openssf-self-assessment.md) | OpenSSF Best Practices (passing level) self-assessment with evidence pointers |
| [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md) | Owner launch gates |
