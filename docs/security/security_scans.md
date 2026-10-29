# Security scan register

Every scanner that runs against this repository, what it gates on, and the
triage decisions behind anything it is configured to accept. Wave-2 entry
(2026-10-29) executed the tools the audit could only list; commands and
observed results are recorded here, the raw output lives in the QA evidence
folders for the round.

## Semgrep (SEC-18)

- Version: semgrep 1.182.1. Rulesets: `p/python`, `p/typescript`,
  `p/react`, `p/docker`, `p/github-actions`, `p/secrets`. Run from the
  repository root; CI pins the version and the same command.
- Command: `semgrep --config p/python --config p/typescript --config p/react
  --config p/docker --config p/github-actions --config p/secrets
  --severity ERROR --error --timeout 60 --metrics=off .`
- Gate: any ERROR-severity finding fails the `guardrails` job. WARNING-level
  findings are triaged in this register but do not fail the build, so the
  gate cannot be flipped by a rule that is not a defect.
- Scope and triaged allowlist: `.semgrepignore`. Four entries, each with
  its reason in the file: alembic migrations (append-only DDL, constants
  only), `scripts/backup_loop.py` (operator-configured offsite command),
  `apps/web/Dockerfile` (stock nginx master binds :80; see "hadolint" and
  the DOCK stream for the unprivileged-image follow-up), and the four
  token-construction test files whose literal fixture secrets are the same
  convention ruff's per-file-ignores already records for tests.
- Fixed in this round rather than allowed: `run-shell-injection` in
  `vercel-deploy.yml` (github context was interpolated straight into a
  `run:` block; it now reaches the shell through `env:`).
- Warning-level finding accepted: `insecure-hash-algorithm-sha1` at
  `apps/api/src/bangla_gpt_api/nctb/chunking.py:145` — SHA-1 is used with
  `usedforsecurity=False` as a non-cryptographic stable id for chunk metadata
  (the content fingerprint above it is SHA-256). Switching ids would orphan
  every persisted chunk reference for no security gain.

## hadolint

- Version: hadolint 2.15.1, blocking step in the `guardrails` job over
  `Dockerfile` and `apps/web/Dockerfile`.
- Result on this tree: zero findings. The single rule accepted by design is
  `DL3008` in `.hadolint.yaml` (`postgresql-client` intentionally unpinned;
  openssl and libssl3t64 are pinned in the Dockerfile with the refresh
  procedure documented there).

## Trivy

- Image and filesystem scans; the image gate in the `docker` job (fixable
  HIGH/CRITICAL) already existed. Wave 2 added the filesystem/dependency
  scan to the `guardrails` job and re-ran both locally against the built
  image. Version and results: see the wave-2 evidence folder; the gate is
  `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`.
- Configuration (`--scanners misconfig`) is part of the filesystem scan, so
  Dockerfile/compose hardening drift fails the build.

## Existing scanners (unchanged, listed for completeness)

- bandit 1.9.4: the audit's run (9 Low + 1 Medium, 0 High) is triaged
  false-positive-by-design in the wave-1 SEC audit register
  (`.qa-work/audit/SEC/`), alongside the CodeQL triage in
  `docs/security/codeql-triage-2026-10-27.md`.
- ruff `S` (flake8-bandit) is enabled in `pyproject.toml` and clean.
- pip-audit and `npm audit --omit=dev` gate the `api` / `web` jobs.
- gitleaks full-history scan and CodeQL run as their own workflows.
- OWASP ZAP has no automated run in this environment; the hermetic red-team
  gate (`evaluation/cli.py --redteam`) covers the prompt-injection surface
  and is a CI candidate recorded with the TEST stream.
