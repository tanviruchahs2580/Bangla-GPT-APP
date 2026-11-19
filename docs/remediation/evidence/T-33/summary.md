# T-33 — dev/prod parity and developer experience (verification task)

Verified 2026-11-20 at `8717f6f`.

1. **Entry-point task runner**: `Makefile` exists with the gate targets (`check_changelog` wiring at :157; corpus-check skip-aware target per AGENTS.md §12).
2. **Postgres-first local setup**: `docker-compose.yml` ships the Postgres + Redis topology with per-profile services; the remediation tooling itself ships `docs/remediation/tools/disposable-services.compose.yaml` (pgvector:pg16 + redis:7) used for T-20/T-21/T-36 — the compose path is exercised, not just documented.
3. **README quick start**: run VERBATIM by CI (`quickstart-windows` job — README PowerShell commands, uvicorn boot, /health probe, npm ci + build; ci.yml:208-280) — the README-vs-reality check the card wants is already automated, on Windows; the ubuntu `api` job covers the POSIX form of the same commands. Docs-as-tests guards (check_readme_contract, check_doc_paths) keep the README honest.
4. **Windows-fragile scripts**: the F-18 verification found the harness itself already Python-native where it matters (capture.py, bn_scan, check_* scripts); no script replaced here because none was observed failing in this session's evidence.
