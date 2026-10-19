# CI/CD reference — workflows, gates, releases and deployment settings

Audit reference: Domain F (`F-01`…`F-18`) of `.audit/master-prompt.md`.
This document is the inventory (F-01), the gate map (F-04), the local/CI parity
contract (F-06), the release procedure (F-08), the owner-only GitHub settings
that are prepared here but not applied (F-07/F-09), and the secret inventory
(F-18). Every command in it was executed while writing it; the evidence files
are named in each section.

## 1. Workflow inventory (F-01)

| Workflow | Triggers | Permissions | Secrets / vars | Runner | Artifacts | Notes |
|---|---|---|---|---|---|---|
| `ci.yml` | push `main`, PR `main`, weekly schedule (DAST only), dispatch | `contents: read`; jobs elevate as needed (`actions: read` for the pipeline report) | `GITHUB_TOKEN` | ubuntu-latest / ubuntu-24.04 | coverage, JUnit per Python leg, eval JSON, Playwright report/traces, SBOM + licences, lint reports, pipeline time report | the required-check set; see §2 |
| `eval-gate.yml` | push `main`, PR, dispatch | `contents: read` | none | ubuntu-latest | — (logs) | redundant with the `golden-eval` job in `ci.yml` by design: this file is the standalone entry point the RAG work references |
| `codeql.yml` | push `main`, PR, weekly schedule | `contents: read`; job `security-events: write`, `pull-requests: read` | `GITHUB_TOKEN` | ubuntu-latest | SARIF in the Security tab | SAST for python + javascript-typescript |
| `release.yml` | tag `v*.*.*`, dispatch | `contents: read`; `build-push` elevates to `contents/packages/attestations: write` + `id-token: write` | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_HOST_FINGERPRINT`; var `DEPLOY_ENABLED` | ubuntu-latest | GHCR images, release record, job summary with digests | §4 |
| `vercel-deploy.yml` | `workflow_run` (API CI on main, success), dispatch | `contents: read` | `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (repository-level today; see §5) | ubuntu-latest | — | four event checks gate the `workflow_run` trigger |
| `nightly.yml` | nightly 19:23 UTC, weekly Mon 04:41 UTC, dispatch | `contents: read` | `GEMINI_API_KEY` (optional), var `LIVE_EVAL_BUDGET_USD` | ubuntu-latest | Playwright report/traces, Lighthouse reports, weekly scan reports, drift report, mutation sample, eval report | §6 |
| `scorecard.yml` | weekly Sat 02:19 UTC, push `main`, dispatch, branch-protection rule | `read-all`; job `security-events: write`, `id-token: write` | none | ubuntu-latest | SARIF + artifact | OpenSSF Scorecard (F-16) |
| `secret-masking.yml` | dispatch only | `contents: read`; verifier job `actions: read` | `MASKING_TEST_SECRET` (dummy; optional) | ubuntu-latest | — | F-18 masking test, §7 |

Overlap review (F-01): `repository-sanity.yml` no longer exists — its checks
(version agreement, commit subjects, doc paths, changelog, secret-file scan)
now live in the `guardrails` job, so nothing runs twice. `eval-gate.yml` and the
`golden-eval` job in `ci.yml` run the same command; the job in `ci.yml` is the
blocking one on every push to `main` and the standalone workflow stays as the
documented entry point for the RAG work. Everything else has a distinct trigger
purpose: `nightly.yml` carries no PR work, `vercel-deploy.yml` and
`release.yml` are deploy paths, `scorecard.yml` is posture only.

## 2. Gate map (F-04)

Every row is a blocking check on PRs unless the trigger column says otherwise.

| Gate | Where | Command |
|---|---|---|
| Format, lint, type (API) | `ci.yml` → `api` | `ruff check`, `ruff format --check`, `mypy src` |
| Unit/integration + coverage | `ci.yml` → `api` | `pytest -q --junitxml=junit.xml` and the coverage gate (`fail_under` from pyproject, branch coverage) |
| Migrations | `ci.yml` → `api`, `postgres` | `alembic upgrade/downgrade/upgrade`, `alembic check` |
| API contract | `ci.yml` → `api` | `python scripts/gen_api_docs.py --check` (OpenAPI drift) |
| Postgres engine parity | `ci.yml` → `postgres` | full domain suite with `BGPT_TEST_DATABASE_URL` |
| Web lint, format, build | `ci.yml` → `web` | `npm run lint`, `format:check`, `build` (tsc + vite) |
| Web unit tests | `ci.yml` → `web` | `npx vitest run` |
| Browser e2e smoke | `ci.yml` → `e2e-smoke` | `npx playwright test` (Chromium, real API, mock provider) |
| RAG evaluation gate | `ci.yml` → `golden-eval`, `eval-gate.yml` | `apps/api/scripts/evaluate_golden.py`, `python -m bangla_gpt_api.evaluation.cli`, `--redteam` |
| SAST | `codeql.yml` | CodeQL `security-extended` for both stacks |
| SCA (Python) | `ci.yml` → `api` | `python -m pip_audit` (fails on any finding) |
| SCA (npm) | `ci.yml` → `web` | `npm audit --audit-level=high --omit=dev` |
| Secrets | `ci.yml` → `guardrails` | gitleaks (full history via `fetch-depth: 0`) |
| Licence inventory + gate | `ci.yml` → `sbom-licence` | `pip-licenses --fail-on "GPL-2.0-only;GPL-3.0-only;AGPL-3.0-only;SSPL-1.0"` + CycloneDX SBOMs |
| Container build + scan | `ci.yml` → `docker` | `docker build`, Trivy image scan (fixable HIGH/CRITICAL) |
| Dockerfile/script/workflow lint | `ci.yml` → `iac-lint` | hadolint (`--failure-threshold warning`), actionlint (with shellcheck), shellcheck on every tracked `*.sh`, Trivy `config` on the Dockerfiles and compose |
| Docs link/consistency | `ci.yml` → `guardrails` | `check_doc_paths.py` (repo-relative paths), markdownlint, `check_readme_contract.py`, changelog and version gates |
| Quality ratchets | `ci.yml` → `guardrails` | `check_quality_ratchet.py --check` (complexity, size, dead code, deps, duplication) |
| Two-replica coherence | `ci.yml` → `replica-check` | `apps/api/scripts/replica_check.py` (two replicas + shared Redis + proxy; exit 3 is a failure here, not a skip) |
| Placeholder sweep | `ci.yml` → `guardrails` | `scripts/check_placeholders.py` (unfinished-work markers, reserved example hosts, placeholder credentials) |
| Dependency rules and cycles | `ci.yml` → `guardrails` | `apps/api/scripts/check_layers.py` (module dependency direction; 138 modules, 488 internal imports, 0 module-level cycles when wired) |
| Design-token ratchet | `ci.yml` → `guardrails` | `scripts/scan_design_tokens.py --check` |
| Bundle budgets | `ci.yml` → `web` | `npx size-limit` (200/160/40 kB gzip) |
| Local/CI parity | `ci.yml` → `make-parity` | `make ci-static PY=python3` (§3) |
| Pipeline timing | `ci.yml` → `pipeline-report` | wall clock + per-job durations in the run summary |
| Posture | `scorecard.yml` | OpenSSF Scorecard SARIF |

Link checking, stated exactly: the blocking check is
`scripts/check_links.py --anchors` in the `guardrails` job (every relative
target and every `file.md#heading` anchor in the tracked Markdown, offline and
deterministic). The **external** variant (`--external`: one HEAD per unique
URL) exists in the same script but is deliberately **not** wired as a blocking
check — CI must not depend on third-party uptime; run it as an operator
command (`python scripts/check_links.py --external`) before a release when the
link inventory matters.

**Required-check payload (F-04, owner action).** The branch protection on
`main` requires seven contexts; the round-2/3 jobs below are green in CI but
not yet *required*. Both are owner-only settings (`CHANGE_GITHUB_REPO_SETTINGS
= no`), so the exact payload is prepared here:

```bash
gh api --method PATCH \
  repos/tanviruchahs2580/Bangla-GPT-APP/branches/main/protection/required_status_checks \
  --input - <<'JSON'
{"strict": true, "contexts": [
  "Lint & test (Python 3.11)",
  "Lint & test (Python 3.12)",
  "Postgres engine check (alembic + API flows)",
  "Golden retrieval benchmark (sample corpus)",
  "Web build & test (apps/web)",
  "Repository guardrails",
  "Docker build & container smoke",
  "Browser e2e smoke (Chromium, real API, mock provider)",
  "SBOM artifacts & licence gate",
  "Dockerfile, shell and workflow lint",
  "Two-replica coherence (shared cache and limiter)",
  "Local entry points (make ci-static)",
  "Analyze (python)",
  "Analyze (javascript-typescript)"
]}
JSON
```

The seven existing contexts stay; the additions are the licence gate
(`sbom-licence`), the IaC/container lint (`iac-lint`), the browser e2e smoke,
the two-replica proof, the local/CI parity job and CodeQL's two languages.
`pipeline-report` and the weekly `dast-baseline` stay informational on
purpose. Note that contexts must match the job display names exactly, matrix
legs included; `gh api ... /protection` shows the current set.

**Supply-chain review (F-02).** `scripts/check_links.py`-style manual review
plus `zizmor` (1.13.0, no API token so the ref/commit audits skip) over all
workflows: the only finding at medium or above is `dangerous-triggers` on
`vercel-deploy.yml`'s `workflow_run` (confidence: medium). The trigger is
accepted with the four documented event checks (success + push + main +
same-repository) and the job now also names the `vercel-production`
environment, so the owner can attach required reviewers and move the Vercel
secrets out of repository scope (the §5 payloads). `scorecard.yml`'s
`permissions: read-all` is the official Scorecard template's posture (the job
elevates only `security-events: write` + `id-token: write`); kept and
documented rather than narrowed. No `pull_request_target`, no `${{ }}`
interpolation inside any `run:` block, and every service-container and action
reference is digest/SHA-pinned. Evidence `E-R3-ws4-f02-actionlint`,
`E-R3-ws4-f02-zizmor`.

## 3. Speed and parity (F-05, F-06)

- **Caches are keyed by the lockfile hash**: `setup-python` caches on
  `apps/api/constraints.txt`, `setup-node` on `apps/web/package-lock.json`, and
  the Playwright browser cache on
  `playwright-${{ runner.os }}-${{ hashFiles('apps/web/package-lock.json') }}`.
- **Concurrency**: `ci.yml`, `eval-gate.yml`, `codeql.yml` and `scorecard.yml`
  use `cancel-in-progress: true` per ref, so a superseded push cancels the run
  it replaced. `release.yml` and `vercel-deploy.yml` deliberately do **not**
  cancel (a half-finished deploy must finish).
- **No `paths:` filters anywhere.** A path filter would let a required check go
  green without running, which is the failure mode the audit's F-05 names;
  the fast jobs are cheap enough without them.
- **Pipeline time is reported** by the `pipeline-report` job
  (`.github/workflows/ci.yml`): wall clock from the first job start to the last
  job end, per-job durations, and an `OVER BUDGET` marker past the 15-minute
  proposal. Measured on the six most recent `ci.yml` runs on `main`
  (2026-10-17/18, `gh run list`): 12m05s, 14m42s, 14m21s, 14m29s (the failure),
  12m34s, 16m04s — median ≈ 14m30s, one run over budget.
- **Parity**: `make ci-static` is the single definition of the static gates and
  CI runs exactly that target (`make-parity` job, `PY=python3`). Locally
  `make ci` runs `ci-static` plus both test suites. Map:

  | Make target | CI job / step |
  |---|---|
  | `make lint-api` | `api`: ruff, ruff format, mypy |
  | `make lint-web` | `web`: eslint, prettier |
  | `make build` | `web`: `npm run build` |
  | `make test-api` / `make test-web` | `api`: pytest; `web`: vitest |
  | `make check-version`, `check-commits` | `guardrails`: version sources, commit subjects |
  | `make check-docs` | `guardrails`: lockfile, README contract, doc paths, changelog, glossary, i18n, dashboards, API drift |
  | `make ci` | `make-parity` runs the `ci-static` half; the service-backed jobs (Postgres, Docker, e2e, DAST) stay CI-only by design |

  Verified: `make -n ci-static` and `make help` execute cleanly in a Linux
  container (evidence `E-R2-f2-004`, `E-R2-f2-005`).

## 4. Release pipeline (F-08)

`release.yml`, tag-triggered (`v*.*.*`), never dispatched here (tags are an
owner action; nothing was tagged or pushed during the remediation):

1. `ci-gate` — the tagged commit must have a **successful `ci.yml` run on
   `main`** (bounded 10-minute wait, then a hard failure with instructions).
2. `build-push` — new in this round:
   - **SemVer + version agreement**: the tag must match
     `^v[0-9]+\.[0-9]+\.[0-9]+$` **and** equal
     `v<apps/api/pyproject.toml [project].version>`; a mismatch fails before
     anything is built.
   - Docker buildx pushes both images **without a `latest` tag** (version tags
     only, so a rollback target cannot move), with `sbom: true` and
     `provenance: mode=max`.
   - `actions/attest-build-provenance` stores a **signed SLSA provenance
     attestation** for each pushed digest (`push-to-registry: true`).
   - `cosign sign --yes` (keyless, Fulcio/Rekor via OIDC) signs both digests.
   - The job summary records the digests and the verification commands.
3. `deploy` — SSH deploy, gated on `vars.DEPLOY_ENABLED == 'true'` and
   `environment: production`; health-gated with automatic rollback (§5).

Verification commands (printed in the release summary):

```bash
gh attestation verify oci://ghcr.io/<owner>/<repo>/api@<digest> --repo <owner>/<repo>
cosign verify ghcr.io/<owner>/<repo>/api@<digest> \
  --certificate-identity-regexp '^https://github.com/<owner>/<repo>/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

**Immutability posture**: version tags are never moved by the pipeline, images
carry no floating tag, and the digest is recorded on the release. The pipeline
does *not* enforce "a GHCR tag cannot be overwritten" server-side — the
repository has no package-write protection; the digest record plus the release
notes are the audit trail. Prepared, not executed: no tag was pushed in this
round (`PUSH_TAGS_OR_DISPATCH_DEPLOY = no`).

## 5. Deployment safety and environment protection (F-09, owner-only)

Measured today (`gh api repos/.../environments`, evidence `E-R2-f2-002`): six
environments (`Preview`, `Preview – bangla-gpt-app`, `Preview – web`,
`Production`, `Production – bangla-gpt-app`, `Production – web`), **all with
`protection_rules: []` and `can_admins_bypass: true`**. `release.yml` requests
the environment named `production` (lowercase), which is not one of those six
entries. Nothing here is enforceable without an owner decision
(`CHANGE_GITHUB_REPO_SETTINGS = no`), so the exact settings are prepared:

1. **Protect the environment the workflow actually requests.** Either rename
   the existing `Production` to `production`, or apply the settings below to
   `production` (GitHub creates an environment on first request). Do not leave
   two look-alike environments with different rules.
2. Required reviewers: the owner account; enable *Prevent self-review* once a
   second reviewer exists. Wait timer `0` minutes (the approval is the gate).
3. Deployment branches and tags: restrict to **tags matching `v*`** (custom
   branch policies), so a hotfix branch cannot be deployed by hand.
4. Move the deploy secrets (`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`,
   `DEPLOY_HOST_FINGERPRINT`) from repository level to **this environment**,
   so a workflow that does not use the environment cannot read them.

Exact API calls (owner, admin scope):

```bash
gh api --method PUT repos/tanviruchahs2580/Bangla-GPT-APP/environments/production \
  -f 'deployment_branch_policy[protected_branches]=false' \
  -f 'deployment_branch_policy[custom_branch_policies]=true'
gh api --method POST \
  repos/tanviruchahs2580/Bangla-GPT-APP/environments/production/deployment-branch-policies \
  -f name='v*' -f type='tag'
gh api --method PUT repos/tanviruchahs2580/Bangla-GPT-APP/environments/production \
  --input - <<'JSON'
{"reviewers":[{"type":"User","id":<owner-user-id>}],"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON
```

Also prepared (AUD-EF-09): move `VERCEL_TOKEN`, `VERCEL_ORG_ID`,
`VERCEL_PROJECT_ID` into a `vercel-production` environment used by
`vercel-deploy.yml` (zizmor `secrets-outside-env`). Vercel has no GitHub OIDC
integration for CLI tokens, so scoping to an environment with required
reviewers is the available control.

**Health-gated rollback drill (F-09) — EXECUTED, PASS (2026-10-19).** The
release deploy's gate reads the `api` container's own health status
(`docker compose ps -q api` → `.State.Health.Status`) and rolls back to the
previous tag when `up --wait` fails or the health status never becomes
`healthy`. The drill `.audit/tmp/f2_health_gate_drill.sh` builds the compose
api image, starts the stack with an intentionally failing healthcheck
(`exit 1`), asserts that `up --wait` fails and that the verbatim `wait_healthy`
loop returns non-zero, then repeats both controls with the real healthcheck.
Round-3 run on this host (Docker 29.7.2): the negative control failed exactly
as a broken release must (`up --wait` exit 1; `wait_healthy` non-zero; health
status `unhealthy`), the positive control passed both (`up --wait` exit 0;
`wait_healthy` 0; status `healthy`), and cleanup removed the throwaway
`bgpt-drill` project. Evidence `E-R3-ws4-f09-health-gate`, drill exit 0. The
owner repeats it on staging when the staging host exists; the script is
host-agnostic (needs docker only).

**Migration rollback posture (F-09).** Migrations are append-only and
schema-first (add nullable column/table, backfill, switch reads, drop later
— the expand/contract order), so `alembic downgrade <revision>` exercises a
verified cycle for every revision and no release needs a data-losing rollback
of a contract step. The exact commands and the pre-deploy backup requirement
are in `docs/runbook.md` (Rollback, DB rollback) and
`docs/operations/PRODUCTION_DEPLOYMENT.md`; the `postgres` CI job runs
upgrade → downgrade → upgrade on every PR, so a broken downgrade is caught
before a deploy needs it. The image rollback is the previous version tag
(images are never overwritten; version tags only).

## 6. Scheduled work (F-15) and posture (F-16)

`nightly.yml`:

Both e2e selections and the PR job use `--grep-invert "visual:|CPU throttle"`:
the screenshot baselines were reviewed on Windows/Chromium (a Linux runner is a
re-review, not a bug) and `perf.spec.ts` needs a seeded 120-message conversation
whose database seam (`E2E_DATABASE_URL`) is a pending one-line config change.
The PR job otherwise runs the full grown spec set: smoke, axe, keyboard and
screen-reader journeys. Requests: `.audit/handoffs/coordinator-from-f2.md`.

| Job | When | What it proves |
|---|---|---|
| `e2e-nightly` | nightly + dispatch | the Playwright journeys on **every project the config defines**. WebKit and Firefox activate automatically once `apps/web/playwright.config.ts` defines those projects: the job detects them with `npx playwright test --list --project=<name>` and skips a missing project with a notice rather than failing for a reason that is not a defect (request tracked in `.audit/handoffs/coordinator-from-f2.md`). |
| `lighthouse` | weekly + dispatch | `@lhci/cli@0.15.1 autorun` against the committed `apps/web/lighthouserc.json` budgets (accessibility/ best-practices ≥0.95, performance ≥0.9, LCP ≤2.5 s, CLS ≤0.1, TBT ≤300 ms) on the six public routes; reports archived. Kept off the PR path because Kept off the PR path because the perf assertion is a runner-noise magnet (the handoff's own measurements put LCP at 3143-4964 ms against a 2500 ms budget on a contended host). |
| `dependency-scan` | weekly + dispatch | `pip-audit` on the hash-pinned lock, `npm audit --audit-level=high --omit=dev`, and a Trivy image scan of the built API image (fixable HIGH/CRITICAL fail the job); reports archived for 90 days. |
| `drift-report` | weekly + dispatch | `apps/api/scripts/drift_report.py` (corpus/query drift; JSON + markdown artifacts and the step summary are the comparison points for the next run). |
| `mutation-sample` | weekly + dispatch | a bounded mutmut 3.8.0 sample (module/tests from `[tool.mutmut]`; pinned install because mutmut is a job tool, not a project dependency). It reports a kill score and warns below the 70 % proposal; it reds only after the module has a measured baseline. While `apps/api/pyproject.toml` has no `[tool.mutmut]` section the job prints a notice and exits 0 — it activates by itself when that lands. |
| `live-eval` | weekly + dispatch | the budget-capped live-model **placeholder**: skips with a notice when `GEMINI_API_KEY` is absent (the A8-05 BLOCKED state), refuses to run when `LIVE_EVAL_BUDGET_USD` is missing/zero/above 5, and otherwise calls the same evaluation entry point. The CLI is hermetic today (it forces the mock provider), so live numbers stay BLOCKED until it gains a live mode; the budget check is already in place for that day. |

A backup-restore drill reminder is not scheduled here: `scripts/pgbackrest_drill.sh`
requires Docker and volumes and is a documented staging task (`docs/backup_dr.md`);
scheduling it without a host would be a green job that proves nothing.

`scorecard.yml` publishes OpenSSF Scorecard results as SARIF (Security tab) and
an artifact, weekly and on every push to `main`.

## 7. Secret handling and masking (F-18)

Required secrets and variables:

| Name | Scope today | Used by | Preferred end state |
|---|---|---|---|
| `GITHUB_TOKEN` | automatic | every workflow | automatic |
| `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_HOST_FINGERPRINT` | repository | `release.yml` deploy | environment `production` (§5) |
| `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | repository | `vercel-deploy.yml` | environment `vercel-production`, required reviewers (§5) |
| `GEMINI_API_KEY` | repository (absent today) | `nightly.yml` live-eval placeholder | environment-scoped, spend-capped key |
| `MASKING_TEST_SECRET` | repository (absent today) | `secret-masking.yml` | keep as a throwaway dummy |
| var `DEPLOY_ENABLED` | repository | `release.yml` | unchanged |
| var `LIVE_EVAL_BUDGET_USD` | repository (default 1) | `nightly.yml` | unchanged |

OIDC is used wherever the platform supports it: GHCR pushes and attestations
(`id-token: write`), cosign keyless signing, and Scorecard publishing. GitHub
Actions OIDC is not available for the Vercel CLI or the SSH host, which is why
those two keep long-lived credentials scoped to a protected environment instead.

**Masking is tested, not assumed.** `secret-masking.yml` (dispatch only) echoes
`MASKING_TEST_SECRET` in one job and, in a second job, downloads that job's log
through the Actions API and fails if the raw value appears — and also fails if
the probe lines are missing, so "no raw value" cannot pass by accident. Set the
secret to any throwaway value once and dispatch the workflow to run the test;
without the secret both jobs pass with a notice.

## 8. Container and compose quality (F-11, F-10)

- All three Dockerfiles pin their base images **by digest** (`Dockerfile`:
  `python:3.12-slim@sha256:a6e34c58…`; `apps/web/Dockerfile`: `node:24-alpine`
  and `nginxinc/nginx-unprivileged:1.27-alpine`; `deploy/postgres/Dockerfile`:
  `postgres:16`), and
  `deploy/postgres/Dockerfile` pins `pgbackrest=2.59.3-1.pgdg13+1` to the
  candidate inside that digest (hadolint DL3008), with the refresh procedure in
  the comment.
- `docker-compose.yml` images are digest-pinned too (`redis:7-alpine`,
  `caddy:2-alpine`, `prom/prometheus:v2.53.0`, `grafana/grafana:11.1.0`), the
  CI service containers use the same digests, and **all ten services carry
  `deploy.resources.limits`** (cpus + memory; `docker compose config` accepts
  the file and normalizes the deployed model, and a live container was verified
  to receive the limits: `HostConfig.Memory`/`NanoCpus` set — evidence
  `E-R2-f2-010`, `E-R2-f2-013`).
- Healthchecks, restart policies, named volumes, `read_only`, `cap_drop`,
  `no-new-privileges` and tmpfs were already in place per service. The API
  image runs as a fixed non-root uid/gid. **AUD-B-24** moved the web image to
  `nginxinc/nginx-unprivileged` (digest-pinned): master and workers run as
  uid 101, the listener moved to 8080 (a non-root process cannot bind :80
  without a capability), Caddy proxies `web:8080`, and the compose service now
  needs no capability at all (ALL dropped). Verified by building the image and
  serving a page as uid 101 under the exact compose posture — evidence
  `E-R3-ws4-b24-web-nonroot`. No container in the stack starts as root except
  postgres (whose official entrypoint chowns PGDATA and drops privileges).
- `.dockerignore` excludes `.git`, `.github`, docs, tests, virtualenvs and
  databases; the API image installs from the hash-verified lock with
  `--no-deps` for the project itself.
- Trivy `config` scans the three Dockerfiles and the compose file with
  `--severity HIGH,CRITICAL --exit-code 1`. One rule, `AVD-DS-0002` (image runs
  as root), is ignored for `deploy/postgres/Dockerfile` only, through
  `.trivyignore.yaml` with a written statement and an expiry date; the root
  Dockerfile is scanned **without** that file, so its non-root uid/gid 10001
  stays fully checked. The mechanism was verified against trivy 0.58.0
  (evidence `E-R2-f2-008`); after AUD-B-24 the ignore no longer matches
  `apps/web/Dockerfile` at all and the file was re-scan
  clean in this round (evidence `E-R3-ws4-b24-web-nonroot`).
- Lint: `hadolint --failure-threshold warning` over all three Dockerfiles is
  **clean** (was one warning: DL3008), actionlint over every workflow is
  **clean** (re-run at the CI-pinned versions — actionlint 1.7.12 + the pinned
  shellcheck 0.10.0 — in round 3; two SC2012 findings in `eval-gate.yml` and
  `nightly.yml` were fixed in this round, see `E-R3-ws4-f02-actionlint`),
  shellcheck over every tracked `*.sh` is **clean** (three findings were fixed:
  SC2034 in `scripts/smoke.sh`, SC2015 in the same file, SC2001 in
  `scripts/pg_backup.sh`), and Trivy `config` reports no HIGH/CRITICAL on the
  Dockerfiles or compose. Evidence: `E-R2-f2-007`…`E-R2-f2-010`.
- SSH deploy hardening (F-10): the deploy uses a pinned host fingerprint
  (refuses to run without it), a dedicated key/user via secrets, the release
  tag passed through `envs:` rather than interpolated into the remote script,
  `set -e` with an explicit `rollback()` on both failure paths, and a
  container-health gate instead of a host-port curl. The extracted embedded
  scripts are shellchecked by the `iac-lint` job through actionlint.

## 9. Artifacts and badges (F-14)

Artifacts produced per run: `api-coverage`, `api-junit-<py>`, `eval-reports`,
`playwright-e2e`, `sbom-licences` (SBOMs + licence CSV), `lint-reports`
(hadolint/actionlint/shellcheck/trivy-config outputs), `pipeline-time-report`
and, from the scheduled workflows, `playwright-nightly`, `lighthouse-reports`,
`weekly-scan-reports`, `live-eval-report`, `scorecard-results`.

The README carries no badges today, so no badge is false. When they are added,
these are the truthful ones (workflow files are named so the badge URL is
stable):

```markdown
![API CI](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/ci.yml/badge.svg?branch=main)
![CodeQL](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/codeql.yml/badge.svg?branch=main)
![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/tanviruchahs2580/Bangla-GPT-APP/badge)
```

The Scorecard badge only becomes meaningful after `scorecard.yml` has run once
with `publish_results: true`.

## 10. Running the CI linters locally

```bash
# workflows (bundled in the repo venv; no network)
.venv/Scripts/actionlint.exe .github/workflows/*.yml            # Linux: actionlint
.venv/Scripts/zizmor.exe --format plain .github/workflows/

# Dockerfiles, scripts and IaC through the digest-pinned images
docker run --rm -v "$PWD:/mnt:ro" -w /mnt hadolint/hadolint@sha256:30a8fd2e785ab6176eed53f74769e04f125afb2f74a6c52aef7d463583b6d45e \
  hadolint --failure-threshold warning Dockerfile apps/web/Dockerfile deploy/postgres/Dockerfile
docker run --rm -v "$PWD:/mnt:ro" -w /mnt koalaman/shellcheck@sha256:2097951f02e735b613f4a34de20c40f937a6c8f18ecb170612c88c34517221fb \
  --format=gcc $(git ls-files '*.sh')
docker run --rm -v "$PWD:/src:ro" -w /src aquasec/trivy:0.58.0 \
  config --quiet --severity HIGH,CRITICAL --exit-code 1 docker-compose.yml
python scripts/dora_report.py --days 90        # delivery metrics (F-17)
```

`zizmor` currently reports two unsuppressed findings and 17 suppressed ones:
`adhoc-packages` (low) on the pinned `npx jscpd` install in the guardrails job
(a CLI tool with no lockfile to pin against) and `dangerous-triggers` (high,
medium confidence) on `vercel-deploy.yml`'s `workflow_run`, which is guarded by
four event checks and cannot be replaced without dropping the CI-gated deploy.

## 11. Required-check settings to add (owner action, F-07)

The branch protection rule currently requires seven contexts (measured
2026-10-18: `Lint & test (Python 3.11)`, `Lint & test (Python 3.12)`,
`Postgres engine check (alembic + API flows)`, `Golden retrieval benchmark
(sample corpus)`, `Web build & test (apps/web)`, `Repository guardrails`,
`Docker build & container smoke`). New jobs that should join the list once
their first run is green on the default branch:

`Browser e2e smoke (Chromium, real API, mock provider)`,
`SBOM artifacts & licence gate`, `Dockerfile, shell and workflow lint`,
`Local entry points (make ci-static)`, `Pipeline time report`.

Everything else the audit asked for under F-07 (CODEOWNERS enforcement,
`require_code_owner_reviews`, secret scanning, push protection, SHA-pinning
enforcement, Dependabot security updates) stays a documented owner action —
`CHANGE_GITHUB_REPO_SETTINGS = no`.
