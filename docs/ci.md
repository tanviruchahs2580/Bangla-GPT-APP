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
| `eval` | the eval-gate workflow (`eval-gate.yml`) called as a reusable workflow — golden v3 suite, 24-question retrieval gate, red-team moderation gate. Called here so the gates sit on a **required** context's critical path (see "Owner action required" below) | `cd apps/api && python -m bangla_gpt_api.evaluation.cli && python scripts/evaluate_golden.py && python -m bangla_gpt_api.evaluation.cli --redteam` |
| `sbom` | CycloneDX manifests for the python lock and the installed web tree | `cd apps/api && python -m cyclonedx_py requirements constraints.txt --output-format JSON --output-file sbom-python.json` |
| `web` | `tsc && vite build`, vitest, type-aware ESLint, prettier — and it `needs: eval`, so a red eval leaves this required check unstarted rather than green | `cd apps/web && npm run build && npm test && npm run lint && npm run format:check` |
| `guardrails` | the repo's own doc/contract checks (see below), plus the NCTB corpus manifest and content-QA gates | the `apps/api/scripts/check_*.py` scripts; `make corpus-check` |
| `e2e` | Playwright journeys + axe sweeps on a served build (chromium) | `cd apps/web && npm run test:e2e` |
| `e2e-engines` | the Bangla shaping/`Intl` specs on chromium, firefox and webkit (pull requests only) | `cd apps/web && npx playwright install firefox webkit --with-deps && npx playwright test -c playwright.engines.config.ts` |
| `docker` | the API image builds and boots | `docker build .` |

`codeql.yml` (SAST) and `eval-gate.yml` also run on PRs.
`eval-gate.yml` also runs standalone on PRs, and `ci.yml` calls it as a
reusable workflow (`workflow_call`) from the `eval` job. Both paths are
deliberate: the standalone run keeps the `Golden-set regression gate` check
name on PRs (so it can be made a required context exactly as named), while
the call makes the required `web` job wait for it.
On a schedule, `retrieval-eval.yml` re-measures the real-corpus retrieval
baseline (`data/nctb/retrieval_eval.json`) against the committed artifact
(`apps/api/scripts/check_retrieval_baseline.py`); the copyrighted corpus is
not distributed with the repo, so a runner without it skips with a notice
instead of pretending, and the run summary records that the gate did not run.
A manual dispatch can point it at a corpus the operator provides
(`corpus_archive_url` or `corpus_path`), and `require_corpus: true` makes a
missing corpus a failure instead of a skip. `eval-gate.yml` is
three blocking steps now: the golden v3 suite (427 items,
`eval/golden_v3.json`) against the committed `eval/baseline_v3.json`,
the 24-question golden retrieval gate
(`python scripts/evaluate_golden.py`, from `apps/api`) and the red-team
moderation gate (`python -m bangla_gpt_api.evaluation.cli --redteam`).

### Owner action required: required status checks (CI-FIX-003)

Branch protection's required contexts currently cover only the `ci.yml` jobs
plus the CodeQL analyses. `Golden-set regression gate`, the two Playwright
jobs and `SBOM` are **not** required, so on their own they cannot block a
merge. The `web` job's `needs: eval` (above) closes the eval gap for merges
through the required `Web build & test` context; making the remaining checks
required is a repository-settings change that only the owner can perform —
do not run it as part of a code change:

```bash
# Read-modify-write: add the missing contexts without dropping the rest of
# the protection object. Requires admin on the repository (gh auth status).
gh api repos/tanviruchahs2580/Bangla-GPT-APP/branches/main/protection \
  > /tmp/protection.json

jq '.required_status_checks.contexts += [
      "Golden-set regression gate",
      "E2E (playwright, chromium)",
      "E2E (playwright, three engines)",
      "SBOM (CycloneDX, python + web)"
    ] | .required_status_checks.contexts |= unique' \
  /tmp/protection.json > /tmp/protection-new.json

gh api --method PUT repos/tanviruchahs2580/Bangla-GPT-APP/branches/main/protection \
  --input /tmp/protection-new.json

# Verify (must list all contexts, old and new):
gh api repos/tanviruchahs2580/Bangla-GPT-APP/branches/main/protection \
  --jq '.required_status_checks.contexts[]'
```

Notes for whoever runs it: (1) check the names against a real PR first — a
required context that never reports blocks every merge; (2) if the API
rejects the body because the repository uses the newer `checks[]` form, edit
`.required_status_checks.checks` the same way instead of `contexts`; (3)
`E2E (playwright, three engines)` only runs on pull requests by design, so a
required check by that name blocks merges to `main` unless the owner accepts
that (merge commits from PRs still produce it; direct pushes do not).

### Repository guardrails

`guardrails` is the only job that fails for documentation reasons, so its
failure text is worth reading rather than re-running:

- `check_doc_paths.py` — every repo-relative path named in a markdown file
  must exist (this catches a doc that describes a file somebody renamed)
- `check_changelog.py` — every commit must be covered by `CHANGELOG.md`;
  regenerate with `python apps/api/scripts/gen_changelog.py`
- `check_readme_contract.py`, `check_proxy_contract.py`,
  `check_lockfile.py` — README/edge-proxy/dependency-pin contracts
- the NCTB corpus gates (CI-FIX-001): `check_corpus_manifest.py` verifies the
  tracked corpus artifacts (manifest, acquisition ledger, quality report,
  retrieval-eval digest) on every run, and — when the copyrighted corpus is
  present — that the served chunks are the manifest's; `content_qa.py report`
  runs per source against `data/nctb/normalized/nctb-*.chunks.jsonl`. On a
  fresh clone the corpus is absent and both emit an explicit `::notice::`
  saying the real-corpus leg did NOT run — a green guardrails job never
  claims the corpus gates ran.
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


## Automatic merging

`automerge.yml` arms GitHub's native auto-merge on every non-draft PR aimed at
`main` (re-armed idempotently on every push to the PR). The merge itself stays
with branch protection: it lands only when all eight protected status checks
pass and is held while any of them is red, so the automation adds convenience
without owning a merge decision of its own. Fork PRs are excluded by the
same-repo guard, and the required-check list -- not this workflow -- is what a
change must satisfy to reach `main`.
## What is deliberately not automated

- Play Store uploads — the Android release workflow builds and signs the
  bundle, and the account, listing and rollout decision stay with the owner
  (the store runbook ships with the mobile release pack).
- Live-model latency/quota measurement — needs a real key and money; the
  committed golden set measures retrieval offline instead.
- FCM push — not implemented anywhere (`docs/mobile_release.md`), so no job
  claims to test it.
