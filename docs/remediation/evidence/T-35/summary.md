# T-35 — dependency currency report (report-only; no bulk upgrade)

Measured 2026-11-20 at `8717f6f` (registry queries against the live index; raw outputs: `npm-outdated.json` (33 packages), `pip-outdated.txt` (23 lines)).

## Class summary
- **npm**: 33 outdated; 22 major-version behind. Toolchain majors: Capacitor 7→8 (six packages), React types 18→19, eslint 9→10, jest-dom 7→8, Sentry 10→11, vitest 4.x line current. Risk: toolchain refresh (React 19 / Vite 8 / TS next / Capacitor 8) is a planned-program item per TD-08 — NOT patchable here.
- **Python**: 23 pins behind latest (constraints are hash-pinned by design). The lock update path is `pip-compile` + `check_lockfile.py` — a reviewed dependency wave, not a per-task edit.

## Applied under this task
NONE: no new high/critical advisory in the audit gates (pip-audit + npm audit + Trivy all green on this tree per T-29), and the card forbids bulk upgrades; patch-level security fixes only apply when an advisory demands them (none did).

## Suggested order (backlog)
1. Toolchain refresh wave (React 19 → Vite 8 → TS → vitest majors) with the coverage ratchets held.
2. Capacitor 8 upgrade + store rebuild (versionName/versionCode discipline per HO-9).
3. pip-compile dependency wave on the hash-verified lock.
