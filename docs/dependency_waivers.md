# Dependency risk waiver register

A waiver says: *we know about this, we are choosing not to fix it yet, and
here is why and when we will reconsider.*

There was no register, so two High advisories in the development dependency
graph had been noted in a comment and then forgotten (F-030). An unrecorded
decision to defer is indistinguishable from not having looked.

## How a waiver works

1. Add a row below with the advisory id, the package, and a date.
2. State the exposure in one sentence: who can reach it, and what it gives
   them. "Dev-only" is an exposure, not a dismissal.
3. State the compensating control that exists **today**.
4. Give an expiry date. A waiver without an expiry is a permanent
   exception wearing a date.

A waiver expires into the backlog automatically. When it does, either fix
it or write a new row explaining why the date moved — a row that quietly
changes its date is worse than no register.

## Current waivers

| Advisory | Package | Severity | Exposure | Control today | Raised | Expires |
|---|---|---|---|---|---|---|
| GHSA-67hx-6x53-jw92 (`source-map-js`) | `source-map-js` (transitive, via `vite`) | High | Dev dependency. It only runs in the browser dev server while developing; it is not bundled into `dist/`. A developer running the dev server on a shared or public network is exposed to source-map disclosure of the running app. | `npm audit --audit-level=high --omit=dev` gates the **production** dependency set and passes. The dev server binds to localhost by default. No upstream fix is published. | 2026-10-15 | 2026-11-15 |
| GHSA-g5qg-72qw-gw5v (`vite` `server.fs.deny` bypass on Windows) | `vite` (dev) | High | Dev dependency, Windows-only path handling. Requires a crafted request to the dev server on Windows. | Same as above: `--omit=dev` gate is green; the dev server is not part of any deployed artifact. | 2026-10-15 | 2026-11-15 |

## Explicitly not waived

- **Any advisory in the production dependency set** (`pip-audit` over
  `constraints.txt`, `npm audit --omit=dev`, Trivy over the built image).
  These fail CI rather than being triaged here.
- **Any advisory in a direct runtime dependency** of the API or the web
  app. Fix or pin; do not defer.

## Re-checking

Advisory data is refreshed by:

```
python -m pip_audit -r apps/api/constraints.txt
npm audit --audit-level=high --omit=dev --prefix apps/web
```

The dev-graph advisories above are deliberately **not** in CI: gating on
them would red the build for findings that are unreachable in any deployed
artifact, and a permanently red gate is a permanently ignored gate. This
register is where that decision is recorded instead.
