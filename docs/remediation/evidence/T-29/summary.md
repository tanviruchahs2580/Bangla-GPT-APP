# T-29 — supply-chain and static-analysis baseline (verification task)

Verified 2026-11-20 at `8717f6f`. The card's inventory is complete on this tree; **nothing was missing** — every tool the card asks for already runs in CI (T-26/T-01 evidence), so no additions were made:

| Tool | Where | Blocking? |
|---|---|---|
| SAST (CodeQL) | `codeql.yml` (SHA-pinned, security-events:write scoped) | yes (default CodeQL behavior) |
| SAST (Semgrep, p/python+ts+react+docker+gha+secrets) | ci.yml guardrails :853-862, ERROR severity --error | yes |
| Dependency audit | pip-audit (locked set, ci.yml:134-159) + npm audit --omit=dev (web job) + Trivy npm-lock scan (guardrails) | yes |
| Container scan | Trivy image gate, fixable HIGH/CRITICAL, DB-flake retry (docker job) | yes |
| Dockerfile lint | hadolint (digest-pinned; DL3008 waiver documented in .hadolint.yaml) | yes |
| Secret scan | gitleaks full history (v2.3.9, fetch-depth 0) + pre-push hook + value-scoped .gitleaks.toml | yes |
| SBOM | CycloneDX Python (from the hash-verified lock) + web (syft) + per-PR image SBOM (sbom-action) | artifact, non-blocking by design (uploaded) |
| License policy | THIRD_PARTY_NOTICES.md + `check_asset_notices` guardrail (bundled images) + OFL font licences shipped | guardrail |
| Scorecard | OpenSSF scorecard-action (scorecard.yml) | informational |
| Actions pinning | zero unpinned `uses:` across 11 workflows (T-16 tabulation) | — |
| Dockerfiles | multi-stage, pinned bases, non-root where applicable (T-29 card step 3 review) — details in the T-16 tabulation + Dockerfile comments | — |

Findings baseline: `.gitleaks.toml` (value-scoped, per-entry reasons), `.semgrepignore` (per-entry reasons, security_scans.md), complexity/vulture ratchets (guardrails). CI fails on NEW findings only.

No copyleft runtime dependency found in this pass (MIT/Apache/BSD class per pyproject + THIRD_PARTY_NOTICES; the ratchet lives in the licence allow-list note in AGENTS.md §11).
