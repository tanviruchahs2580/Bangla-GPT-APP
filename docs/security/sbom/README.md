# SBOM artifacts — 2026-10-19

Finding: AUD-B-26 ("no generated SBOM file is tracked"). The CI job
`sbom-licence` (`.github/workflows/ci.yml`) generates SBOMs on every PR but
publishes them as 90-day workflow artifacts; nothing dated lives in the
repository. These files are the repo-owned, dated counterpart.

| File | What it describes |
|---|---|
| `bangla-gpt-api-2026-10-19.cdx.json` | CycloneDX 1.6 SBOM of the **locked runtime environment** (`apps/api/constraints.txt`, hash-verified install) |
| `bangla-gpt-web-2026-10-19.cdx.json` | CycloneDX 1.6 SBOM of the web **production dependency tree** (`apps/web/package.json` via `package-lock.json`, `--omit dev`) |
| `licence-inventory-2026-10-19.md` | Machine-derived licence summary + every copyleft/restricted/unresolved component in both SBOMs |

## How these were generated (2026-10-19)

```sh
# API: runtime-only venv from the hash-verified lock, then SBOM the environment
python -m venv .venv-sbom-local
.venv-sbom-local/Scripts/python -m pip install --require-hashes -r apps/api/constraints.txt
python -m venv .venv-tools && .venv-tools/Scripts/pip install "cyclonedx-bom==7.5.0"
.venv-tools/Scripts/cyclonedx-py environment .venv-sbom-local/Scripts/python \
  --output-format JSON \
  --output-file docs/security/sbom/bangla-gpt-api-2026-10-19.cdx.json

# Web: lock-file only, production tree (same semantics as the CI job)
cd apps/web
npx --yes @cyclonedx/cyclonedx-npm@6.0.1 --omit dev --package-lock-only \
  --output-file ../../docs/security/sbom/bangla-gpt-web-2026-10-19.cdx.json
```

The CI job pins `cyclonedx-bom 7.5.0` / `@cyclonedx/cyclonedx-npm 4.1.1`;
this local run used `cyclonedx-npm 6.0.1` (the version current on
2026-10-19). Spec version is 1.6 either way; re-generate with the CI pins if
byte-level parity with CI output matters.

## Caveats recorded with the artifacts

- The local `apps/web/node_modules` tree is inconsistent (`npm ls` reports
  `invalid: esbuild@0.21.5`), which is exactly why the web SBOM was generated
  **from the lock file** (`--package-lock-only`), not from installed modules.
  The lock file is the shipping truth; the CI job does the same.
- On this machine the API SBOM was produced from a fresh venv built from
  `constraints.txt`, not from the developer venv, so it does **not** list
  dev/test tooling. Dev-tool licences are triaged in
  `docs/security_scans.md`.
- Neither artifact is a substitute for the release-time buildx attestation in
  `release.yml` (`sbom: true`, `provenance: mode=max`), which covers the
  container images themselves. No release has been cut, so that attestation
  remains unverified until one is.

## Licence posture (summary; details in the inventory)

- No strong-copyleft (GPL/AGPL/SSPL) component ships: the API set is
  MIT/Apache/BSD-dominant with **LGPL-3.0-only** `fpdf2`, `psycopg` and
  `psycopg-binary` (the relink note in `THIRD_PARTY_NOTICES.md` covers them),
  plus `pyphen`'s triple LGPL/MPL/GPL declaration where the non-GPL options
  apply. The web tree is MIT-dominant with file-level MPL-2.0 entries and two
  OFL-1.1 fonts.
- The CI `sbom-licence` job fails on `GPL-2.0-only;GPL-3.0-only;AGPL-3.0-only;SSPL-1.0`
  and stays the blocking gate; these artifacts exist so a human can read the
  same fact without opening a workflow log.

Refresh cadence: regenerate on dependency-lock changes and at each release
candidate; keep the dated filenames (one pair per date) rather than
overwriting, so the inventory remains an auditable series.
