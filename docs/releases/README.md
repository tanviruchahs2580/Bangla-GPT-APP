# Release plans

Prepared release records. A plan here is a draft until the owner authorises the
tag: nothing in this directory has been tagged, published or deployed, and the
audit that wrote it (2026-10 hardening round) was not authorised to push tags
or trigger deploys.

The mechanics live elsewhere and are not duplicated here:

| What | Where |
| --- | --- |
| Tag-triggered pipeline (CI gate, GHCR images, optional SSH deploy, `gh release create`) | [.github/workflows/release.yml](../../.github/workflows/release.yml), explained in [../ci.md](../ci.md) |
| Deploy procedure and secrets | [../runbook.md](../runbook.md) §2 |
| Rollback (release image pin, DB downgrade, health-gated auto-rollback) | [../runbook.md](../runbook.md) §7 |
| Owner launch gates (legal, UAT, deployment) | [../LAUNCH_READINESS_CHECKLIST.md](../LAUNCH_READINESS_CHECKLIST.md) |
| What changed per release | [../../CHANGELOG.md](../../CHANGELOG.md) (generated; do not hand-edit) |

## House scheme (verified from the repository, 2026-10-19)

- **Tags:** annotated SemVer tags `vX.Y.Z` (history: `v0.1.0-rc1` … `v0.9.2`,
  13 tags, newest `v0.9.2` = `0d275a8`, 2026-09-15). Pre-releases use
  `vX.Y.Z-rcN`; the release workflow triggers on `v*.*.*`, so an `-rc` tag
  also builds images and a Release record.
- **Images:** `ghcr.io/tanviruchahs2580/bangla-gpt-api:${version}` and
  `…/bangla-gpt-web:${version}` — version only, deliberately no `:latest`
  (the deploy job and compose address images by explicit tag).
- **Gate:** the release workflow refuses to build or publish unless a
  successful `API CI` run exists for the tagged commit.
- **Release notes:** the workflow creates the GitHub Release from the same
  commits the CHANGELOG groups; `CHANGELOG.md` itself is the Keep a
  Changelog-format record and is generated
  (`python apps/api/scripts/gen_changelog.py`).
- **Single source of version:** `apps/api/pyproject.toml` `[project].version`;
  `python scripts/check_version.py` asserts every file that states it agrees.

No release is tagged while the working tree is ahead of a green CI run, and
the owner-only checklist items below are re-checked at tag time.
