# Audit V2 remediation plan — Enterprise V2 (2026-11-14)

Source: `Bangla_GPT_Backend_Database_Engineering_Audit_Enterprise_V2_2026.md`
(reviewed commit `8cc65a4`). This document is the executed triage: what this
wave implements, what is documented as an owner decision, and what stays in
the report's own Phase 1–2 backlog. Facts only; every claim carries its
evidence in the linked items.

## Wave v0.11.2 — executed now (Phase 0, code-executable items)

### 1. BGPT-SEC-001 (P1, confirmed defect) — TOTP seed encryption at rest

- Domain-separated Fernet key derived from `PII_ENC_KEY` via HKDF-SHA256
  (info `bangla-gpt:totp-seed:v1`) — the PII key is never used directly for
  TOTP ciphertext, and no new boot secret is required (the production guard
  already refuses to boot without `PII_ENC_KEY`).
- Ciphertexts carry a version prefix (`totp1:`) = key/version metadata;
  rotation procedure documented (issue `v2` label, dual-read, sweep).
- Write path encrypts (`POST /auth/mfa/verify`); read path decrypts for the
  challenge; legacy plaintext rows pass through on read and are lazily
  upgraded on the next successful challenge; a bounded startup sweep
  encrypts remaining plaintext rows (the report's backfill, run with full
  app config instead of an env-blind migration).
- Decryption failure is fail-closed (MFA challenge fails; nothing logged
  but the event name — no seed material anywhere).
- GDPR export: verified the user block carries only id/email/role/
  created_at — no seed material (gdpr.py export V2 user dict).
- Tests: ciphertext-at-rest, round-trip challenge, legacy passthrough +
  lazy upgrade, startup sweep, keyless-dev warning, no-seed-in-logs.

### 2. BGPT-DATA-001 (P1, confirmed defect) — mastery reconciliation contract

Measured finding that reframes the fix: `ConceptMastery.correct/total` are
**already durable lifetime aggregates** — the quiz-grading path increments
them database-side per graded attempt (knowledge.py `increment`). The defect
is the nightly `refresh_mastery()`, which **overwrites** those aggregates
from the retained answer-log window; after the 730-day purge it would shrink
lifetime totals (or leave stale rows when no retained rows remain).

Fix (the report's recommended reconciliation semantics, lifetime contract):

- `refresh_mastery` never shrinks: it creates missing chapter-root
  concepts/rows (kept), tops a row **up** to the retained-window aggregate
  when the stored counters are lower (monotone self-heal for lost updates),
  and never writes a smaller value. Purged history can no longer erase
  aggregates.
- New `reconciled_at` column (migration) = the report's
  last-reconciled timestamp; `NULL` = not yet reconciled.
- Tests (report §8.3 acceptance criteria, adapted): old+new boundary
  stability across a retention run; only-old-purged concept keeps its
  totals; lost-update heal; post-purge no-shrink; consumer verdict parity;
  new-cell creation. Same tests run under the CI PostgreSQL suite.

### 3. BGPT-OPS-001 (P1) — deployment contract and receipt

- Authoritative targets stated in `docs/runbook.md` §7.1: API = single-host
  operator-run container swap (the documented live topology); web = Vercel
  production deploy. The release workflow's SSH job is not the deployment
  path for this topology.
- This wave ships a deployment receipt: merge commit → image tag → running
  container digest → `/ready` smoke, recorded in the final report and
  runbook.

### 4. BGPT-RAG-001 (P1) — fail-closed corpus gate wiring

The copyrighted corpus cannot be committed to CI (AGENTS §8). The eval
workflow now reports an explicit, non-confusable corpus-gate status per
run, and fails closed when a configured corpus artifact is absent or its
digest mismatches (opt-in artifact provisioning via repository
configuration). Provisioning the artifact itself is the remaining owner
action — recorded in the backlog, not silently skipped.

### 5. Small confirmed items executed with the wave

- BGPT-RAG-003: current citation-verdict behavior traced and pinned by test.
- BGPT-REL-002: scheduler mode declared at startup (one owner per topology).
- BGPT-SEC-004: registration `disclose` posture documented as the accepted
  trade-off with compensating controls (owner acceptance recorded).

## Owner-decision backlog (not silently deferred — dated plan)

| Item | Phase (report) | Owner decision needed | Next concrete step |
|---|---|---|---|
| BGPT-PRIV-001 (P1 launch gate) | 0 | Accountable privacy owner; DPIA scope | Data inventory from models.py table list → counsel review |
| BGPT-RAG-001 corpus artifact | 0 | Where to host the restricted corpus | Owner provisions access-controlled storage; then the wired gate goes mandatory |
| BGPT-DATA-002 | 1 | quiz_attempts retention window | Retention matrix draft after DATA-001 lands |
| BGPT-DATA-003 | 1 | JSON schema-version policy | Add `schema_version` to ai_jobs payloads first |
| BGPT-DB-001 | 1 | Deployment topology cap | Pool budget table (replicas × workers × pool) |
| BGPT-DB-002 | 1 | Migration window policy | Per-migration lock/timeout preflight template |
| BGPT-SEC-002 | 1 | none (engineering) | Generate 140-operation matrix; negative tests per family |
| BGPT-SEC-003 | 1 | Audit sink choice | DB-role privilege separation first |
| BGPT-SEC-005 | 1 | Infra evidence pack | Operator-run evidence collection |
| BGPT-API-001/002/003 | 1 | Mobile compat window | Operation catalogue from OpenAPI fixture |
| BGPT-RAG-002 | 1 | Human review panel | Bengali eval set v1 (owner-approved labels) |
| BGPT-REL-001/003 | 2 | Durable worker adoption | ARQ worker topology decision |
| BGPT-PERF-001 | 2 | Capacity target scenario | Mixed-workload k6 suite design |
| BGPT-OPS-002/003 | 2 | Drill window; SLO approval | Restore drill on disposable copy; SLO proposal review |
| BGPT-ENG-001/002, SUPPLY-001 | P3 | Refactor window | Model split by bounded context; advisory register |

## Release rule for this wave

Version `0.11.2` (patch — data-correctness and security hardening, no API
contract change). Full CI gate set, merge, tag, Release & Deploy, live
container swap with deployment receipt, APK rebuild for version sync,
as-a-user regression before the final report.
