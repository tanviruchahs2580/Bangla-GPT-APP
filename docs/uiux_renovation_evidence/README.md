# UI/UX evidence screenshots — why the PNGs are committed

This directory holds the visual evidence for the UI/UX renovation waves
(2026-08..09) and the live-deployment checks that followed. It is **evidence,
not product assets**: nothing here is shipped to users or referenced by the
application at runtime.

## What is here

| Directory | Contents | Largest wave |
| --- | --- | --- |
| `before/`, `after/` | Public-route and dashboard screenshots taken before and after the first renovation wave, light and dark | 2.4 MB / 1.4 MB |
| `wave4/before/`, `wave4/after/` | The same pairs for the wave-4 redesign (welcome, login, student home, live tunnel) | 6.2 MB |
| `mobile-audit/before/`, `mobile-audit/after/` | Mobile-width snapshots for the responsive repair | 1.2 MB |
| `vercel/` | Deployment-time screenshots of the hosted preview | 0.8 MB |

74 files, 12.7 MB on disk, largest single file ~753 KiB (measured 2026-10-18;
audit evidence `E-FIX-JK-010`).

## Why they are in git rather than in an artifact store

- They are review artifacts: a reviewer must be able to see the visual state a
  pull request changed without a network dependency or an expiring link.
- They are cited by the QA and renovation notes as the evidence for
  accessibility/visual claims; a citation that resolves to a downloaded
  archive is not reviewable.
- The size is within what a normal clone handles (the whole repository object
  database is 41.3 MiB, including history), and there is no Git LFS
  dependency in the project.

The trade-off, the alternatives and the threshold for revisiting this choice
are recorded in [`docs/adr/ADR-0011-data-and-artifact-management.md`](../adr/ADR-0011-data-and-artifact-management.md).
If the set grows past roughly 100 MB, re-open the LFS question there with a
measured size budget.

## Rules for adding screenshots

- Name files for what they show and the state they show it in
  (`new-login-light.png`, `live-tunnel-login-en-dark.png`); pairs stay in the
  matching `before/` and `after/` directory.
- Never capture a real student's data. Seed/test accounts only — this
  repository is public and the product holds children's personal data.
- Keep a single capture under 512 KiB where possible (the pre-commit
  `check-added-large-files` limit is 512 KB; existing files above it predate
  the hook).
- Do not add screenshots for a change that has a cheaper assertion (a test, an
  axe result or a computed metric). This directory is for what only an image
  can show.
