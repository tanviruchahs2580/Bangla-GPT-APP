> **Historical, not current.** Kept for history only; this snapshot does
> not describe the current tree and must not be quoted as current status.
> Current sources of truth: [../README.md](../README.md).

# RELEASE READINESS — Bangla GPT APP (2026-10-16)

## Verdict

**NOT RELEASE-READY (NO-GO)** for a release decision, with the audit scope
itself reported as **PARTIALLY VERIFIED**.

Two separate statements, kept distinct on purpose:

1. **Gate decision — NO-GO.** Three P1 findings remain unresolved and each one
   is a release-blocking class per the audit's own decision rules: a cross-tenant
   read of generated content (`F-09`), a release path that ships untested code
   (`F-10`), and Android release artifacts that cannot be built from the
   repository (`F-12`).
2. **Verification scope — PARTIALLY VERIFIED.** Everything that can be checked
   from this checkout was checked and is green: the full API suite, the full web
   suite, lint, type checks, build, migrations, guardrail scripts, and a live
   browser pass over 12 screens against a real running stack. What could **not**
   be checked is material: GitHub provider settings, remote CI runs, production
   or staging behaviour, Android signing/device builds, real-provider AI
   behaviour, and screen-reader verification. Those are `NOT VERIFIED`, not
   passed.

A green local build is not release approval, and this document does not treat it
as one.

## Blocking items (must be resolved or formally accepted by the owner)

| ID | Severity | Blocker | Why it blocks |
|---|---|---|---|
| `F-10` | P1 | Tags run no CI, and the deploy pulls a mutable image tag rather than the digest the workflow attested | Any commit can be tagged and shipped without lint/tests/eval, and the deployed image is not bound to the verified artifact |
| `F-09` | P1 | `ChapterContent` has no tenancy column; `GET/PUT /teacher/content` cross school boundaries | Confirmed cross-tenant read of teacher-generated content (no student PII in that table) |
| `F-12` | P1 (mobile) | `gradle-wrapper.jar`, launcher/splash assets and `data_extraction_rules.xml` are untracked | A clean clone cannot produce a release APK; mobile releases are not reproducible |

## Should-fix before or immediately after launch

`F-24` (production deploy ignores the AI eval gate) · `F-13`/`F-30` (accessibility:
skip link, `<h1>`, live-region scope, focus under the fixed mobile bar) ·
`F-23` (Vercel token material in the web image build context) · `F-22` (compose
publishes the API on all interfaces when the port variable is empty) ·
`F-26` (class selector offers classes with no content and shows a blank page) ·
`F-20`/`F-21` (eval gate fails open; unpinned eval install) · `F-11` (CSV import
hashing cost) · `F-19` (school invite entropy) · `F-16` (prettier drift) ·
`F-17`/`F-33`/`F-31` (unverifiable or untranslated copy).

## What is verified for this release candidate

| Dimension | Status | Evidence |
|---|---|---|
| API test suite | GREEN | `pytest -q` → 828 passed, 6 skipped (`logs/final_api_gates.log`) |
| Web test suite | GREEN | `vitest run` → 162 passed / 48 files (`logs/final3_web_gates.log`) |
| Lint / format / types | GREEN | ruff check + format, mypy, eslint (`--max-warnings 0`), `tsc` via build |
| Production build (web) | GREEN | `tsc && vite build` succeeded |
| Migrations | GREEN | single head; fresh-DB `alembic upgrade head` + `alembic check` → no drift |
| Guardrails | GREEN | README contract, changelog, i18n checker all exit 0 (the README contract was broken at baseline and is fixed) |
| Critical journeys | GREEN (local, mock provider) | live browser pass: login → tutor answer → quiz → reader → report → teacher hub |
| Feature preservation | GREEN | 136-operation API matrix + 22 frontend routes have a recorded outcome; nothing was removed (see `FEATURE_REGRESSION_MATRIX.md`) |
| Gates weakened | NONE | suite grew 824→828 and 156→162; no test deleted, skipped or loosened; no suppression added |

## Deployment prerequisites (before the next deploy attempt)

1. Commit and push the owner's in-progress work together with this audit's
   changes; confirm CI is green on the pushed SHA (this audit cannot observe CI).
2. Add the Android wrapper and launcher assets to version control, then verify a
   clean-clone release build (`F-12`).
3. Decide and implement the `ChapterContent` tenancy question (`F-09`).
4. Confirm the `production` environment has required reviewers and that the
   deploy binds to the attested digest (`F-10`).
5. Re-check provider retention/training settings and record them in the privacy
   docs (currently `NOT VERIFIED`).

## Rollback notes

The image is published per release tag and the host checks out the release tag,
so a rollback is a redeploy of the previous tag; the previous image remains in
the registry. Database changes are additive migrations with a working
`downgrade` path (`ci.yml` runs upgrade → downgrade → upgrade on every build),
so a schema rollback is available for this revision. **Not verified here:** that
the host's compose file, secrets and volume layout still match the tag being
rolled back — that requires the deploy host. `NOT VERIFIED`.

## Release decision rule applied

Per the audit's gate: an unresolved P1, an unverified critical control, or
unsafe deployment uncertainty ⇒ NO-GO. This revision has all three. The
decision is based on evidence in `AUDIT_FINDINGS.md`, not on a score.
