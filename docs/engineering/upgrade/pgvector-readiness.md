# Pgvector production readiness record

**Assessment date:** 2026-11-16  
**Decision:** **NO-GO — production activation is not authorized and is not ready on the evidence reviewed.**  
**Scope:** Repository evidence review only. No live host, database, container, CI service, secret, or raw corpus was queried or changed.

## Decision summary

The repository records a real local pgvector staging exercise and contains a configured pgvector CI integration-test step. Those facts support implementation readiness for a staging lane, not production activation. Checked-in operations documentation still describes the live API as SQLite with in-process hybrid retrieval; current live posture was not independently verified for this assessment. Production pgvector serving is explicitly recorded as blocked pending infrastructure and owner decisions.

The 1,598 count appears in committed corpus/evaluation artifacts, and a dated staging report states that generation `gen-44dc63b55c85` was built, validated and activated in a local pgvector container. The report is a repository-recorded claim, not a captured database/registry dump or raw command output. The committed CI workflow proves configuration, not the latest CI run. No automated assertion was found that compares the persisted generation's IDs/count/digest to a fresh serving-loader result or verifies production-vs-pgvector serving parity.

Accordingly, **do not switch production serving, provision/alter production infrastructure, or run a production migration on the strength of this record.** The host, migration rehearsal, tested restore/rollback path and explicit owner activation decision remain prerequisites.

## Readiness matrix

| Area | Status | Evidence and boundary |
|---|---|---|
| Checked-out production posture | **Verified in repository; live not verified** | The V5 system design records production as SQLite with in-process hybrid retrieval and pgvector production serving blocked ([`system-design.md`](../rag-v5/system-design.md#L64)). The V5.5 staging report says the production default remains SQLite + in-process hybrid ([`staging-retrieval-report.md`](../rag-v5/staging-retrieval-report.md#L68)). These are repository statements, not a query of the live host on 2026-11-16. |
| Local pgvector staging run | **Reported / not independently verified here** | The dated report says a local `pgvector/pgvector:pg16` container ran on port 5433, the Alembic chain was applied, and the pgvector integration tests passed 5/5 against the extension ([`staging-retrieval-report.md`](../rag-v5/staging-retrieval-report.md#L8)). No container logs or raw test output were found in the checked-in evidence. |
| 1,598-chunk corpus/index | **Partially verified** | The committed corpus manifest records `index_chunks: 1598`, an index hash, embedder identity and evaluation timestamp ([`corpus_manifest.json`](../../../data/nctb/manifests/corpus_manifest.json#L314)). The committed retrieval-evaluation artifact also records 1,598 corpus/index chunks ([`retrieval_eval.json`](../../../data/nctb/retrieval_eval.json#L1)). These artifacts establish recorded counts, not a pgvector registry row or current active pointer. The staging report attributes `gen-44dc63b55c85` and activation to its local run, but that remains report-level evidence ([`staging-retrieval-report.md`](../rag-v5/staging-retrieval-report.md#L14)). |
| Pgvector CI integration gate | **Verified in repository; latest run not verified** | The Postgres CI job declares `pgvector/pgvector:pg16` ([`ci.yml`](../../../.github/workflows/ci.yml#L321)) and sets both `DATABASE_URL` and `BGPT_PGVECTOR_TEST_URL` before invoking `pytest tests/test_pgvector_store.py` ([`ci.yml`](../../../.github/workflows/ci.yml#L385)). The staging report documents that this gate had previously been skipped and says the workflow was fixed ([`staging-retrieval-report.md`](../rag-v5/staging-retrieval-report.md#L57)). The V5.5 execution log reports later green CI, but no raw CI run result was independently retrieved for this assessment ([`execution-log.md`](../rag-v5/execution-log.md#L44)). |
| Migration coverage | **Verified in repository; live migration not verified** | CI declares an Alembic upgrade/downgrade/upgrade cycle and `alembic check` against its Postgres service ([`ci.yml`](../../../.github/workflows/ci.yml#L363)). This is configuration evidence; it does not prove a production migration rehearsal or current live schema state. |
| Serving/data parity | **Partially verified; equality not demonstrated** | The staging report says the generation used the serving-parity loader and describes its dedupe, exclusion and class-attribution behavior ([`staging-retrieval-report.md`](../rag-v5/staging-retrieval-report.md#L14)). The build CLI uses the serving loader by default, but the repository review did not find a test comparing persisted pgvector IDs/count/digest against a fresh serving-loader output or asserting equivalent production and pgvector results. The staging measurements are labeled provisional because there are no human-reviewed labels ([`staging-retrieval-report.md`](../rag-v5/staging-retrieval-report.md#L1)). |
| Backup/restore for a Postgres topology | **Reported local drill; not live production evidence** | The backup/DR document reports a local Docker pgBackRest full-volume restore drill passing on 2026-09-07 ([`backup_dr.md`](../../backup_dr.md#L57)). That document also says the live API does not run this Postgres/pgBackRest topology and has no pgBackRest stanza ([`backup_dr.md`](../../backup_dr.md#L6)). |
| Live SQLite backup/restore | **Reported snapshot restore tests; full DR drill not demonstrated** | The risk-acceptance register records nightly SQLite snapshots and a `restore_test` pass dated 2026-11-14, while explicitly saying no full restore/DR drill on the live SQLite topology has been completed ([`audit-v2-risk-acceptances.md`](../audit-v2-risk-acceptances.md#L55)). A snapshot integrity/row-count check is not a full recovery drill with measured RPO/RTO. |

## Activation prerequisites

Before reconsidering production activation, the owner/operator should record evidence for each item below. This list is a readiness gate, not authorization to perform the work.

1. **Provision and approve the target Postgres/pgvector host.** Record its supported engine/extension versions, access boundary, operational ownership and recovery objective. The current design identifies the host as an infrastructure blocker ([`system-design.md`](../rag-v5/system-design.md#L72)).
2. **Rehearse migrations on a disposable environment matching the target.** Include extension availability, clean upgrade, supported rollback/recovery path, and `alembic check`; retain command output and resulting schema/version evidence. Do not use production for rehearsal.
3. **Rebuild and validate from the serving loader on that target.** Preserve generation identity, source digest, embedder identity/dimension, chunk count, validation result and active-pointer evidence. Resolve any manifest/loader discrepancy before activation; the V3 checkpoint records a 1,605-vs-1,598 mismatch ([`CHECKPOINT.md`](../../rag/v3/CHECKPOINT.md)).
4. **Add an automated parity assertion.** Compare the generation stored in pgvector to a fresh serving-loader result using stable chunk IDs/count/digest and explicitly test filters and serving behavior. Record a retrieval evaluation on human-reviewed labels; current staging probes are explicitly provisional.
5. **Prove rollback and recovery on the target topology.** Run a full isolated restore/recovery drill, measure RPO/RTO, exercise the previous-generation pointer rollback and document operator commands. A local Postgres drill does not substitute for the target/live topology.
6. **Review production data and operational controls.** Confirm backup encryption/retention, least-privilege credentials, monitoring/alerting, capacity, network boundaries and incident/rollback ownership without exposing credentials in this document.
7. **Obtain explicit owner approval for a canary and activation.** Record the approved scope, success/stop criteria, observation window and rollback authority. Until this decision is documented, keep the existing SQLite/in-process serving default.

## Go / no-go criteria

**Current result: NO-GO.** A future GO decision requires all of the following to be evidenced and reviewed:

- a production-capable Postgres/pgvector host is provisioned and approved;
- migration and generation build/validation are rehearsed against a disposable equivalent;
- the active generation's persisted digest/count/IDs match serving-loader output;
- human-reviewed retrieval evaluation meets the existing gates without baseline manipulation;
- backup, full restore, rollback and RPO/RTO are demonstrated for the target topology;
- monitoring, access, privacy and operational ownership are reviewed;
- the owner explicitly authorizes a canary, and the canary meets its predeclared acceptance/stop criteria.

Any missing, stale or report-only prerequisite keeps the decision **NO-GO**. This record does not change runtime configuration, production topology, migration state, corpus, evaluation baselines or rollout authorization.

## Open decisions

These need an owner; this record makes none of them:

1. **Provisioning and activation** — whether to procure/approve a production Postgres/pgvector host at all, and on what budget and recovery objective (prerequisite 1).
2. **Embedder choice** — a real multilingual embedding model remains a staging human decision (`EMBEDDING_MODEL` is empty by design); any change is a manifest-breaking event that would require a full corpus rebuild and re-validation before it could be considered for production.
3. **Parity assertion ownership** — who implements the automated persisted-generation-vs-serving-loader comparison (prerequisite 4) and where it runs (CI vs a scheduled job).
4. **Live-topology DR drill** — whether to schedule the full restore/rollback drill on the actual live topology, which the runbook documents but no exercise has covered.

## Evidence register

Primary repository sources reviewed on 2026-11-16:

- [`docs/engineering/rag-v5/system-design.md`](../rag-v5/system-design.md) — declared lane topology and production blocker.
- [`docs/engineering/rag-v5/staging-retrieval-report.md`](../rag-v5/staging-retrieval-report.md) — provisional local staging generation and CI-step correction.
- [`docs/engineering/rag-v5/execution-log.md`](../rag-v5/execution-log.md) — repository-recorded operational/CI history; not raw host or CI output.
- [`data/nctb/manifests/corpus_manifest.json`](../../../data/nctb/manifests/corpus_manifest.json) and [`data/nctb/retrieval_eval.json`](../../../data/nctb/retrieval_eval.json) — committed generation/corpus counts and evaluation metadata, not pgvector runtime state.
- [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) — declared pgvector service, migration cycle and integration-test command.
- [`docs/backup_dr.md`](../../backup_dr.md), [`docs/runbook.md`](../../runbook.md) and [`docs/engineering/audit-v2-risk-acceptances.md`](../audit-v2-risk-acceptances.md) — documented Postgres and SQLite recovery procedures/status.
- [`docs/rag/v3/CHECKPOINT.md`](../../rag/v3/CHECKPOINT.md) — recorded manifest/loader discrepancy.

No live-environment verification, CI-provider query, database query, container inspection, migration execution, deployment, or infrastructure change was performed for this record.
