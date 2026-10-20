# Executed command ledger — audit waves 2–4 (J-03)

Status: compiled by R4-wsC (2026-10-20). Every row is a command documented in
the repo's operational docs together with an actual execution of it during the
audit, and the recorded outcome. Guards: `check_links.py` /
`check_doc_paths.py` / `gen_api_docs.py --check` run in CI on every push, so a
doc that starts naming a wrong path or a dead link fails the build; this file
records the runs themselves.

| # | Documented command (source doc) | Executed | Result |
|---|---|---|---|
| 1 | `docker compose config -q` — compose file validity (docs/PRODUCTION_DEPLOYMENT.md prep) | R2/R4 CI + locally | OK |
| 2 | production compose boot: pg profile → `alembic upgrade head` → `docker compose up` per docs/PRODUCTION_DEPLOYMENT.md §3 (per deploy/DEPLOYMENT.md) | R3 wave-4/5 (E-R3-prod-boot.txt + E-R3-prod-boot-health.json, E-R3-prod-boot-401.json) | `/health` 200 `{"status":"ok"}`; `/status` 4 components ok; unauth `POST /tutor/ask` → 401 problem+json; `/metrics` 403 under `METRICS_REQUIRE_AUTH=true` |
| 3 | `python apps/api/scripts/soak.py --minutes 30 --rate 6 --sample-seconds 30` (docs/operations/SOAK.md) | R3-ws5 | 10806 requests, 0 transport/5xx, RSS 38–110 MiB no upward trend, p95 46–105 ms; +32-client ramp, no saturation; two driver findings found and fixed in the same change (ai_max_conversation_messages disabled by the driver; stream/ask shared in-flight counter measured) |
| 4 | `python apps/api/scripts/soak.py --minutes 3 ...` fix verification re-run | R3-ws5 | stream 181×200 / 0×429 after the driver fix |
| 5 | `python apps/api/scripts/soak.py --minutes 10 --rate 6 --sample-seconds 20 --ramp-top 24 --ramp-seconds 30 --port 8130` (docs/operations/SOAK.md) | R4-wsC (this ledger's own run, .audit/evidence/R4-wsc-i08/) | see the JSON/log beside this file — recorded with the same driver post-fix |
| 6 | `python apps/api/scripts/profile_report.py --iterations 60 --top 20` (docs/operations/PROFILE.md) | R3 | tutor ask 19.68 ms/call; uncached dashboard 10.17 ms/call |
| 7 | `python apps/api/scripts/profile_report.py --iterations 20 --top 10 --out <evidence>` | R4-wsC (.audit/evidence/R4-wsc-i07) | tutor ask 25.52 ms/call; uncached dashboard 14.16 ms/call (shared CI host); comfortably inside the documented ≤ 300 ms non-LLM budget |
| 8 | `python apps/api/scripts/backup_restore_drill.py` (docs/backup_dr.md sqlite rehearsal) | R4-wsC | DRILL PASSED: online backup → restore verified (integrity, FK, row counts, post-checkpoint marker); bare-file-copy trap demonstrated; pgBackRest wipe-and-restore remains the owner-run step per the doc |
| 9 | `npx playwright test e2e/smoke.spec.ts` (apps/web README / testing docs; CI e2e-smoke job) | R3 | 5 passed |
| 10 | `npx playwright test e2e/screen-reader.spec.ts` (docs/frontend-accessibility.md) | R3 | login tree + language switch ok; `-g 'announced exactly once'` → 1 passed (6.8 s) |
| 11 | e2e crawl of every route (`apps/web/e2e/crawl.spec.ts`) — D-16 | run by the ci.yml e2e-smoke job on every push | green in CI; runs against a real API |
| 12 | `python apps/api/apps/api/scripts/gen_api_docs.py --check` (docs/API.md header) | CI on every push + R4-wsC locally | "docs/API.md matches the OpenAPI schema (245 table rows rendered)" — drift fails the build |
| 13 | eval CLI: `python -m bangla_gpt_api.evaluation.cli …` / golden eval (docs/RAG_ARCHITECTURE.md, NCTB_DATA_PIPELINE.md) | R2/R3 waves; eval harness runs (mock provider) | golden/retrieval evals executed; live-model run blocked on provider key — tracked as issue #49 |
| 14 | `pip-compile --generate-hashes …` (apps/api README on constraints.txt) | R3 (constraints.txt committed, 2582 sha256 pins) | lockfile gate: `check_lockfile.py` = "satisfies all 39 declared dependencies" (re-checked R4-wsC) |
| 15 | `make ci-static PY=python3` — the local parity command the Makefile documents (J-09) | every CI push (make-parity job "Local entry points (make ci-static)") | success (latest run 39366476370, 2026-10-20) |
| 16 | `make setup/dev/test/lint/build/ci` (root README) | not executed as make targets on this host — Windows host has no make; every command behind those targets was executed directly (ruff/mypy/pytest/packaging) and the parity job proves the Makefile wiring | recorded honestly with the known Windows caveat (devcontainer covers Linux-first flows) |
| 17 | `python scripts/check_glossary.py`, `check_links.py`, `check_doc_paths.py`, `check_dashboards.py`, `check_placeholders.py`, `check_commits.py`, `check_pr_title.py`, `check_quality_ratchet.py`, `check_coverage_floors.py` (referenced from docs/CONTRIBUTING + ci.yml) | R4-wsC, all locally | results recorded across this wave's evidence files (glossary 0 violations; links 143 ok; paths 443 ok; dashboards 23 exported; placeholders 0; commits 0 errors; ratchet dead-code green at min-confidence 60) |
| 18 | promtool check rules (docs/operations/SLO.md references) | NOT executed — promtool is not installed on the audit host; fallback validation performed: alerts.yml parses and all its series names are exported by the dashboards (`check_dashboards.py`: "all 23 bgpt_* metric references … are exported") | recorded honestly |

## Known-failures found by executing doc commands (and their fixes)

- The R3 compose smoke initially failed to boot the API (E-18's finding) —
  fixed and re-executed end-to-end with the health/401/metrics probes listed
  in row 2 (E-18 is PASS).
- A doc-path guard failure (ADR-0012 named `apps/api/scripts/gen_api_docs.py` instead
  of `apps/api/scripts/gen_api_docs.py`) was fixed in R3; the guard now passes
  ("all 443 repo-relative paths named across 164 markdown files exist").

## Remaining doc commands with no executed run (honest list)

- pgBackRest wipe-and-restore drill (docs/backup_dr.md) — needs an isolated
  Docker host; owner-run step; the sqlite rehearsal (row 8) is the executed
  counterpart.
- promtool rule check (row 18) — tool absent; fallback validation done.
- `make` targets on a native Windows shell (row 16) — make absent; devcontainer
  is the supported path.
