# docs/ index — every living document, one line each

Companion to the curated list in [README.md](README.md): that page says where
to *start*, this page is the map of the whole tracked tree so nothing is found
only by luck. Scope: `git ls-files docs/` — tracked files only. Point-in-time
records and generated files are marked as such and are not held to the current
tree.

Authority: `git ls-files docs/` is the manifest. If a file here is missing from
there (or the reverse), one of the two is stale. `scripts/check_links.py`
(`--anchors`) keeps every relative link on this page honest, and markdownlint
keeps the formatting.

## Tree

```text
docs/
├── README.md                  # curated entry point (read this first)
├── INDEX.md                   # this page: full tracked inventory
├── API.md                     # generated REST reference (do not edit)
├── architecture.md            # system architecture and decisions
├── architecture/              # deeper design records (DB, target state)
├── adr/                       # architecture decision records
├── runbook.md                 # operations runbook
├── operations/                # deployment, SLO, timezone, tracing
├── NCTB_DATA_PIPELINE.md      # corpus acquisition → retrieval
├── RAG_ARCHITECTURE.md        # retrieval + grounding design
├── ai-system-card.md          # AI system card (measured facts only)
├── threat-model.md            # STRIDE + OWASP LLM Top 10 + LINDDUN-lite
├── testing-strategy.md        # test pyramid, gates, traceability
├── requirements-traceability.md  # requirement → test → evidence matrix
├── code-style.md              # language and review conventions
├── ci.md                      # pipeline reference
├── security/                  # security review material (scan records, review)
├── compliance/                # privacy/compliance positions and templates
├── evaluation/                # measured evaluation records
├── qa/                        # ONE current QA record; older ones are archived
├── native-review/             # generated strings for Bangla native review
├── uiux_renovation_evidence/  # committed UI evidence PNGs + why they exist
├── audit/                     # this hardening round's dated report
└── archive/                   # superseded reports (never current state)
```

## Core reference

| Document | What it is |
| --- | --- |
| [README.md](README.md) | Curated documentation index — the entry point for readers |
| [architecture.md](architecture.md) | System architecture, layers, and the decisions behind them |
| [API.md](API.md) | Generated API reference; regenerate with `python apps/api/scripts/gen_api_docs.py` |
| [route_baseline.md](route_baseline.md) | Route inventory captured 2026-09-11 from the running app; re-verify against `/openapi.json` |
| [runbook.md](runbook.md) | Operations runbook: deploy, roll back, diagnose, restore |
| [code-style.md](code-style.md) | House style beyond what the linters enforce |
| [ci.md](ci.md) | What each workflow checks and how to reproduce it locally |
| [requirements-traceability.md](requirements-traceability.md) | Requirement → test → evidence matrix |
| [testing-strategy.md](testing-strategy.md) | Test pyramid, suites, fixtures, and the gates that run them |

## AI, data and correctness

| Document | What it is |
| --- | --- |
| [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md) | Retrieval, chunking, ranking and grounding design with the measured baseline |
| [NCTB_DATA_PIPELINE.md](NCTB_DATA_PIPELINE.md) | Corpus acquisition, QA gates, indexing |
| [ai-system-card.md](ai-system-card.md) | Intended use, data sources, measured evaluation results, failure modes, oversight |
| [threat-model.md](threat-model.md) | STRIDE per trust boundary, OWASP Top 10 for LLM Applications (2025), LINDDUN-lite for minors' data |
| [evaluation/](evaluation/) | Evaluation records and artifacts produced from them |
| [i18n-glossary.md](i18n-glossary.md) | Prescriptive Bangla terminology (the single source of truth for wording) |
| [native-review-sheet.md](native-review-sheet.md) | What a Bangla native speaker must review, and why engineering cannot certify it |
| [native-review/](native-review/) | Generated string collections for that review |

## Operations, security and compliance

| Document | What it is |
| --- | --- |
| [operations/PRODUCTION_DEPLOYMENT.md](operations/PRODUCTION_DEPLOYMENT.md) | Deployment architecture and procedure |
| [operations/SLO.md](operations/SLO.md) | Service level objectives (draft, owner ratification pending) |
| [operations/TIMEZONE.md](operations/TIMEZONE.md) | UTC storage, the clock seam, Dhaka presentation |
| [operations/TRACING.md](operations/TRACING.md) | OpenTelemetry spans and per-stage trace records |
| [backup_dr.md](backup_dr.md) | Backup and disaster recovery (RPO/RTO, restore drills) |
| [capacity_plan.md](capacity_plan.md) | Capacity at 10k / 100k / 1M MAU |
| [security_scans.md](security_scans.md) | Security scan records and triage |
| [security/](security/) | Security review material (review notes, scan outputs) |
| [owasp_checklist.md](owasp_checklist.md) | OWASP Top 10 (2021) review, every line pointing at a control |
| [dependency_waivers.md](dependency_waivers.md) | Risk waivers for dependencies, each with an expiry |
| [compliance/](compliance/) | Privacy positions, data-map material and templates |
| [data_minimization.md](data_minimization.md) | Per-table PII minimization review |
| [dpa_template.md](dpa_template.md) | School ⇄ Bangla GPT data processing agreement template |
| [hosting_decision.md](hosting_decision.md) | Hosting choice record (draft, sign-off pending) |
| [openssf-self-assessment.md](openssf-self-assessment.md) | OpenSSF Best Practices (passing level) self-assessment with evidence pointers |
| [LAUNCH_READINESS_CHECKLIST.md](LAUNCH_READINESS_CHECKLIST.md) | Owner-facing launch gates (legal, UAT, deployment) |
| [mobile_release.md](mobile_release.md) | Android/Capacitor distribution and release |

## Decisions and records

| Document | What it is |
| --- | --- |
| [adr/ADRs.md](adr/ADRs.md) | ADR-0001 … ADR-0010, one per heading, each with Context / Decision / Alternatives / Consequences / Status |
| [adr/ADR-0011-data-and-artifact-management.md](adr/ADR-0011-data-and-artifact-management.md) | What lives in git vs out-of-band (corpus, screenshots, evals) |
| [architecture/DATABASE_ARCHITECTURE.md](architecture/DATABASE_ARCHITECTURE.md) | Data model |
| [architecture/TARGET_ARCHITECTURE.md](architecture/TARGET_ARCHITECTURE.md) | Forward-looking target state (dated 2026-09-14) |
| [qa/QA_REPORT_2026-10-17.md](qa/QA_REPORT_2026-10-17.md) | The single current QA record |
| [audit/2026-10-18-audit-report.md](audit/2026-10-18-audit-report.md) | Dated audit report for the 2026-10 hardening round |
| [uiux_renovation_evidence/README.md](uiux_renovation_evidence/README.md) | Why the UI evidence PNGs are committed instead of LFS/release assets |
| [archive/](archive/) | Superseded reports and point-in-time snapshots — never quoted as current state |

## Keeping this current

```bash
python scripts/check_links.py --anchors   # every relative link and #anchor
npx --yes markdownlint-cli2 "**/*.md"     # the repo's markdown config
```

Add a row here in the same pull request that adds a document, or the next
reader pays for the gap. Generated files (`API.md`, `native-review/`) are
regenerated by their scripts, not hand-edited.
