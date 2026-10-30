# Contributing

Thanks for working on Bangla GPT APP. This file is short on purpose: it states
only the rules that the CI cannot enforce for you.

## Before you start

- Open an issue first for anything beyond a small fix, so the approach is
  agreed before the work is done.
- `main` is the integration branch. Branch from it, never commit to it
  directly.
- Participation is covered by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), which
  also states the project-specific rule about children's data.

## Setup

1. **API** — the README "Quick start" carries the exact commands for both
   PowerShell and Linux; CI runs the same two steps (`pip install
   --require-hashes -r constraints.txt`, then `pip install --no-deps -e
   ".[dev]"`). Python 3.11+ is required.
2. **Web** — `npm ci` in `apps/web` (Node 24 / npm 11; `.nvmrc` pins 24).
3. **Optional but recommended** — `pip install pre-commit && pre-commit
   install`: the hook set is a subset of CI and catches whitespace, JSON/TOML
   and private-key problems before the push. `.pre-commit-config.yaml` states
   what is deliberately left to CI and why.
4. **Or in one step** — `make setup` runs 1–3 (GNU make + bash; see the
   Makefile header for the other targets).

A fresh-clone bootstrap was measured end-to-end on 2026-10-30 (Windows 11,
Git Bash, warm pip cache, ≈10.8 GiB free): clone 5 s → `python -m venv .venv`
40 s → hash-locked install 263 s → editable install 24 s → `npm ci` 226 s →
`npm run build` 65 s, ≈21 minutes in total, and the dev server answered
`/health` and `/ready` 200 at the end. Disk after the installs: venv 258 MB,
`apps/web/node_modules` 348 MB, `dist/` 4 MB. A cold pip/npm cache adds to the
two install steps; CI runs the same commands in the `quickstart-windows` job.

## Branches and commits

```
git switch main && git pull
git switch -c fix/short-description
```

- One logical change per branch. A branch that fixes a bug and reformats the
  world cannot be reviewed.
- Commit messages: a subject line under ~72 characters in the imperative
  ("Add retry to the ingestion worker"), then a blank line, then the body.
  Explain *why* — the diff already says *what*. Reference the issue or the
  finding id when one exists (`Refs: #123`).
- Commit with a GitHub noreply address (`<id>+<user>@users.noreply.github.com`),
  not a personal one. A personal address in the author field is permanent in
  published history (GIT-09/F-103); `.mailmap` maps the historic address for
  display only, it does not rewrite the commits.
- Do not commit secrets, `.env` files, real student data, or generated
  artefacts. `.env.example` is the template; copy it to `.env` locally.

## Definition of done

CI must be green on your branch. That means, at minimum:

| Check | Command | Notes |
| --- | --- | --- |
| API lint + format | `ruff check .` and `ruff format --check .` | `ruff format .` then re-check |
| API type check | `mypy src` | From `apps/api` — matches the CI step |
| API tests | `pytest` | Add tests for behaviour you change |
| API tests on Postgres | `BGPT_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bgpt_test pytest` | Optional locally, required in CI. Runs the same domain suite on the engine production uses, with per-test truncation isolation (`tests/conftest.py`); the CI `Postgres engine check` job runs it automatically |
| Dependencies | `pip-compile --generate-hashes --allow-unsafe --extra dev --strip-extras` | Regenerate `constraints.txt` when `pyproject.toml` changes — the guardrails job fails if a declared dependency is missing or its pin violates the declared specifier |
| Migrations | `alembic check` | Schema and models must not drift |
| Web tests | `npm test` | vitest |
| Web build | `npm run build` | `tsc && vite build` — typecheck included |
| Web lint | `npm run lint` | ESLint, type-aware, `--max-warnings 0` |
| Web format | `npm run format:check` | prettier — run `npm run format` to fix |

Both web checks run in the `Web build & test (apps/web)` CI job.

The prettier row used to be a trap: `npm run format:check` failed on six
files, nothing in CI ran it, and this table is the stated definition of
done. The files are now formatted and the check is wired into CI, so the
claim is true. ESLint is likewise committed and enforced — an earlier
version of this document said the config "is not committed yet", which
stopped being true in 2026-10 and was not corrected.

### Dependency changes

The API's dependencies are declared in `apps/api/pyproject.toml`, but what actually gets
installed is pinned in `apps/api/constraints.txt`, which carries a hash per
artifact. CI and the Dockerfile both install from it, so a given commit always
builds the same dependency set.

When you change `pyproject.toml`, regenerate the lock in the same pull request:

```
pip install pip-tools
cd apps/api
pip-compile --generate-hashes --allow-unsafe --extra dev --strip-extras
```

The `guardrails` job runs `apps/api/scripts/check_lockfile.py`, which fails if a
dependency declared in `pyproject.toml` is missing from the lock or if its pinned
version violates the declared specifier — so `redis>=5.0,<6` cannot coexist with
a pinned `redis==8.1.0`.

It does **not** compare the whole lock against a fresh `pip-compile` run: that
comparison is not reproducible against a live index (two clean resolves minutes
apart legitimately differ) and it used to fail on untouched, valid locks. Nor
does it check that transitive pins agree with each other — installing the lock
(`pip install --require-hashes -r constraints.txt`, which every build and test
job does) is what proves that. That install is the step that caught the redis/arq
conflict; this gate exists so the same mistake fails in the cheap job, with a
message that names the package and the fix.

Because the lock carries hashes, pip runs in hash-checking mode; the project
itself is therefore installed separately with `--no-deps` (a local directory has
no single artifact to hash). Keep that two-step shape if you change the install
commands.

### Base image updates

The `Dockerfile` pins `python:3.12-slim` to a digest, and the two explicitly
installed Debian packages to the versions that digest resolves to. To move the
base, re-resolve both and change them together:

```
docker run --rm --entrypoint sh python:3.12-slim@sha256:<digest> \
  -c "apt-get update -qq && apt-cache policy openssl libssl3t64"
```

Never replace the digest with the tag.

If you change `apps/api/src/bangla_gpt_api/db/models.py`, add a migration in
the same pull request. CI runs `alembic check`, which fails when the models and
the migration history disagree.

## Pull requests

- Target `main`. One pull request per branch.
- Fill in what changed and how it was verified. "Ran the tests" is not
  verification; "757 passed, new test asserts X fails without the fix" is.
- Screenshots for UI changes; a request/response pair for API changes.
- If you change a public API contract, update the OpenAPI-derived docs and the
  changelog in the same pull request.

## Merge policy

Check the repository settings before relying on this section: merge methods
and branch protection are configured on the server, not in the repository,
and this file can drift from them.

The intended policy, and what CI enforces by review rather than by
configuration:

- **Squash merge** for feature branches, so `main`'s history stays readable
  and each merge has one Conventional-Commits subject.
- Delete the branch after merge.
- Only maintainers merge to `main`, and production deploys only after the
  full gate is green on `main`.

What is actually configured today is in `.github/` and in the repository
settings, not here; see `docs/LAUNCH_READINESS_CHECKLIST.md` for the items
that still need a maintainer with admin scope.

Pull-request review is required for changes under `apps/api/src` and anything
that touches authentication, PII handling, migrations, or CI configuration.

## Code style

Match the surrounding code. The linters are configured in `apps/api/pyproject.toml`;
when a suppression is genuinely necessary, put the reason in the comment — an
unexplained `# noqa` or `# type: ignore` will be asked about in review.

### File names

A `_v2` suffix marks the second generation of a suite or dataset
(`test_cache_v2.py`, `eval/golden_v2.json`, `eval/redteam_v2.json`,
`eval/baseline_v2.json` and their siblings). The base name is intentionally
absent: the first generation was replaced rather than kept side by side, and
the QA reports and the eval-gate job refer to these names, so rename only with
every reference updated in the same change.

## Repository size

Fourteen tracked files exceed 500 KB (8.4 MB total, measured 2026-10-30): nine
Playwright visual-regression baselines under
`apps/web/e2e/__screenshots__/visual.spec.ts/` and five renovation-evidence
screenshots under `docs/uiux_renovation_evidence/wave4/after/`. Decision
(2026-10-29): keep them in git — the baselines make visual regressions
reviewable and refreshable, and the evidence set is the durable record of that
UI pass. Re-run the inventory (`git ls-files` + file sizes) when the baselines
are regenerated; the count moves with them. The `check-added-large-files`
pre-commit hook caps **newly added** files at 512 KB (it inspects added files
per commit), so a new large file needs an explicit decision recorded here, not
a silent `--no-verify`.

## Security issues

Do not open a public issue for a vulnerability — this project holds personal
data about children. Report it privately through
[SECURITY.md](SECURITY.md), which documents the reporting channel, the
response targets and the scope.

## Licence

By contributing you agree that your contributions are licensed under the MIT
licence of this repository. Bundled third-party material keeps its own
licence — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
