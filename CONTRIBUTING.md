# Contributing

Thanks for working on Bangla GPT APP. This file is short on purpose: it states
only the rules that the CI cannot enforce for you.

## Before you start

- Open an issue first for anything beyond a small fix, so the approach is
  agreed before the work is done.
- `main` is the integration branch. Branch from it, never commit to it
  directly.
- One command sets the toolchain up (Python 3.12 + Node 24, pinned in
  `.python-version`, `.nvmrc` and `.tool-versions`):

  ```text
  make setup     # venv + hash-verified Python deps + npm ci
  make test      # the real test suites; make test-fast for the guardrail subset
  make ci        # every CI check that needs no external service
  ```

  The same environment is described for editors in `.devcontainer/` and
  `.editorconfig`. `make help` lists every target; a POSIX shell (Git Bash on
  Windows) and GNU make are required.

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md) in every
project space.

## Branches and commits

```sh
git switch main && git pull
git switch -c fix/short-description
```

- One logical change per branch. A branch that fixes a bug and reformats the
  world cannot be reviewed.
- Commit messages: a subject line under ~72 characters in the imperative
  ("Add retry to the ingestion worker"), then a blank line, then the body.
  Explain *why* — the diff already says *what*. Reference the issue or the
  finding id when one exists (`Refs: #123`).
- Do not commit secrets, `.env` files, real student data, or generated
  artefacts. `.env.example` is the template; copy it to `.env` locally.

The 72-character limit and the Conventional Commits shape are checked by
`scripts/check_commits.py` (`make check-commits`): structure violations fail,
over-length subjects warn on history but fail in CI for a pull request's own
commits (`--strict-length` over the PR range). The check arrived after most of
the current history was written and history is not rewritten, so older commits
legitimately do not satisfy the length rule; new commits must.

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

```sh
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

```sh
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

## Audit trail and traceability

Reviews depend on being able to reconstruct *why* a change exists. Keep the
trail in the pull request itself; external documents are not searchable from
the change:

- **Findings and issues.** Name the finding ids a change addresses
  (`Refs: AUD-JK-07`, `Closes #42`) in the commit body and in the PR body's
  "Findings addressed" section. A change that fixes something the tracker
  does not name should say so explicitly.
- **Evidence.** For a measurable claim, state the command and the before/after
  numbers ("pytest 1106 passed, 6 skipped"; "recall@1 0.38 → 0.51,
  `data/nctb/retrieval_eval.json`"). A number without a command and a date is
  not evidence.
- **Risk and rollback.** One short section per PR: what could go wrong, how it
  is detected, and how to undo it (revert commit, flag, migration downgrade).
- **Decisions.** A choice another engineer could reasonably have made
  differently gets an ADR under `docs/adr/` (numbered, with Context / Decision
  / Alternatives / Consequences / Status) or a paragraph in the PR body that
  the ADR record can quote later.
- **Deferred work.** Anything found but not fixed becomes an issue with
  acceptance criteria, not a comment in a closed PR.

The audit's own ledgers (`.audit/`, a work-in-progress artifact set from the
2026-10 hardening round) are not the long-term tracker: the issue tracker is.

## Branch model and merge policy

Check the repository settings before relying on this section: merge methods
and branch protection are configured on the server, not in the repository,
and this file can drift from them.

The intended policy, and what CI enforces by review rather than by
configuration:

- `main` is the only long-lived branch and the only deployment source.
- Feature work happens on topic branches (`fix/…`, `feat/…`, `chore/…`,
  `docs/…`, `ci/…`) and lands through a pull request.
- **Squash merge** for feature branches, so `main`'s history stays readable
  and each merge has one Conventional-Commits subject.
- Delete the branch after merge (the repository already sets
  `delete_branch_on_merge`), and remove a stale branch once its commits are in
  `main`.
- Only maintainers merge to `main`, and production deploys only after the
  full gate is green on `main`.

What is actually configured today, verified 2026-10-18 at commit `0b7dfe6`: the
repository allows merge commits, squash merges and rebase merges at the same
time, and the history contains nine `Merge pull request #N` commits, so the
squash-only intent above is *not* enforced by configuration. The remote
carries 30 heads — 12 already merged into `main` (including
`backup/pre-qa-2026-10-16`), 18 not, 14 of those Dependabot branches — and the
local clone has 13. The full inventory is recorded at
`.audit/evidence/E-FIX-JK-009-stale-branches.txt` as the pruning baseline.
Changing repository settings or deleting remote branches needs maintainer
admin scope — both are listed as owner actions in
`.audit/handoffs/ef-from-jk.md`.

Pull-request review is required for changes under `apps/api/src` and anything
that touches authentication, PII handling, migrations, or CI configuration.

## Code style

Match the surrounding code. The linters are configured in `apps/api/pyproject.toml`;
when a suppression is genuinely necessary, put the reason in the comment — an
unexplained `# noqa` or `# type: ignore` will be asked about in review.

## Security issues

Do not open a public issue for a vulnerability — this project holds personal
data about children. Report it privately through
[SECURITY.md](SECURITY.md), which documents the reporting channel, the
response targets and the scope.

## Licence

By contributing you agree that your contributions are licensed under the MIT
licence of this repository. Bundled third-party material keeps its own
licence — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
