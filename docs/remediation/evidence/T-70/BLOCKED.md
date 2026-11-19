# T-70 — version normalization to 0.2.0: BLOCKED on a false prompt premise + store-version conflict

**Status: BLOCKED (STOP S-3 + §0.3 override), with the full inventory prepared.**

## The prompt premise is false (H-6/§0.3)
V2 §3.3/F-21 states the app "is reported to declare 1.x today" and T-70 step 8's template text presumes "renumbered from 1.x to 0.2.0". **The repository declares 0.15.0** with a published release lineage (`CHANGELOG.md` v0.15.0 2026-11-18; GitHub Release v0.15.0; signed vc236 APK/AAB = versionName 0.15.0 verified at release).

## Renumbering 0.15.0 → 0.2.0 would break the store chain
`docs/playstore/` exists and versioned artifacts were distributed through Google Play (signed vc236 = 0.15.0). Play Store update rules refuse a versionName LOWER than one already published: shipping 0.2.0 after 0.15.0 makes every future store update impossible until a higher versionName is minted — a real, irreversible deployment breakage. The card's own step 4 ("build counters never decrease… store rules… record this risk") acknowledges the class of hazard; applying the letter of BC-10 here would violate the higher-precedence behavior-preservation contract (§0.3: prompt wrong about the repository → follow the code).

## Inventory prepared (this task's deliverable, `version-inventory.txt`)
| Declaration | Value |
|---|---|
| apps/api/pyproject.toml `version` | 0.15.0 (single source of truth per android/app/build.gradle comment) |
| apps/web/package.json + package-lock root | 0.15.0 |
| OpenAPI `info.version` (baseline) | 0.15.0 |
| Android versionName | derived from the web version at build time (CI-only builds) |
| PWA manifest | no version field |
| Docker `APP_VERSION` build arg | supplied by release workflow (CI-only) |
| README badge/mentions | 0.15.0 |
| CHANGELOG | v0.15.0 latest entry |
| Consumers | `versionParity.test.ts` (release-version parity gate); no semver comparison against 1.x found in the scanned consumers |

## Owner decision required (S-3e)
Options: (A) keep 0.15.0 and treat the remediation line as 0.15.x/0.16.0 (recommended — the store lineage stays monotonic; BC-10's intent — an honest pre-1.0 marker — is already met by 0.15.0 < 1.0.0); (B) renumber to 0.2.0 and accept the store cost (requires abandoning the current Play listing or a higher-versionName bridge release); (C) renumber to 0.16.0 with the remediation changes (keeps monotonicity, marks the remediation line).
**Nothing was renumbered.** No tag or release was created (card Never).
