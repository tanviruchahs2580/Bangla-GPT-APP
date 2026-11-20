---
name: gates
description: Run the CI gates a Bangla-GPT-APP change needs, locally on this Windows workstation, and report the evidence. Use before calling a change done, before committing or proposing a push or PR, and whenever asked to run the tests, lint, type checks, coverage, eval or "CI" for this repo.
---

# Gates for Bangla GPT

CI (`.github/workflows/ci.yml` and `eval-gate.yml`) stays the authority. The
commands below mirror its steps so a failure shows up before the push. Run them
from Git Bash at the repo root. `make` is not installed, so the recipes are
written out here. Each command runs in a `( … )` subshell, and an exit code is
reported, so a failed step is never hidden by a later one.

Test order matters: CI runs pytest and vitest with fixed shuffle seeds
(`20261030`). Use the same seeds here so a failure reproduces.

## 1. Choose the gates

Look at what changed: `git status --short` and `git diff --name-only main...HEAD`.

| What changed | Run |
| --- | --- |
| `apps/api/**` | API gates |
| `apps/api/src/bangla_gpt_api/db/`, `apps/api/alembic/`, any DB model | API gates, the migration cycle, and `/safe-db-migration` |
| `apps/api/pyproject.toml` | API gates, the lockfile check and `pip-audit`. Regenerating `constraints.txt` needs the user's OK |
| routers, schemas, or anything the OpenAPI document shows | API gates and the OpenAPI fixture check |
| retrieval, tutor, prompt, safety or evaluation code | API gates and the eval gates |
| `apps/web/**` | Web gates |
| UI strings, `i18n`, `docs/native-review/` | Docs gates (including the native-review check) |
| Markdown, docs, env templates, `scripts/` | Docs gates |
| Anything else, or unsure | All of them |

## 2. API

One command per line. Each runs from the repo root.

```bash
(cd apps/api && ../../.venv/Scripts/python.exe -m ruff check .)
(cd apps/api && ../../.venv/Scripts/python.exe -m ruff format --check .)
(cd apps/api && ../../.venv/Scripts/python.exe -m mypy src)
.venv/Scripts/lint-imports --config .importlinter
(cd apps/api && ../../.venv/Scripts/python.exe -m pytest -q -p randomly --randomly-seed=20261030 --cov=bangla_gpt_api --cov-branch --cov-report=json)
(cd apps/api && ../../.venv/Scripts/python.exe scripts/check_coverage_floors.py coverage.json)
(cd apps/api && ../../.venv/Scripts/python.exe -m pip_audit -r constraints.txt --no-deps)
.venv/Scripts/python.exe apps/api/scripts/check_lockfile.py
```

- The pytest run takes 11 to 22 minutes. Start it in the background and keep
  working. Coverage floors only ratchet up (AGENTS.md §11); never lower one.
- Collection can create `apps/api/bangla_gpt.db`. It is gitignored; delete it
  after the run.

Smoke start and the OpenAPI fixture (both CI steps; the fixture check writes to a
scratch file and never touches the tracked fixture):

```bash
(cd apps/api && DATABASE_URL=sqlite:///./_smoke_scratch.db ../../.venv/Scripts/python.exe -c "from bangla_gpt_api.main import create_app; app = create_app(); print(len(app.openapi()['paths']), 'openapi paths ok')"; rc=$?; rm -f _smoke_scratch.db; exit $rc)
OUT="$(mktemp)"; (cd apps/api && ../../.venv/Scripts/python.exe scripts/export_openapi_types.py "$OUT") && cmp "$OUT" apps/web/src/test/fixtures/openapi.json && echo "openapi fixture current"; rm -f "$OUT"
```

The migration cycle (CI runs it on every API change). It goes through the
`alembic` ask rule, so expect a prompt. Full details are in `/safe-db-migration`:

```bash
(cd apps/api && export DATABASE_URL=sqlite:///./_ci_scratch.db && rm -f _ci_scratch.db && ../../.venv/Scripts/python.exe -m alembic upgrade head && ../../.venv/Scripts/python.exe -m alembic downgrade base && ../../.venv/Scripts/python.exe -m alembic upgrade head && ../../.venv/Scripts/python.exe -m alembic check; rc=$?; rm -f _ci_scratch.db; echo "migration cycle exit=$rc")
```

The dependency audit is `pip-audit` on the locked set (`constraints.txt`), which
is what the gate means. It needs network access; if it fails for that reason,
say so and do not call it passed.

## 3. Web

```bash
(cd apps/web && npm audit --audit-level=high --omit=dev)
(cd apps/web && npm run test:coverage -- --no-file-parallelism --sequence.shuffle --sequence.seed=20261030)
(cd apps/web && npm run lint)
(cd apps/web && npm run build)
(cd apps/web && npm run format:check)
(cd apps/web && npm run deadcode)
```

- Use `test:coverage` with the CI flags, not plain `npm test`. Only this form
  enforces the thresholds in `vite.config.ts` (68 / 60 / 60 / 70) and the seed.
- The `npm audit` step needs network access. Same rule as pip-audit.

## 4. Docs and guardrails

```bash
.venv/Scripts/python.exe apps/api/scripts/check_doc_paths.py
.venv/Scripts/python.exe apps/api/scripts/check_proxy_contract.py
.venv/Scripts/python.exe apps/api/scripts/check_readme_contract.py
.venv/Scripts/python.exe apps/api/scripts/check_changelog.py
.venv/Scripts/python.exe scripts/check_archive_banners.py
.venv/Scripts/python.exe scripts/check_asset_notices.py
.venv/Scripts/python.exe scripts/check_i18n.py
.venv/Scripts/python.exe scripts/gen_native_review.py --check
(cd apps/api && PYTHONPATH=src ../../.venv/Scripts/python.exe scripts/check_corpus_manifest.py --data-dir ../../data/nctb)
.venv/Scripts/python.exe -m pre_commit run --all-files --show-diff-on-failure
```

Two CI guardrail steps are inline Python. Run them with the venv interpreter:

- The Bangla script hygiene scan. Its output goes to a temp file, and the step
  fails on any hygiene category:

  ```bash
  BN="$(mktemp)"; git ls-files -z | xargs -0 .venv/Scripts/python.exe scripts/bn_scan.py > "$BN"; test -s "$BN" || echo "bn_scan printed nothing: the scanner did not run"; grep -E '^(ASSAMESE_LETTER|DEVANAGARI_NON_PUNCT|REPLACEMENT_CHAR|BOM_INSIDE_TEXT|NOT_NFC) +[1-9]' "$BN" && echo "BANGLA HYGIENE FAILED"; tail -14 "$BN"; rm -f "$BN"
  ```

- The mojibake scan and the README and `docs/ci.md` workflow-table check. Copy
  the heredoc from `.github/workflows/ci.yml` in the guardrails job (search for
  "Repository mojibake scan" and "README and docs/ci.md agree") and run it with
  `.venv/Scripts/python.exe -`, in place of `python3`.

Notes:

- `check_changelog.py` fails while a branch has commits that `CHANGELOG.md`
  does not list. That is expected until the changelog is regenerated, which is a
  separate commit and the user's call.
- `pre_commit` may rewrite files (end of file, whitespace, `ruff --fix`).
  Review its diff.
- Add `--corpus-dir ../../data/nctb` to the corpus check only when
  `data/nctb/normalized/` exists locally. It does not exist on this machine.

## 5. Eval (blocking in CI)

Run these when the change touches retrieval, tutor, prompt, safety or eval code.
These are the four blocking steps of `eval-gate.yml`, run from `apps/api`:

```bash
(cd apps/api && ../../.venv/Scripts/python.exe scripts/check_eval_binding.py)
(cd apps/api && ../../.venv/Scripts/python.exe -m bangla_gpt_api.evaluation.cli)
(cd apps/api && ../../.venv/Scripts/python.exe scripts/evaluate_golden.py)
(cd apps/api && ../../.venv/Scripts/python.exe -m bangla_gpt_api.evaluation.cli --redteam)
```

Never regenerate `apps/api/eval/baseline_v3.json` to make a change pass
(AGENTS.md §7 and §11). The real-corpus retrieval gate (`retrieval-eval.yml`)
cannot run here: the NCTB corpus is absent.

## 6. Not runnable on this workstation

Name each of these as "CI only" or "not run locally" when it applies:

- Playwright e2e and visual regression: no browsers installed. Edge and Chrome
  are installed, but `playwright.config.ts` does not use them.
- The Docker image build, hadolint and Trivy (`docker` and `guardrails` jobs).
- gitleaks (full history), CodeQL, OpenSSF Scorecard, Lighthouse CI.
- semgrep, radon and vulture: not in the venv. CI installs them at run time;
  installing them here needs the user's OK.
- The PostgreSQL engine leg: no server.
- The Redis-backed cache tests: no redis-server, so they skip here.
- The Python 3.11 matrix leg: no 3.11 interpreter.
- The SBOM job (cyclonedx-py and syft) and the Android release.
- The Cloudflare "Workers Builds" check on PRs: not part of this repo's CI.

## 7. Known test-order caveat

`test_status_public_ok_shape` and `test_status_page_reports_curriculum_component`
fail when the Gemini or OpenAI error-path tests run first. The CI seed makes
this reproducible. If they fail, check the order (see `CLAUDE.md`, "Known
caveats") before calling the change broken.

## 8. Report

For every gate: the command, pass or fail, and the numbers (tests passed,
failed and skipped; coverage; findings). Then list each gate that did not run
and why. Never write "all green" when a gate was skipped or failed. Judge the
PR against the 8 required CI contexts, not against every red check on the page.
