# Bangla GPT APP task runner (DX-02).
#
# Requires GNU make and bash. On Windows run it from Git Bash, where bash is
# on PATH; on Linux/macOS the system make and bash work as they are.
#
# Every recipe is one of the commands the README, CONTRIBUTING or ci.yml
# already run -- the point is that a contributor (or an agent) does not have to
# reassemble the flow from three documents, and that the commands cannot drift
# from CI silently. Where a CI job needs infrastructure this machine does not
# have, the target says so instead of pretending.
#
# Variable overrides: PYTHON=python3.12  (interpreter used to build the venv)
# DATABASE_URL / ENV are read by the app and by migrate/seed/dev as usual.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

ifeq ($(wildcard Makefile),)
$(error run make from the repository root)
endif

PYTHON ?= python
ifeq ($(OS),Windows_NT)
VENV_PY := $(CURDIR)/.venv/Scripts/python.exe
else
VENV_PY := $(CURDIR)/.venv/bin/python
endif
# The repository venv when it exists, the plain interpreter otherwise, so the
# targets also work inside an already-activated environment (and in CI).
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(PYTHON))

.PHONY: help setup dev dev-web lint format format-check typecheck test test-web \
        e2e build migrate seed corpus docker-up docker-down docs-check ci

help:
	@echo "make setup       venv + hash-locked API install + npm ci"
	@echo "make dev         API with autoreload (http://127.0.0.1:8000)"
	@echo "make dev-web     Vite dev server (http://localhost:5173)"
	@echo "make lint        ruff check + eslint --max-warnings 0"
	@echo "make format      ruff format + prettier --write"
	@echo "make format-check  the CI form: ruff format --check + prettier --check"
	@echo "make typecheck   mypy src + tsc --noEmit"
	@echo "make test        pytest (API)"
	@echo "make test-web    vitest (apps/web)"
	@echo "make e2e         Playwright (starts the seeded API and the dev server)"
	@echo "make build       type-checked production build of the web app"
	@echo "make migrate     alembic upgrade head (honours DATABASE_URL)"
	@echo "make seed        seed the Playwright accounts (honours DATABASE_URL)"
	@echo "make corpus      build the NCTB corpus for the optional ssc-science subset"
	@echo "make docker-up   ENV=test docker compose --profile core up -d --wait"
	@echo "make docker-down stop that stack"
	@echo "make docs-check  repository documentation/contract checks (CI guardrails subset)"
	@echo "make imports-check  .importlinter layering contracts (needs import-linter; CI installs it)"
	@echo "make ci          the one-machine subset of the blocking CI gate"

# Same two installs as the README quick start and the api CI job; the venv
# lives at the repository root (the README's apps/api/.venv is the same two
# commands in a different directory, and both are git-ignored).
setup:
	$(PYTHON) -m venv .venv
	"$(PY)" -m pip install --upgrade pip
	"$(PY)" -m pip install --require-hashes -r apps/api/constraints.txt
	cd apps/api && "$(PY)" -m pip install --no-deps -e ".[dev]"
	cd apps/web && npm ci

dev:
	cd apps/api && "$(PY)" -m uvicorn bangla_gpt_api.main:app --reload

dev-web:
	cd apps/web && npm run dev

lint:
	cd apps/api && "$(PY)" -m ruff check .
	cd apps/web && npm run lint

format:
	cd apps/api && "$(PY)" -m ruff format .
	cd apps/web && npm run format

format-check:
	cd apps/api && "$(PY)" -m ruff format --check .
	cd apps/web && npm run format:check

typecheck:
	cd apps/api && "$(PY)" -m mypy src
	cd apps/web && npx --no-install tsc --noEmit

test:
	cd apps/api && "$(PY)" -m pytest -q

test-web:
	cd apps/web && npm test

e2e:
	cd apps/web && npm run test:e2e

build:
	cd apps/web && npm run build

migrate:
	cd apps/api && "$(PY)" -m alembic upgrade head

seed:
	cd apps/api && ENV=$${ENV:-development} "$(PY)" ../apps/web/e2e/seed_e2e_users.py

corpus:
	cd apps/api && "$(PY)" scripts/build_nctb_corpus.py --data-dir ../../data/nctb --subset ssc-science

docker-up:
	ENV=test docker compose --profile core up -d --wait

docker-down:
	docker compose --profile core down

imports-check:
	"$(PY)" -c "import sys; from importlinter.cli import lint_imports_command; sys.exit(lint_imports_command())"

docs-check:
	"$(PY)" scripts/check_archive_banners.py
	"$(PY)" scripts/check_asset_notices.py
	"$(PY)" apps/api/scripts/check_doc_paths.py
	"$(PY)" apps/api/scripts/check_lockfile.py
	"$(PY)" apps/api/scripts/check_proxy_contract.py
	"$(PY)" apps/api/scripts/check_readme_contract.py
	"$(PY)" apps/api/scripts/check_changelog.py
	"$(PY)" scripts/check_i18n.py

# The blocking gate as far as one machine can run it: the api, web and
# guardrails job commands. NOT included, with the reason: the postgres job
# needs a PostgreSQL service; e2e needs the Playwright browsers; the docker job
# needs Docker and builds the image; eval-gate and the sbom job have their own
# CI jobs. Run those where their infrastructure exists.
ci: format-check
	"$(PY)" -m pre_commit run --all-files --show-diff-on-failure
	cd apps/api && "$(PY)" -m ruff check .
	cd apps/api && "$(PY)" -m mypy src
	cd apps/api && "$(PY)" -m pytest -q
	cd apps/web && npm run lint
	cd apps/web && npm test
	cd apps/web && npm run build
	$(MAKE) docs-check
