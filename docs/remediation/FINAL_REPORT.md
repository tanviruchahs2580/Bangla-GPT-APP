# FINAL REPORT — Bangla-GPT-APP V2 Remediation (0.2.0 program)

Terse and factual per V2 §11.3: no scores, no superlatives, no emojis.

## 1. Scope and environment
- Base SHA `31e3e60ba51b9dde54cfbcba0de4466f70c83917` (== origin/main at program start) · work branch `remediation/0.2.0` · verified SHA (T-90 fresh clone) `ef524c6` → repaired `0142c46` → final SHA = this commit (docs differ from the verified SHA; both stated).
- Isolated worktree `C:/Users/DST/AppData/Local/Temp/bgpt-remediation-0.2.0-20261119/worktree`; the original checkout and its untracked `docs/remediation/` preserved untouched (user-selected S-6).
- Windows 11 10.0.26300 · Python 3.12.10 · Node 24.19.0 · npm 11.17.0 · Docker 29.7.2 · interaction mode interactive.
- 32 commits pushed; 4 stacked draft PRs opened (§6.6): #149 (P1→main), #150 (P2→P1), #151 (P3→P2), #152 (P4→P3). The P0 pointer equals origin/main (phase 0 was docs-only in untracked `docs/remediation/`), so no P0 PR exists.

## 2. Finding outcomes (F-01–F-30 + N-findings)
| ID | Final status | Where |
|---|---|---|
| F-01 tracked env/db/logs | REFUTED (as exposure); 1 historical synthetic DB blob documented | T-01, T-10 |
| F-02 NCTB artifacts in public repo | REFUTED as tracking (metadata only); licensing → HO-3 | T-10 inventory |
| F-03 tenant isolation per-handler | CONFIRMED architecture; matrix green (0 leaks) | T-11 |
| F-04 PBKDF2 passwords | REFUTED — Argon2id at OWASP floor already; BC-8 guard added | T-12 |
| F-05 JWT revocation | PARTIAL → role-change rotation ADDED (BC-2); logout/password flows pre-existing | T-13 |
| F-06 MFA not mandatory for admins | CONFIRMED → `MFA_REQUIRED_ROLES` shipped (default off; S-3a) | T-13 |
| F-07 hashed-ngram retrieval | PARTIAL — semantic gap real; identity verification exists; T-26 groundwork | T-26 |
| F-08 eval honesty | PARTIAL → provenance labelling + metrics + human-set scaffolding SHIPPED (T-14); recall claim contradicted by tracked artifact | T-14 |
| F-09 JSON-array relations | CONFIRMED → link tables + dual-write + backfill SHIPPED (BC-5) | T-20 |
| F-10 FK ondelete | REFUTED — 52/52 declare policies (T-01 regex artifact corrected) | T-21 |
| F-11 layering | PARTIAL — measurement recorded; refactor deferred (rationale) | T-22 |
| F-12 LLM gateway | CONFIRMED → provider-reported usage SHIPPED (BC-9); breaker sharing = S-3d | T-23 |
| F-13 safety layer | REFUTED (output screening exists) BUT 4 refusal gaps found by must-sets and FIXED (BC-7) | T-24 |
| F-14 ARQ schedulers in workers | CONFIRMED (inline default) → multi-worker boot refusal (BC-8); arq 0.28.0 verified current | T-32 |
| F-15 frontend debt | PARTIAL — i18n split/typed client deferred; e2e exists (22 specs) | T-25 |
| F-16 no API version prefix | CONFIRMED → /v1 alias SHIPPED (BC-4, ADR-0013) | T-25 |
| F-17 process hygiene | REFUTED (largely) | T-34 |
| F-18 SQLite default | CONFIRMED — Postgres-first compose + CI Postgres suite exist; live topology is an owner item | T-33 |
| F-19 observability | PARTIAL — OTel deferred (lock-regen + S-3); promtool BLOCKED | T-30 |
| F-20 CI thresholds | REFUTED (already gated) → tightened to measured floors | T-16 |
| F-21 app version | REFUTED as "reads 1" (0.15.0) → renumber BLOCKED on store conflict (S-3e) | T-70 |
| F-22 HTTP hardening | REFUTED (largely) — inventory complete; Permissions-Policy → S-3c | T-17 |
| F-23 LLM appsec | REFUTED — 10 boundaries mapped, each pinned by tests | T-27 |
| F-24 object-level authz | PARTIAL → matrix green; N-01 fixed | T-11/T-13 |
| F-25 child-data controls | REFUTED (controls exist + tested); DPIA → HO-3 | T-28 |
| F-26 supply chain | REFUTED — full toolchain in CI | T-29 |
| F-27 production guards | REFUTED — 17 validators (+2 added: hash params, jobs backend) | T-17/T-32 |
| F-28 backups | PARTIAL — DRILL-ONLY restore executed; live topology HO-6 | T-36 |
| F-29 capacity | CONFIRMED unmeasured → measure-only smoke executed (LOCAL/MOCK) | T-37 |
| F-30 routes outside OpenAPI | CONFIRMED bounded (docs routes + /metrics) → classified in the checked-in file | T-11 |

New findings: N-01 (FIXED — role-change epoch rotation), N-02 (FIXED — coverage.xml ignore), N-03 (open, test hygiene), N-04 (open, base-classified STU-16 environment artifact).

## 3. Measured results (each with command + provenance)
- API tests: 2314×2 at baseline; fresh-clone 2568 passed (48.5 min, CI flags) — LOCAL
- API coverage: 89.52% → raised `fail_under` 80→89; fresh clone 89.47%, floors 36/36 — LOCAL
- Web tests: 124 files / 592 passed; coverage 76.65/70.07/72.13/78.84 vs raised floors 76/70/72/78 — LOCAL
- Migration chain: full up/down/up incl. e2f3a4b5c6d7 on SQLite AND PostgreSQL 16 — SQLITE+POSTGRES
- Deletion/erasure parity on Postgres 16: 16 tests — POSTGRES
- Eval gates (golden 427, redteam 36, golden-24) — PASS, MOCK/SYNTHETIC (never live-quality evidence)
- Browser journeys: 212/213 PASS (chromium, LOCAL); single failure base-classified (N-04)
- Capacity smoke: LOCAL/MOCK numbers recorded; rate limits saturate as designed; no capacity claim
- Secret scan: gitleaks 8.30.1 full history — 1176 commits / 30 MB, no leaks

## 4. Behavior changes made (BC-1..BC-11)
BC-1: already present (verified, not changed). BC-2: role change ends sessions (T-13). BC-3: no fixes needed (matrix proved 0 leaks). BC-4: /v1 alias (T-25). BC-5: link tables + dual-write + backfill, JSON read default kept (T-20). BC-6: MFA setting shipped disabled (T-13). BC-7: 4 refusal gaps closed via must-sets (T-24). BC-8: hash-parameter + jobs-backend boot guards (T-12/T-32). BC-9: provider-reported usage (T-23). BC-10: **NOT EXECUTED** — BLOCKED (S-3e; see §8). BC-11: verified rather than changed (T-27).
EG-4 evidence: OpenAPI diff vs T-00 baseline is EMPTY (the /v1 shim is schema-invisible by ADR-0013) — strictly within "only additive /v1 paths + info.version".

## 5. Not verified or blocked (exact human commands)
- T-70 renumber: owner decision S-3e first (options in `evidence/T-70/BLOCKED.md`); then edit declarations + run `python apps/api/scripts/gen_changelog.py`.
- Import-linter locally: `pip install import-linter==2.15` then `lint-imports --config .importlinter` (runs in CI).
- PostgreSQL full-suite locally: set `BGPT_TEST_DATABASE_URL` to a disposable pg16 and run the suite (runs in CI's postgres job).
- promtool alert tests: `promtool test rules deploy/prometheus/rules/*.yml` (or a CI image step).
- N-04 e2e robustness fix: poll settled auth state instead of the URL suffix (frontend stream).
- T-26 model choice (S-4) + T-31 RLS (requires T-26 implementation; schema groundwork documented).

## 6. Human-owned actions (HO-1..HO-9)
HO-1 secrets rotation — none triggered (S-1 never raised). HO-2 branch protection/required checks/CODEOWNERS enforcement + repository visibility decision (PUBLIC; F-02 metadata-only). HO-3 NCTB licensing + DPIA + PDPA legal review. HO-4 human-labelled eval set (schema + README shipped; CI prints HUMAN SET: ABSENT). HO-5 pentest + accessibility audit with real users. HO-6 infrastructure: managed Postgres, real backup verification, capacity sizing from T-37. HO-7 real-device + live-provider tests. HO-8 security contact/disclosure. HO-9 release publication (no tag/release created; store-version decision folded into S-3e).

## 7. Operator actions before deploy
- Run migration `e2f3a4b5c6d7` (additive; reversible).
- New settings shipped at safe defaults: `MFA_REQUIRED_ROLES=""`, `ATTEMPT_LINKS_READ=false`, `JOBS_BACKEND=inline` (multi-worker production now REFUSES inline — set `arq` or one worker).
- Boot guards that can refuse to start: 17 existing validators + hash-parameter floor + jobs-backend; an unrecognized ENV is guarded as production.
- Reconciliation must pass (`reconcile_attempt_links`) before flipping `ATTEMPT_LINKS_READ` (S-3).

## 8. Feature-flag register
| Flag | Defa
| Flag | Default | Enables | Prerequisite (S-3) | Owner |
|---|---|---|---|---|
| MFA_REQUIRED_ROLES | "" | mandatory TOTP per role | S-3a | owner |
| ATTEMPT_LINKS_READ | false | link-table reads | reconciliation green | owner |
| ALLOW_* production escapes | unchanged | pre-existing | pre-existing policy | owner |
| require_human_eval (CLI flag) | off | release gate on human eval set | HO-4 set exists | owner |

## 9. Rollout and rollback sequence
Expand/contract (T-20): deploy + migrate → dual-write active → reconciliation green → [S-3] flip read flag → later release drops JSON columns. Rollback: flip flags off; migration downgrade drops mirror tables only (JSON untouched); full-chain downgrades verified on both engines.

## 10. Residual risks and backlog (priority order)
1. BC-10 version decision (S-3e) — blocks any release naming.
2. Safety classifier model-based stage + breaker sharing (S-3d) — policy decisions.
3. i18n split + generated typed client (T-25 remainder) — frontend program.
4. Two-domain layering refactor (T-22 remainder) — with characterization coverage in place.
5. OTel spans (T-30) — after a lock-regeneration window.
6. N-03/N-04 hygiene fixes.
7. Dependabot majors per T-35 backlog order.

## 11. 1.0.0 readiness checklist
HO-3 (DPIA/licences) · HO-5 (independent pentest + a11y audit) · HO-6 (managed Postgres + verified backups) · HO-7 (device/live-provider) · HO-8 (disclosure policy) · human eval set with interval-width acceptance (HO-4) · S-3a/b/d/e owner decisions · EG-3 on any NEW migrations in the merged PRs.

## 12. Deviations and contradictions
- T-70 BLOCKED (S-3e): the prompt's "declares 1.x" premise is false; 0.15.0 has a published store lineage — renumbering would break Play versionName monotonicity. Inventory prepared; nothing renumbered.
- T-22 refactor deferred (measurement + candidates recorded; import-linter already enforces layering in CI).
- T-25 i18n split + typed client deferred (Bangla regression risk vs behavior-preservation; new-dependency decision).
- T-30 OTel deferred (lock regen + S-3 exporter default); promtool BLOCKED locally.
- Per-module FLOORS file untouched (AGENTS.md reserves it for the QA Engineer); AGENTS.md §11 "fail_under = 80" is now stale (raised to 89) — owner decides whether to update the doc.
- Capture-methodology traps recorded in STATE.md (cmd.exe false positives; bare npm exit 127; /tmp path mangling).

## 13. Version note
Declarations remain 0.15.0 (see §8/§12). Build counters untouched. Store-version risk recorded (S-3e). Tag commands for the human (HO-9), once the version decision lands: `git tag -a v<chosen> <merge-commit> -m "<message>"` after review.

*Every claim maps to evidence under `docs/remediation/evidence/` (INDEX.md) or an H-1 citation; unverified statements are prefixed UNVERIFIED.*
