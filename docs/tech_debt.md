# Technical debt register

Curated list of the debt a maintainer would pick up next. Each row names what
the debt is, why it is not fixed yet, the effort, the risk if it stays, and
the role that owns the call. Effort: S (hours), M (days), L (weeks). Risk of
leaving it: H/M/L. It is linked from `docs/README.md`; update it in the same
change that pays a row down or adds a new one.

The 2026-10-29 hardening wave closed most of the audit's findings; this
register is what remains after that wave, deliberately.

| id | Item | Why it is still open | Effort | Risk | Owner |
|---|---|---|---|---|---|
| TD-01 | Complexity limits are not enforced: ruff `C90` stays off, 11 functions at radon grade D/F, `services/gdpr.py::build_data_export` is 481 lines (F-006) | Needs a refactor first; enabling the rule before it would red the build | L | M | API maintainer |
| TD-02 | `services` and `providers` import each other, so the strict layer contract in `.importlinter` cannot be widened to a single list (F-069) | Breaking the cycle touches the mock provider and the request-context seam | M | M | API maintainer |
| TD-03 | AI job lifecycle: no idempotency key, no retry, no retention sweep for `ai_jobs` (F-007) | Product decision on idempotency semantics + a migration | M | M | API maintainer |
| TD-04 | The served corpus is not reproducible from the recorded pipeline; committed derived artifacts disagree with the tree (F-011, F-047) | Needs a full rebuild with the rights-holder permission in place (F-013) | L | M | Data maintainer |
| TD-05 | Cross-source duplicate chunks are not deduplicated; the report says `duplicates_removed=0` (F-012) | Belongs with the corpus rebuild above | M | M | Data maintainer |
| TD-06 | No foreign key declares `ON DELETE`; erase policy is application-only (F-014) | One reversible migration plus re-running the erasure tests on Postgres | M | M | API maintainer |
| TD-07 | `docs/API.md` documents the core surface only; the full surface is `/openapi.json` (F-017) | The durable fix is generating the reference in CI; the audit kept the hand-written detail for SSE and pagination | M | L | Docs maintainer |
| TD-08 | Dependency updates have no cadence: 27 of 36 direct npm deps and 38 Python pins were behind at the audit (F-152) | Owner decision on a recurring slot; majors (react 19, vite 8, TS 7, capacitor 8) need a planned toolchain refresh | S recurring | M | Owner |
| TD-09 | Bundled UI images have no licence record (F-137) | Needs the owner to state the source/licence or replace the artwork | S | M | Owner |
| TD-10 | The uptime probe is best-effort (GitHub throttles `schedule`); an external monitor is the durable paging path (F-079) | Needs an external service decision; the runbook documents the latency | S | M | Owner |
| TD-11 | `release.yml` makes actionlint's shellcheck pass hang (platform-specific); only the other eight workflows get the shellcheck pass (F-173) | No clean workaround without splitting the file's embedded scripts | S | L | CI maintainer |
| TD-12 | No fresh synthetic-subject dry run through the whole pipeline (generate → ingest → index → tutor → quiz) (ARCH-10) | Existing tests cover classes 6-10 / math+science; a new-subject fixture is a product-side investment | M | L | Data/RAG maintainer |
| TD-13 | Live-model behaviour (Gemini latency, quota, moderation quality) is unverified without a key (F-020 family, `SECURITY.md`) | Needs a funded key and a maintenance window | M | M | Owner |
| TD-14 | `docs/security_scans.md` and `docs/dependency_waivers.md` need a review-by date discipline; advisories currently have no expiry field (F-SUP-1) | One editing pass plus a scheduled reminder | S | M | Security maintainer |

Not debt, deliberately: the phase log in `docs/architecture.md`, the
`docs/archive/` reports (banner-covered history), and the pre-commit hook
subset (`.pre-commit-config.yaml` states why mypy/eslint/prettier/gitleaks
stay in CI).
