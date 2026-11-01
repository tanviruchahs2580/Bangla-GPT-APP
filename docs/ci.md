# CI: what runs, what gates, and how to reproduce it

One page for the question "why is this red?" — every workflow in
`.github/workflows/`, what triggers it, what blocks a merge, and the local
command that reproduces it. Product-side gates live in
`CONTRIBUTING.md` ("Definition of done"); this file is the pipeline view.

## Blocking a pull request

`ci.yml` ("API CI") runs on every PR to `main` and is the gate that must be
green. Its jobs:

| Job | What it proves | Reproduce locally |
|---|---|---|
| `api` | lint, format, mypy, tests, coverage floor, `pip-audit`, import-linter contracts, `alembic` check, import smoke | `cd apps/api && ruff check . && ruff format --check . && mypy src && pytest` |
| `quickstart-windows` | the README PowerShell quick start runs on `windows-latest`: venv, hash-locked install, dev-server `/health`, `npm ci` + build, then the visual regression matrix (the baselines are Windows-rasterised by design) | the README "Quick start" PowerShell block, run on Windows |
| `postgres` | the same domain suite on the engine production runs, plus migration drift | `BGPT_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bgpt_test pytest` |
| `sbom` | CycloneDX manifests for the python lock and the installed web tree | `cd apps/api && python -m cyclonedx_py requirements constraints.txt --output-format JSON --output-file sbom-python.json` |
| `web` | `tsc && vite build`, vitest, type-aware ESLint, prettier | `cd apps/web && npm run build && npm test && npm run lint && npm run format:check` |
| `guardrails` | the repo's own doc/contract checks (see below) | the `apps/api/scripts/check_*.py` scripts |
| `e2e` | Playwright journeys + axe sweeps on a served build (chromium) | `cd apps/web && npm run test:e2e` |
| `e2e-engines` | the Bangla shaping/`Intl` specs on chromium, firefox and webkit (pull requests only) | `cd apps/web && npx playwright install firefox webkit --with-deps && npx playwright test -c playwright.engines.config.ts` |
| `docker` | the API image builds and boots | `docker build .` |

`codeql.yml` (SAST) and `eval-gate.yml` also run on PRs. `eval-gate.yml` is
three blocking steps now: the golden v2 suite against the committed baseline,
the 24-question golden retrieval gate
(`python scripts/evaluate_golden.py`, from `apps/api`) and the red-team
moderation gate (`python -m bangla_gpt_api.evaluation.cli --redteam`).

### Repository guardrails

`guardrails` is the only job that fails for documentation reasons, so its
failure text is worth reading rather than re-running:

- `check_doc_paths.py` — every repo-relative path named in a markdown file
  must exist (this catches a doc that describes a file somebody renamed)
- `check_changelog.py` — every commit must be covered by `CHANGELOG.md`;
  regenerate with `python apps/api/scripts/gen_changelog.py`
- `check_readme_contract.py`, `check_proxy_contract.py`,
  `check_lockfile.py` — README/edge-proxy/dependency-pin contracts
- the inline `README and docs/ci.md agree with the workflows` step — every
  workflow file must have a row in this table and in the README's CI table,
  each row must name every job id, and the triggers must match the workflow's
  own `on:` block

## Monitoring production

- `uptime.yml` probes `https://bangla-gpt-app.vercel.app/api/health` on a
  schedule and fails loudly when the API origin behind the edge proxy stops
  answering. GitHub throttles schedules (observations of five-hour gaps on a
  `*/15` cron), so treat it as a backstop, not as a p50 detector. Repair
  procedure: `docs/runbook.md`, "API origin down".
- `scorecard.yml` runs OpenSSF Scorecard weekly and on every push to `main`,
  and publishes its SARIF into the repository's Security tab next to the
  CodeQL alerts. It needs no repository secrets (the run is proved by
  keyless OIDC), so a low score is a finding about the repository's
  configuration, not about a missing credential.
- `release.yml` runs on a `v*.*.*` tag: it requires green CI for the tagged
  commit, builds and pushes both images, creates the GitHub Release, scans
  the pushed digests and only then deploys.

## Secret handling and masking

GitHub masks repository secrets in logs. That is a platform claim, and
`secret-masking.yml` turns it into a test you can run instead of trusting it:

1. Create a repository secret named `MASKING_TEST_SECRET` with **any
   throwaway value** — its content is irrelevant and must never be a real
   credential. It exists only to be echoed into a job log and then searched
   for.
2. Run the workflow (`Actions → Secret masking verification → Run workflow`).
3. The second job downloads the first job's log through the Actions API and
   asserts the raw value is absent. If the value appears, masking is broken
   and the run fails; if the secret is not configured, both jobs pass with a
   notice, so the check is a no-op rather than a permanent red.

It is dispatch-only on purpose: a scheduled echo of a secret value into a log
adds no information after the first verification, and the log is retained
either way.

## What is deliberately not automated

- Play Store uploads — the Android release workflow builds and signs the
  bundle, and the account, listing and rollout decision stay with the owner
  (the store runbook ships with the mobile release pack).
- Live-model latency/quota measurement — needs a real key and money; the
  committed golden set measures retrieval offline instead.
- FCM push — not implemented anywhere (`docs/mobile_release.md`), so no job
  claims to test it.
