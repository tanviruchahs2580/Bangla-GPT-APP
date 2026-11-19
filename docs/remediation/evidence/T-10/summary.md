# T-10 summary — repository and secret hygiene

Executed 2026-11-19 at `f206ee2a5504253187cd9c6b9719010e6a2514f5` (branch `remediation/0.2.0`). Zero behavior change; the only product-tree change is a `.gitignore` addition.

## Step 1 — tracked-file and history-name checks
`evidence/T-10/t10-step1-name-checks.txt`: zero tracked `.env`/db/sqlite/coverage files; zero `.env` additions in full history (`--diff-filter=A --all`). Exactly one DB-shaped file ever added to history: `apps/api/dev.db.bak-wave2` — previously owner-verified synthetic seed data (AGENTS.md §15); recurrence blocked by `*.db*` ignore rules.

## Step 2 — full-history secret scan
`evidence/T-10/t10-step2-gitleaks-full-history.txt`: gitleaks 8.30.1 (verified from `scoop` shim), repo's own `.gitleaks.toml` baseline, `git . --log-opts=--all`: **1176 commits scanned, ~30 MB, no leaks found** (report JSON: 0 findings, `--redact` set). The pre-existing value-scoped baseline (`.gitleaks.toml`) documents the 82 reviewed non-credentials with per-entry reasons and a planted-key verification — used as the required historic-findings baseline file (card step 6).

## Step 3 — personal-data scan (tracked data/fixtures)
`evidence/T-10/t10-step3-pii-scan2.txt`: 989 tracked files scanned; 263 carry PII-shaped hits. Triage (shapes/domains only, no values printed): email domains are synthetic test domains (top: `example` ×1023, `e2e`, `school`, `demo`, `g3`, `example.edu`, `sentry.example`; no consumer-mail domain); mobile-shaped strings are the redactor's own fixture/docstring examples (spot-checked `services/pii.py:18`, `services/analytics.py:28`), a SHA-256 digit-run in `constraints.txt:762`, and one doc table line; `corpus_manifest.json` carries one NID-shaped digit run inside a digest. **Verdict: fixtures/metadata only, no real personal data → STOP S-1 not raised.**

## Step 5 — .gitignore / .dockerignore
`.gitignore` gained `apps/api/coverage.xml` (N-02: the CI-uploaded artifact was unignored, so every local coverage run left a stray untracked file) — verified `git check-ignore` now IGNORED (`.gitignore:120`). `.dockerignore` (root + `apps/web/`) already excludes env files/secrets/certs with documented negations for the two `*.example` templates; no change needed.

## Step 6 — secret scanning wiring (verified, pre-existing)
- CI: `ci.yml` guardrails runs `gitleaks/gitleaks-action@ff98106… # v2.3.9` over a `fetch-depth: 0` clone (full history) — ci.yml:771-787; Semgrep `p/secrets` ERROR-severity blocking — ci.yml:853-862; Trivy image + npm-lock scans — ci.yml:880-911, 1262-1307.
- pre-commit: gitleaks hook at the `pre-push` stage (`.pre-commit-config.yaml:14-25`, system binary, documented) — CI guardrails runs `pre-commit run --all-files` against the pinned revision, so the gate holds.
- Baseline: `.gitleaks.toml` value-scoped allowlist (never path-scoped) with per-entry reasons.
Nothing to add; wired and green (CI-UNAVAILABLE on this branch SHA — see STATE.md).

## Step 7 — NCTB inventory
`evidence/T-10/nctb-inventory.md`: all `data/nctb` tracked content is metadata (manifests/quality/eval, ≤11.9 KB per file, no textbook text); raw/extracted/normalized gitignored and absent here; repository PUBLIC; **STOP S-4 not raised**; licensing remains HO-3.

## Acceptance
- Evidence files exist (this summary + four captures + inventory). CI secret-scan job: green on main per repo history; on this branch CI-UNAVAILABLE (branch filters) with the local full-history scan standing in as direct evidence.
- Zero behavior change: `.gitignore` line only.
