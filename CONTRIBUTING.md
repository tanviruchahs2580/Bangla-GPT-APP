# Contributing

Thanks for working on Bangla GPT APP. This file is short on purpose: it states
only the rules that the CI cannot enforce for you.

## Before you start

- Open an issue first for anything beyond a small fix, so the approach is
  agreed before the work is done.
- `main` is the integration branch. Branch from it, never commit to it
  directly.

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
- Do not commit secrets, `.env` files, real student data, or generated
  artefacts. `.env.example` is the template; copy it to `.env` locally.

## Definition of done

CI must be green on your branch. That means, at minimum:

| Check | Command | Notes |
| --- | --- | --- |
| API lint + format | `ruff check .` and `ruff format --check .` | `ruff format .` then re-check |
| API tests | `pytest` | Add tests for behaviour you change |
| Migrations | `alembic check` | Schema and models must not drift |
| Web tests | `npm test` | vitest |
| Web build | `npm run build` | `tsc && vite build` — typecheck included |
| Web format | `npm run format:check` | prettier |

An ESLint config is not committed yet (tracked as AUD-0009), so the web checks
above are what CI can actually run today.

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

The repository currently allows all three merge methods (squash, merge,
rebase) and does not auto-delete branches. Recommended practice until the
maintainers tighten it:

- **Squash merge** for feature branches, so `main`'s history stays readable.
- Keep the branch name meaningful; it is deleted after merge.
- Only maintainers merge to `main`.

Pull-request review is required for changes under `apps/api/src` and anything
that touches authentication, PII handling, migrations, or CI configuration.

## Code style

Match the surrounding code. The linters are configured in `apps/api/pyproject.toml`;
when a suppression is genuinely necessary, put the reason in the comment — an
unexplained `# noqa` or `# type: ignore` will be asked about in review.

## Security issues

Do not open a public issue for a vulnerability. Contact the maintainers
privately; see the repository's security policy if one is published.

## Licence

By contributing you agree that your contributions are licensed under the MIT
licence of this repository. Bundled third-party material keeps its own
licence — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).