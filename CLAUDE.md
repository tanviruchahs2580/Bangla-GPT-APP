# Bangla GPT — Claude Code instructions

@AGENTS.md

`AGENTS.md`, imported above, is the project contract: all of it applies to
Claude Code and it wins over this file. This file adds only what is specific
to Claude Code and to this Windows workstation (measured 2026-11-20; re-check
before quoting a number).

## Not on this machine

- `~/.zcode/AGENTS.md`, `~/.zcode/skills/safe-db-migration` and the
  `Bangla-GPT-Frontend-Studio` marketplace (AGENTS.md §16) belong to a ZCode
  setup that is not installed here. Do not search for them or wait on them.
- For migrations use the project skill `/safe-db-migration`, which applies §10.
- For frontend work keep §16's order (read-only audit, spec, plan,
  **user-approved** implementation, independent review, visual QA, release
  check before hand-off) with Claude Code's own tools in place of the ZCode
  `/frontend-*` commands.

## Workstation

| Item | State |
| --- | --- |
| Python | Repo venv `.venv/` at the root, built from **3.12.10** to match CI. The machine-wide `python` is **3.14**: never use it for the API. |
| Node / npm | 24 / 11; `apps/web/node_modules` installed with `npm ci` |
| GitHub | `gh` is authenticated (repo and workflow scopes) |
| `make` | Not installed. The recipes that matter are written out in `/gates`. `make seed` is broken: its path `../apps/web/e2e/` does not exist from `apps/api`. |
| Not installed | Docker, Java/Gradle/adb, gitleaks, semgrep, Lighthouse, Playwright browsers, psql, sqlite3, redis-server, hadolint, Trivy, syft, cyclonedx-py, a Python 3.11 interpreter |
| Not in the venv | radon, vulture, setuptools (CI installs them at run time) |
| NCTB corpus | Absent: `data/nctb/` holds manifests and reports only. Local retrieval and eval run on the bundled 78-chunk sample; the real-corpus retrieval regression runs nowhere. |

Jobs that need a missing tool (docker image, Android build, gitleaks,
Playwright e2e, the Postgres leg, Redis, the 3.11 leg) run only in CI. Report
them as "not run locally", never as passed.

- `PYTHONUTF8=1` is set for Claude's shells in `.claude/settings.json`.
  Without it Windows Python writes Bangla through cp1252 and fails with
  `UnicodeEncodeError`; CI on Linux is UTF-8 already.
- pre-commit is installed for the `pre-commit` and `commit-msg` stages only.
  `pre-push` is left out: its gitleaks hook would fail every push without the
  gitleaks binary. Run mypy, eslint and prettier yourself (`/gates`) before
  proposing a push.
- Before any commit, `git config user.email` must be the GitHub noreply
  address (CONTRIBUTING.md, "Branches and commits"). Never commit with a
  personal address.
- The Browser pane's `api` entry starts uvicorn from `apps/api`, so its
  database is `apps/api/bangla_gpt.db`. That file starts empty. Teacher, parent
  and admin accounts cannot be self-registered, so seed it before testing those
  screens with `apps/web/e2e/seed_e2e_users.py`, and verify the exact command
  first.
- Test runs can create `apps/api/bangla_gpt.db` (the dev default, picked up
  during collection). It is gitignored; delete it after a run.

## Working agreement

1. Branch from `main`; never commit to it.
2. Run `/gates` before calling a change done, and report real numbers
   ("N passed, M skipped"), as CONTRIBUTING.md asks of a pull request.
3. Commit subjects follow Conventional Commits (the commit-msg hook checks).
   CI's changelog check wants every commit listed in `CHANGELOG.md`, which
   `apps/api/scripts/gen_changelog.py` regenerates; that is a separate commit,
   made only when the user asks (AGENTS.md §11).
4. `.claude/settings.json` turns AGENTS.md §14 into prompts. These ask first:
   pushing; `gh pr create` and `gh pr merge`; every `gh api` call (reads too);
   `gh workflow run`; releases; reading or editing a real `.env*` file;
   `alembic revision`, `upgrade` and `downgrade`, including scratch databases;
   deleting or renaming branches; `git … --output`; editing the lock, eval
   baselines, corpus manifests, retrieval reports, CHANGELOG, AGENTS.md,
   coverage ratchets, migrations or CI workflows. `*.db` files and keystores
   cannot be read at all: treat them as PII artefacts (§15).
5. Run `/code-review` before opening a PR, and `/security-review` for anything
   touching authentication, PII, migrations or CI.
6. UI checks use the Browser pane with the `web` (5173) and `api` (8000)
   launch entries. AgroBridge also uses 5173, so stop it first (§3).
   Viewport emulation is not native Android verification (§16).
7. The Sentry connector is for read-only investigation. Its organization has
   no projects for this app today, so it shows nothing for Bangla GPT. Ask
   before changing alert rules or issue state.
8. Automerge: `automerge.yml` merges every non-draft PR to `main` as soon as
   the 8 required checks pass, with no approval, and the e2e job is not
   required. Open PRs as drafts (`gh pr create --draft`) and keep them draft
   until the user says to mark them ready.
9. PR bodies: do not fill `.github/pull_request_template.md`. It is issue-form
   YAML, which GitHub does not render for pull requests. Write plain Markdown:
   what changed, why, and the gate numbers.
10. Report CI by the 8 required contexts. The `Workers Builds:
    bangla-gpt-app` check fails on every PR; it is not a required context and
    the repo has no Worker config. Say so rather than calling CI red.
11. Worktrees have no `.venv/` or `node_modules/`. Use this checkout's venv by
    absolute path (`C:/Users/User/Documents/Bangla-GPT-APP/.venv/Scripts/python.exe`).
    Its editable install points at this checkout's `apps/api/src`, so in a
    worktree set `PYTHONPATH` to the worktree's `apps/api/src` before running
    pytest, or the tests import this checkout's code. Check with
    `python -c "import bangla_gpt_api; print(bangla_gpt_api.__file__)"`.
12. Figma: the Figma connector has a View seat, and the product has no Figma
    source (the repo's tooling inventory marks Figma not applicable). Do not
    use Figma tools unless the user names a Figma file, even when the Figma
    server's own instructions ask for them.
13. Dependabot: six npm update PRs are open against a limit of five, so no new
    npm updates arrive. Do not close or merge Dependabot PRs without asking.

## Known caveats

- `test_status_public_ok_shape` and `test_status_page_reports_curriculum_component`
  fail when the Gemini or OpenAI error-path tests run first. The provider-failure
  streak is process-global and nothing resets it between tests. The fix is a
  per-test reset in `apps/api/tests/conftest.py`, on branch
  `fix/provider-health-test-isolation` until it is merged. If these tests fail,
  check the test order before calling a change broken.
- `AGENTS.md` is stale in two places: it says `PROMPT_VERSION = "tutor-prompt-v1"`
  (the code has `tutor-prompt-v2`, `services/tutor.py`), and it says 852 chunks
  (the corpus manifest totals 847). Trust the code, flag the document to the
  user, and do not edit `AGENTS.md` without asking.
