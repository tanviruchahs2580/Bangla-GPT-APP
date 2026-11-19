# T-34 — repository process hygiene (verification task)

Verified 2026-11-20 at `8717f6f`. Every card item is ALREADY satisfied — none required work:

1. **No root-level audit/progress documents**: root `.md` = AGENTS, CHANGELOG, CODE_OF_CONDUCT, CONTRIBUTING, README, SECURITY, SUPPORT, THIRD_PARTY_NOTICES (measured in T-01); self-audit reports live in `docs/archive/` behind the archive banner.
2. **PR template**: `.github/pull_request_template.md` + `.github/PULL_REQUEST_TEMPLATE.md` exist with summary/test-plan/rollback shape (matches §11.2).
3. **CODEOWNERS**: `.github/CODEOWNERS` with the verified handle `@tanviruchahs2580` (default owner + per-area rows; never invented handles).
4. **Dependency updates**: `.github/dependabot.yml` covering pip/npm/docker/github-actions (weekly cadence config present).
5. **Link/path checks**: `check_doc_paths.py` + `check_readme_contract.py` run in guardrails — the link check the card asks for is a CI gate.
6. **Branch protection / required checks**: repo settings — HO-2 (listed in the final report).
