# Licence inventory — 2026-10-19

Derived mechanically from the two CycloneDX SBOMs beside this file (`bangla-gpt-api-2026-10-19.cdx.json`, `bangla-gpt-web-2026-10-19.cdx.json`); counts and lists are generated, not transcribed. Component-level detail is in the SBOMs themselves.

## API (Python environment) — 91 components

| Licence | Components |
| --- | --- |
| MIT | 50 |
| BSD-3-Clause | 12 |
| Apache-2.0 | 10 |
| License :: OSI Approved :: Apache Software License | 6 |
| LGPL-3.0-only | 3 |
| BSD-2-Clause | 2 |
| License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0) | 2 |
| License :: OSI Approved :: BSD License | 2 |
| MPL-2.0 | 1 |
| MIT-0 | 1 |
| Apache-2.0 OR BSD-3-Clause | 1 |
| Python-2.0 | 1 |
| Apache-2.0 OR BSD-2-Clause | 1 |
| MIT-CMU | 1 |
| Apache-2.0 AND BSD-2-Clause | 1 |
| PSF-2.0 | 1 |
| (no licence metadata) | 1 |

### Copyleft / restricted / unresolved

- certifi 2026.7.22 -- MPL-2.0, License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)
- fpdf2 2.8.9 -- LGPL-3.0-only
- psycopg 3.3.6 -- LGPL-3.0-only
- psycopg-binary 3.3.6 -- LGPL-3.0-only
- uharfbuzz 0.56.3 -- no metadata

## Web (package-lock.json) — 127 components

| Licence | Components |
| --- | --- |
| MIT | 121 |
| ISC | 3 |
| OFL-1.1 | 2 |
| 0BSD | 1 |

### Copyleft / restricted / unresolved

- (none)

## Review notes

- LGPL-3.0-only (API): `fpdf2` (PDF rendering), `psycopg` + `psycopg-binary` (Postgres driver). These are dynamically linked Python imports; the existing relink/replacement note in `THIRD_PARTY_NOTICES.md` applies and now has machine-checkable evidence for which versions.
- `pyphen` carries a triple `GPL-2.0-or-later / MPL-1.1 / LGPL-2.1-or-later` declaration; it is only reachable through fpdf2's text hyphenation and is NOT GPL-elected by our use (the LGPL/MPL option applies), but this is exactly the class of entry the release checklist should re-check when fpdf2 moves.
- MPL-2.0 entries (certifi, axe-core, lightningcss, playwright, hypothesis, pathspec) are file-level copyleft: unmodified use, no source-disclosure trigger for our files.
- Font assets are OFL-1.1 (`hind-siliguri`, `noto-sans-bengali`) — self-hosted, licence text bundled in THIRD_PARTY_NOTICES.md.
- Components with no licence metadata: uharfbuzz. `bangla-gpt-api` is this repository itself; the others need manual licence lookup at release time (they are pinned by the lockfiles).

Regenerate with the commands in `docs/security/sbom/README.md`.
