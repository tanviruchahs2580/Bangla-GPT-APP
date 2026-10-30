# Test runtime budgets

How long each test layer may take, so suite bloat is visible instead of
discovered on a slow afternoon (F-197, TEST-14). Numbers are ceilings, not
targets; the CI job timeouts are the hard stop.

## Budgets

| Layer | Local budget | CI job timeout | Where the number comes from |
|---|---|---|---|
| API unit suite (`pytest` in `apps/api`) | 15 min | 30 min (`.github/workflows/ci.yml`, api job) | ~8 min per full run on GitHub runners per the job comment; the 15 min local ceiling leaves room for a laptop working while the suite runs |
| API with coverage (`--cov-branch`) | 20 min | same 30 min | a second full run in the same job |
| Web unit suite (`npm run test:coverage`) | 5 min | 20 min (web job) | 73 files, `--no-file-parallelism` in CI |
| E2E smoke (`npm run test:e2e`, chromium) | 20 min | 40 min (e2e job) | server bring-up + seeded journeys |
| Postgres parity job | 30 min | 45 min (postgres job step timeout) | migrations + smoke + race/tenancy batches |
| Guardrails (ruff/mypy/radon/vulture/import-linter/semgrep/hadolint) | 3 min | 15 min (guardrails job) | tool installs dominate |

Measured reference points (this host, 2026-10-30): the SSE contract file 16 s,
four provider/health files 53 s, env parity suite 6 s, a full API run minutes
under `-n 8` while other agents used the box.

## What to do when a layer exceeds its budget

1. Look for the class of test that grew, not the slowest single test: a new
   family of fixtures that rebuilds the app per test usually doubles a file.
2. Prefer a shared session fixture or a smaller corpus over deleting coverage.
3. If the growth is inherent (a new layer of integration coverage), raise the
   budget in the same change as the tests, with the measurement that justifies
   it, and note it in the PR.

## How each layer is run

`CONTRIBUTING.md` documents the exact commands per layer (API, web, e2e,
Postgres) and the Makefile targets wrap them.
