# Developer entry points for Bangla GPT APP (audit finding AUD-JK-09).
#
#   make setup   create the Python venv + install locked deps, install web deps
#   make dev     run the API with reload on http://127.0.0.1:8000
#   make test    run the real test commands (API pytest + web vitest)
#   make ci      every CI check that needs no external service, in CI's order
#   make help    list every target
#
# Requirements: run from Git Bash (or any POSIX shell) with GNU make, Python
# 3.12 (see .python-version) and Node 24 (see .nvmrc). Every command below is
# the one CI runs in .github/workflows/ci.yml; nothing is invented here.
# Overridable: VENV (default .venv), PYTEST_ARGS, NPM_INSTALL.
#
# `make test` runs the full API suite (several minutes) plus the web unit
# tests; `make test-fast` runs the guardrail subset in a few minutes.

SHELL := sh
.DEFAULT_GOAL := help

VENV ?= .venv
PYTEST_ARGS ?= -q
NPM_INSTALL ?= npm ci

ifeq ($(OS),Windows_NT)
  PY := $(CURDIR)/$(VENV)/Scripts/python.exe
else
  PY := $(CURDIR)/$(VENV)/bin/python
endif

.PHONY: help setup setup-python setup-web dev test test-fast test-api test-web \
        lint lint-api lint-web build check-version check-commits ci

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

setup: setup-python setup-web ## Create the venv, install locked Python deps and web deps

setup-python: ## Venv + hash-verified Python install (README quick start step 2)
	@test -d "$(VENV)" || "$(PY)" -m venv "$(VENV)"
	"$(PY)" -m pip install --upgrade pip
	cd apps/api && "$(PY)" -m pip install --require-hashes -r constraints.txt
	cd apps/api && "$(PY)" -m pip install --no-deps -e ".[dev]"

setup-web: ## Web dependencies (npm ci, exactly like CI)
	cd apps/web && $(NPM_INSTALL)

dev: ## Run the API with autoreload (foreground)
	cd apps/api && "$(PY)" -m uvicorn bangla_gpt_api.main:app --reload

test: test-api test-web ## Run the real API + web test suites

test-api: ## API suite (pytest, the same command CI runs)
	cd apps/api && "$(PY)" -m pytest $(PYTEST_ARGS)

test-web: ## Web unit tests (vitest run — the same command CI runs)
	cd apps/web && npm test

test-fast: ## Bounded guardrail subset (a few minutes): security, contract, gates
	cd apps/api && "$(PY)" -m pytest $(PYTEST_ARGS) \
		tests/test_security_v2.py tests/test_openapi_auth_matrix.py \
		tests/test_corpus_qa_gate.py tests/test_changelog_scripts.py \
		tests/test_lockfile_gate.py

lint: lint-api lint-web ## Run every linter CI runs

lint-api: ## API lint, format check, type check (CI: ruff + mypy)
	cd apps/api && "$(PY)" -m ruff check .
	cd apps/api && "$(PY)" -m ruff format --check .
	cd apps/api && "$(PY)" -m mypy src

lint-web: ## Web lint + format check (CI: eslint + prettier)
	cd apps/web && npm run lint
	cd apps/web && npm run format:check

build: ## Web production build (tsc + vite build)
	cd apps/web && npm run build

check-version: ## Verify the version is identical in every file that states it
	"$(PY)" scripts/check_version.py

check-commits: ## Verify recent commit subjects follow the repository rules
	"$(PY)" scripts/check_commits.py --max-count 50

ci: lint test check-version check-commits ## Local mirror of the CI checks that need no services
	cd apps/web && npm run build
	"$(PY)" apps/api/scripts/check_lockfile.py
	"$(PY)" apps/api/scripts/check_readme_contract.py
	"$(PY)" apps/api/scripts/check_doc_paths.py
	"$(PY)" apps/api/scripts/check_changelog.py
