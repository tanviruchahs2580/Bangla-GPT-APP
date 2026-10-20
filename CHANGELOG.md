# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> **How this file is produced.** Entries are generated from the git commits
> each tag actually contains, grouped by conventional-commit type. They are
> a record of what changed, not a claim about user impact - when that
> matters it belongs in the release notes on the GitHub Release, which the
> release workflow generates from these same commits.

## Unreleased

### Added

- feat(api): logout token revocation, security headers, infra hardening and privacy docs
- feat(api): production connection posture, truthful readiness, boot index metric; full-suite Postgres parity in CI (#29)
- feat(api): render errors as RFC 9457 problem+json, additively
- feat(api): strict schemas, idempotent writes, streamed CSV import, one pagination policy
- feat(auth): rotating refresh tokens, impersonation limits, central tenancy filter
- feat(eval): live model run with recorded responses, replayed in PR CI
- feat(eval): reconstruct the golden set independently; widen red-team to 43 cases
- feat(eval): variant matrix, held-out targets with CIs, index budget, ANN sweep, one rag-eval command
- feat(i18n): land Bangla copy for the status and impersonation strings
- feat(mobile): fail-closed Play Store signing, AAB build path, launch runbook
- feat(obs): per-stage traces, business metrics, SLO/runbook, cost dashboard and generated API reference
- feat(quality): complexity/file-size/dead-code/deps/duplication ratchet + as-built architecture map
- feat(rag): event-loop hardening, hot-path observability, follow-up retrieval; gate CI on retrieval baselines + CodeQL SAST (#27)
- feat(rag): rank-aware retrieval metrics, chunk-boundary rules, index lifecycle and corpus dedupe
- feat(rag): retrieval-quality rework - fair gate, query lanes, measured rank lift
- feat(rag): token-budgeted context, versioned prompts, hint-first pedagogy, wider safety sets
- feat(web): Bangla i18n glossary, native-review sheet, offline quota, TTS controls and dialog unification
- feat(web): a11y/perf/visual suites, shared settings components, consent-gated telemetry UI
- feat(web): login page background image with dark/light theme sync
- feat(web): student section background image with dark/light sync

### Fixed

- fix(api): P4 cleanup batch — chunk-id content hash, lesson echo gate, proportional Latin penalty, corpus-scoped RAG keys, history char cap (A20-A25)
- fix(api): align the served OpenAPI contract with runtime behaviour
- fix(api): burn pending verification codes when a new one is issued
- fix(api): close two moderation false negatives and cover the chat routes
- fix(api): derive the school analytics day window in Asia/Dhaka
- fix(api): drop an unused variable the new RUF059 rule caught
- fix(api): drop the unverified helpline number from self-harm support copy
- fix(api): flush SSE streams through buffering proxies
- fix(api): gate evals on hybrid retrieval, de-tautologize golden set, precompute BM25 trigrams, single-pass redteam (A13, A8, A18)
- fix(api): harden authentication, session end and abuse limits
- fix(api): impersonation revocation fails closed when cache is down (F-08)
- fix(api): issue verification codes to invited school staff
- fix(api): let a student clear their subject focus
- fix(api): make question-paper marks, difficulty buckets and integer parsing truthful
- fix(api): make the account export complete
- fix(api): one weak-chapter rule, a survivable mastery rollup and content-verified images
- fix(api): record an explicit auth decision on every public operation
- fix(api): redact exception tracebacks in logs
- fix(api): refuse account deletion from an impersonation session
- fix(api): remove the dead 'answer is None' regeneration branch (A25)
- fix(api): repair corrupted Bengali in tutor prompts, feedback IDOR, dead code
- fix(api): repair the retrieval evaluation's coverage-gate call
- fix(api): restore middleware_stack and circuit_breaker to last-green versions
- fix(api): restore the documented build_limiter patch seam in create_app
- fix(api): retry create_all on the schema race between booting workers
- fix(api): rotate token epoch on password change/reset — sessions revoke (F-05)
- fix(api): ruff format circuit_breaker
- fix(api): ruff format middleware_stack
- fix(api): scope chapter-content writes to the author's school
- fix(api): serve the configured corpus and the Dhaka day in the Learn flow
- fix(api): tie the quiz ceilings to one bound so an assignment stays submittable
- fix(api): vision-honest refusal for openai, max_output_tokens cap, transport retries (A10, A9, A16)
- fix(api): wall school-less staff into the shared default school (F-04)
- fix(api,web): audit remediations — breaker recovery, MFA/chat rate limits, CORS PATCH, model-refusal honesty, test runner
- fix(auth): bind JWTs to an issuer and audience
- fix(auth): hash passwords with Argon2id and upgrade legacy hashes on login
- fix(auth): redeem single-use codes with a compare-and-set, not a read-then-write
- fix(auth): unblock login on web and APK (MFA step-up, unauth resend, proxy/APK errors)
- fix(ci): drop the two out-of-convention shebangs; format the datetime test
- fix(ci): exempt changelog-regenerating commits by changed paths, not subject text
- fix(ci): make the commit-subject gate testable anywhere; lint fixes the CI run caught
- fix(ci): make the doc-path guard cover the classes of path it claims to
- fix(ci): make the lockfile guardrail deterministic
- fix(ci): pin every action to a commit SHA and scope registry permission
- fix(ci): repair two gates that could not fail, and stop the impossible redis bump
- fix(ci): resolve README links portably so the docs guard works on Linux
- fix(ci): serialise release and deploy runs per git ref
- fix(ci): unblock Dependabot PRs and name the Vercel credential failure (#9)
- fix(ci): upgrade setuptools before pip-audit; refresh lock to current resolution
- fix(compose): writable HOME for gunicorn's control socket; drop the dead SettingsRegistry
- fix(db): reconcile ORM/migration drift so alembic check passes
- fix(deps): declare packaging, the lockfile gate's own import
- fix(deps): declare radon, the one ratchet tool the script imports
- fix(deps): lock radon and make deptry's import mapping environment-independent
- fix(e2e): raise the harness login rate limit above the suite's own login volume
- fix(encoding): add .gitattributes and repair three encoding defects
- fix(i18n): put the parent digest and the printed papers in Bangla, and correct five copy defects
- fix(ops): point the Grafana dashboard at the exported metric names
- fix(ops): stop publishing the API on a random host port, and make the release gate real
- fix(pdf): enable Bengali complex-script shaping in PDF renderers
- fix(rag): enforce post-generation grounding (citation + numeric) instead of warning
- fix(rag): framing-plane coverage, cross-script gate resolution, in-corpus weighting
- fix(rag): locative reclassification + short-token roman guard
- fix(rag): report true recall@1 in retrieval evaluation
- fix(rag): roman-lane floor, edit-similarity rank, MRR unit, trailing newline
- fix(rag): runtime prompt-injection screening at the query boundary
- fix(rag): strip symbol-font PUA residue and gate corpus quality at build and load
- fix(rag): the chunk-ablation script crashed on the pages artifact
- fix(scripts): compute the benchmark's throwaway JWT value instead of writing a literal
- fix(scripts): set the executable bit on the three new shebang scripts
- fix(sec): refuse unsafe production defaults at boot
- fix(sec): stop serving the OpenAPI reference in production
- fix(tests): the live A/B assertion points at the committed record, not audit scratch
- fix(web): WCAG 2.2 fixes on the public routes
- fix(web): clear footer from bottom nav + cut a round-trip from login
- fix(web): clear the two WCAG AA failures axe found on the tutor screen
- fix(web): close-JSDoc sequence inside edge-proxy comment broke Vercel TS build
- fix(web): configurable production API origin via edge proxy (FE-01)
- fix(web): correct the password-hashing claim in the legal copy
- fix(web): drop the regex HTML stripper and guard the image-preview sink
- fix(web): guarantee minimum gap between stacked page sections
- fix(web): guard the tutor turn, bound stalled requests and clear data on sign-out
- fix(web): keep Enter out of IME composition and truncate by grapheme
- fix(web): let an anonymous visitor change the interface language
- fix(web): localize consent/invite copy, theme icon sync, error states, icon cleanup
- fix(web): make the register screen's email-verification step usable
- fix(web): modal focus/backdrop defects, truthful grounding UI, shared test harness
- fix(web): move the list key onto the element the map returns
- fix(web): notification panel no longer clipped off the left edge
- fix(web): raise three status tokens to the WCAG AA contrast minimum
- fix(web): recover from page errors, report load failures, and never show another child's data
- fix(web): report a dead API origin accurately, not as a busy server (#14)
- fix(web): route /api/* explicitly to the edge proxy function
- fix(web): stop rendering remote images in answers and announce each answer once
- fix(web): stop showing failures as facts, and read API timestamps as UTC
- fix(web): stop swallowing failed writes; roll back the bookmark toggle
- fix(web): verified visual baselines, three-engine green, Play Store listing assets
- fix(web,e2e): bn plural expectation, empty-sub geometry, ratchet line budget
- fix(web,e2e,scripts): close the CI failures the wave introduced
- fix: A7-05 per-role in-flight caps and A7-08 teacher AI disclaimer
- fix: complete admin password-change flow, tutor typo gate, roster-scoped stats, quiz distractors, i18n
- fix: land the verified remediation on current main (CORS-adjacent, budget, UI states)
- fix: resolve mypy 2.4.0 type errors in teacher/school/common/weakness
- fix: wave-4 closing batch — ratchet baseline, brand tokens, loade split, role caps, env parity
- fix: wave-4 quality batch — C-10 pagination parity, G-24 PDF None-render, D-16 in-app confirm, tokenizer unit collision

### Security

- security(school): bound staff invite codes to a lifetime

### Changed

- refactor(api): bring TutorService.ask/ask_stream down from grade E
- refactor(web): use one data-fetching path in the admin centre and the paper review panel

### Build and dependencies

- build(api): configure deptry for the src layout
- build(api): turn on mypy strictness per flag, with a written plan to the rest
- build(api): widen the ruff rule set from 5 families to 15, fixing what it found
- build(ci): add guardrails for coverage, migration drift, secrets and Bangla
- build(ci): let the changelog check tolerate its own regeneration commit
- build(deps): add Dependabot config for all four ecosystems
- build(web): add type-aware ESLint and fix the 175 findings it found
- build: lock the dependency set, pin the base image, and attest what ships

### CI/CD

- ci(mobile): avoid the reserved example domain in the android workflow comment
- ci(security): record the reviewed benchmark fixture in the gitleaks allowlist
- ci: add CI-gated Vercel production deploy workflow
- ci: add concurrency to api CI, fix eval-gate header, retire sanity workflow
- ci: bound job runtimes and harden release/deploy workflows
- ci: fetch tags in the make-parity job; record the last three commits in the CHANGELOG
- ci: gate a release on a successful CI run for the tagged commit
- ci: hermetic import-time settings patch + step-isolated migration DBs
- ci: lint/scan/replay jobs, prompt packaging, packaging locks, release attestations
- ci: require a real 200 before calling a web deploy healthy
- ci: run the skipped Redis and Postgres paths and enforce the hook set
- ci: wire the handoff gates into workflows

### Documentation

- docs(adr): record the data and artifact management decision (K-05)
- docs(audit): final audit report (INCOMPLETE — BLOCKED) + changelog refresh
- docs(audit): record the merge and live-production outcome
- docs(audit): refresh the audit report for the second remediation pass (61.0/100)
- docs(audit): wave-3 report — score 83.0/100, live evaluation closed, caps re-checked
- docs(changelog): record the CI-fix commits
- docs(changelog): record the e2e-evidence wave
- docs(changelog): record the wave-3 commits
- docs(compliance): record the provider's current terms, tier by tier (A7-04)
- docs(dx): threat model, AI system card, OpenSSF self-assessment, devcontainer and Make targets
- docs(qa): publish the 2026-10-16 audit report; refresh the lockfile within its ranges
- docs(qa): publish the 2026-10-17 QA record and archive its predecessor
- docs(qa): record the 2026-10-17 deployment and how it was verified
- docs(qa): record the CI evidence and the two honest notes in the record
- docs(qa): record the CI-found defects and the exit-gate assessment in the report
- docs(qa): record the explicit Vercel redeploy and the 61-check role-level live test
- docs(qa): record the fully green CI run and the final commit list
- docs(qa): record the post-merge CI evidence and the live Dependabot result
- docs(qa): record the registration-backdrop change and its deployment
- docs(qa): record the role-based acceptance run and the live deployment
- docs(rag): correct the measured-baseline table to the fixed harness
- docs(rag): quote the current artifact instead of the pre-regeneration numbers
- docs: add 2026-10-06 QA audit and final certification reports
- docs: add a CHANGELOG generated from git history, and a check that keeps it honest
- docs: add final QA report for 2026-10-07 UAT completion
- docs: audit wave-3 records, SBOM/DAST artefacts, tenancy and statelessness notes
- docs: correct stale facts and move point-in-time reports to the archive
- docs: fix the loader path named in the NCTB pipeline guide
- docs: name only paths that exist in the corpus and security guides
- docs: phase-2 CI/CD pipeline execution record (v0.9.2 shipped through full pipeline)
- docs: pin the deploy host key, make the quick starts real, and repair script hygiene
- docs: purge session-report accumulation, rewrite README, add docs index
- docs: record Vercel sync verification + fix git-push auto-deploy (root dir apps/web)
- docs: record final v0.9.2 live sync (tunnel host amd-reproduction-clips-cricket)
- docs: record the live enablement and fix the token rotation procedure
- docs: regenerate CHANGELOG
- docs: regenerate CHANGELOG for the branch commit
- docs: regenerate CHANGELOG for the current batch
- docs: regenerate the CHANGELOG for the 2026-10-17 audit fixes
- docs: regenerate the CHANGELOG for the QA-record amendment
- docs: regenerate the CHANGELOG for the RAG retrieval rework
- docs: regenerate the CHANGELOG for the acceptance-testing fixes
- docs: regenerate the CHANGELOG for the audit remediation commits
- docs: regenerate the CHANGELOG for the branch's final commits
- docs: regenerate the CHANGELOG for the delivery record
- docs: regenerate the CHANGELOG for the deployment record
- docs: regenerate the CHANGELOG for the gitleaks allowlist entry
- docs: regenerate the CHANGELOG for the injection screen
- docs: regenerate the CHANGELOG for the key-prop fix
- docs: regenerate the CHANGELOG for the locative reclassification fix
- docs: regenerate the CHANGELOG for the post-merge CI record
- docs: regenerate the CHANGELOG for the redeploy record
- docs: regenerate the CHANGELOG for the register-backdrop change
- docs: regenerate the CHANGELOG for the roman-lane fix
- docs: regenerate the CHANGELOG for the scripts commit
- docs: regenerate the CHANGELOG for the test and QA-record commits
- docs: regenerate the CHANGELOG for this branch's commits
- docs: satisfy the markdown and spelling gates the wave's new docs tripped
- docs: ship the bundled font's licence, third-party notices, contributing guide
- docs: the AI system card cites current numbers and an artifact that exists
- docs: truthful disclosure channel, corpus step, pipeline gate and PDF engine copy

### Tests

- test(api): cover school admin fallbacks and tenant guards
- test(api): make the injection-guard fixture grounded under the enforced contract
- test(e2e): Playwright smoke scaffold and a sqlite boot-timeout regression test
- test(e2e): scope the sign-out selector to the header
- test(e2e): wait for the session in signIn, not just the submit click
- test(school): cover the aggregation routes TST-04 flagged as unexercised
- test(tenancy): cover school dashboard routes across two tenants
- test(web): assert the changed behaviour instead of the old literals
- test(web): drop remaining plan-tracker tags from suite titles
- test(web): the i18n key scan uses a build-time glob, not a filesystem walk

### Maintenance

- chore(api): remove unresolvable plan-tracker tags from comments
- chore(scripts): make the shebang executable real for the five scripts that have one
- chore(security): allowlist the reviewed ASCII-art hit in the full-history secret scan
- chore(web): repoint /api proxy to current tunnel host (quick-tunnel rotation)
- chore: apply the repository's pre-commit hooks to the second-pass files
- chore: checkpoint before switching to main
- chore: code honesty - unused args, un-typed db params, inert suppressions, stale comments
- chore: satisfy the two CI guardrails main added after this branch's baseline
- fmt: ruff format teacher.py _room_counts

### Style

- style(api): format the new tutor seam tests
- style(api): reformat SchoolInvite claim call
- style(api): ruff format four test files (format-gate drift)
- style(api): ruff format mock provider and lesson plan prompt
- style(scripts): parenthesise the scanner's exemption reasons for ruff ISC004
- style(web): give the registration screen login's photo backdrop
- style: satisfy the repository's own pre-commit hooks

### Other

- Audit remediation, round 2: 38 findings closed across backend, privacy, auth and UX (#10)
- Full engineering audit + remediation: 47 findings fixed, 0 open (#1)
- Merge pull request #15 from tanviruchahs2580/audit/2026-10-16-live-verification
- Merge pull request #16 from tanviruchahs2580/docs/2026-10-16-live-outcome
- Merge pull request #17 from tanviruchahs2580/docs/2026-10-16-live-enablement
- Merge pull request #18 from tanviruchahs2580/qa/full-audit-hardening
- Merge pull request #22 from tanviruchahs2580/qa/2026-10-17-audit-hardening
- Merge pull request #24 from tanviruchahs2580/docs/2026-10-17-deployment-record
- Merge pull request #25 from tanviruchahs2580/docs/2026-10-17-vercel-redeploy
- Merge pull request #26 from tanviruchahs2580/feat/rag-retrieval-quality

## v0.9.2 - 2026-09-15

### Fixed

- fix(api): production-boot guard + Bangla input-boundary NFKC + hermetic tests
- fix(web): repoint /api proxy at live tunnel URL (live site was 502)

### Documentation

- docs: WAVE-5 mobile repair record (v0.9.1) — audit, fixes, pipeline evidence
- docs: enterprise QA audit evidence (2026-09-15) + ADR/architecture/ops records

### Maintenance

- chore(gitignore): exclude local mailpit TLS dir and production env file
- chore(release): v0.9.2 — live-hardening patch release
- chore(repo): move G3 seed script into scripts/, drop tracked DB backup blob


## v0.9.1 - 2026-09-13

### Fixed

- fix(web): WAVE-5 mobile responsive repair — topbar overflow, staff nav, snapshot squeeze (release 0.9.1)

### Documentation

- docs: WAVE-4 v0.9.0 pipeline + release record (CI 6/6 green, GHCR published, live verified)
- docs: fixed cross-domain demo credentials (student/teacher/parent @demo.com) + verification evidence

### Maintenance

- chore(web): ignore .vercel local project link dir

### Deployment

- deploy(web): Vercel production deployment — SPA + /api proxy rewrite (docs: deploy record)


## v0.9.0 - 2026-09-13

### Added

- feat(web): WAVE-4 national-scale brand & landing renovation — Shapla Book mark, ambient backgrounds, split landing (release 0.9.0)


## v0.8.1 - 2026-09-13

### Added

- feat(web): WAVE-3 visual renovation — premium buttons, motion, alignment (release 0.8.1)


## v0.8.0 - 2026-09-13

### Added

- feat(web): UI/UX polish wave-2 + teacher dashboard redesign, release 0.8.0

### Documentation

- docs: pipeline + release record for v0.7.0 (CI green, GHCR published, live verified)


## v0.7.0 - 2026-09-12

### Added

- feat(enterprise): modular bootstrap plus debt remediation, full CI green
- feat(web): world-class UI/UX renovation (WP-01 to WP-12)

### Fixed

- fix(ci): align tests with intentional health/SMTP/stream behavior, document metrics env
- fix(ci): drop unsupported pip-audit --fail-on flag
- fix(ci): smoke via openapi paths; trivy fail on fixable only
- fix(ci): use real trivy 0.58.0 image for vuln gate
- fix(docker): apt upgrade base layer so trivy gate stays green
- fix(infra): gate create_all only for postgres prod, keep sqlite for tests
- fix(security): remediation master prompt P0-P2 — F-SEC-01..04, F-PERF-01/02/04/05/06, F-DATA-01, F-SEC-05..07, F-AUTH-01/02, F-INFRA-01, baseline docs, live verified
- fix(stack): resilient nginx api proxy + analytics 401 funnel guard
- fix(tests): include SMTP in prod settings helper for PII guard
- fix(web): stop instant logout after login on transient failures

### Maintenance

- chore(release): bump version to 0.7.0


## v0.6.2 - 2026-09-09

### Fixed

- fix(tests): dynamic version assertion for health check (v0.6.2)


## v0.6.1 - 2026-09-09

### Fixed

- fix(i18n): Bangladesh Academy-standard Bangla — universal Noto Sans Bengali (v0.6.1)

### Documentation

- docs: final CI/CD report v0.6.0 — blueprint implementation release


## v0.6.0 - 2026-09-09

### Added

- feat(api): wave 2 — generators, notifications, ai_jobs, persistent entities
- feat(web): wave 2 — school dashboard, notification bell, CreateHub, i18n + fixes

### Fixed

- fix: minor fixes and test updates

### Documentation

- docs: final CI/CD execution report for release v0.5.0

### Maintenance

- chore(release): v0.6.0 — version bump + blueprint gap matrix


## v0.5.0 - 2026-09-08

### Added

- feat(0.1): gemini provider latency+usage logging; pooled client
- feat(0.2): mock leak guard test — system prompt never leaked (AUD-01)
- feat(0.3): markdown+KaTeX rendering — SafeMarkdown in tutor+learn, XSS guard, vitest
- feat(0.4): postgres pool config + pg_backup script, alembic drill on pg16
- feat(0.5): config hardening — gemini/CORS checks + negative prod test
- feat(0.6): observability — Sentry (api+web) + request_id in logs + Grafana dashboard
- feat(0.7): smoke.sh automated smoke + rollback doc (staging pending server)
- feat(1.1): dashboard/summary + Continue + Recommendation v1

### Fixed

- fix(api): FK-complete account deletion (DELETE /users/me)
- fix(api): ship knowledge-graph JSON and Bengali PDF font in the wheel
- fix(web): download the data export with the session token
- fix(web): merge tutor stream placeholder instead of rendering the answer twice

### Documentation

- docs(progress): BUG-4 narrative in Phase H entry and evidence log
- docs(progress): Phase H v0.5.0 finalization entry; honest gate headers
- docs(progress): S0.1 live verified with gemini (key in .env, not committed)
- docs(progress): update S0.1/S0.2 done with evidence
- docs(progress): update S0.3 commit hash
- docs(progress): update S0.4 hash
- docs(progress): update S0.5 hash
- docs(progress): update S0.6 hash
- docs(progress): update S0.7 hash
- docs(progress): update S1.1 hash
- docs(reports): S0 stage report + interim final report (3/64 steps)
- docs(reports): S0.1 live gemini verified, key in .env gitignored per SOP
- docs(reports): update S0 report + final report for S0.4-0.5
- docs(reports+progress): S0 G0 code complete (7/7), gemini live, S0.6/0.7 done
- docs: final CI/CD execution report for release v0.4.0

### Maintenance

- chore(release): v0.5.0 — version sync + README status
- chore(repo): track manifest PWA icons; ignore Capacitor scaffolds and scratch font dir

### Style

- style(api): ruff format S5/S6 files that predate the CI formatter

### Other

- commit all change following SOP and SWE best practices strictly


## v0.4.0 - 2026-09-03

### Added

- feat(api): v0.3 product features + AUD-01 fix, version 0.4.0
- feat(ops): concurrency probe + k6 tutor load script; env examples for invites/chat/safety
- feat(web): v0.4 UI — AppShell, i18n, PWA, student pages + bug fixes

### Fixed

- fix: mypy CursorResult cast for atomic quiz claim (CI typecheck gate)
- fix: post-build validation round - races, SAST, supply-chain, headers, hermetic tests

### CI/CD

- ci: vitest unit-test gate in web job; compose env for v0.3 services

### Documentation

- docs: CD executed to GHCR publish (v0.2.1) - monitoring/caddy/fresh-clone evidence; L6-L7 fixes recorded
- docs: final enterprise validation report - verdict B (production ready with documented limitations)
- docs: v0.3/v0.4 execution, validation, audit, roadmap and launch-readiness reports

### Maintenance

- chore(release): README status v0.4.0; ignore local live-test evidence


## v0.2.1 - 2026-08-26

### Added

- feat: NCTB acquisition + Bijoy-to-Unicode pipeline + real-corpus RAG integration
- feat: NCTB corpus wiring — sources inventory, config switch, provenance artifacts
- feat: enterprise hardening v0.2.0 — gap plan B1–B19 executed & verified
- feat: v0.2.1 - live Gemini verification & deployable-stage fixes

### Fixed

- fix(cd): lowercase GHCR image paths - repository names must be all-lowercase
- fix(cd): restore REGISTRY env for GHCR login
- fix(ci): postgres smoke fixture — PID-scoped database name (no xdist dependency)
- fix(ci): postgres smoke — create scratch database via raw psycopg (strip driver suffix)
- fix: real-corpus tests skip unless normalized chunk files exist (clean-env verified)

### Documentation

- docs: NCTB RAG architecture + data pipeline + final production audit (traceability RAG-001..046)
- docs: final delivery report — Phase 8 complete, v0.1.0-rc1 staged (67 tests, all CI gates green)
- docs: final enterprise report v0.2.0 — B1–B19 closure matrix, evidence, limitations
- docs: verified gap analysis + full deployment plan (B1-B19, ordered phases, complete parameter checklist)


## v0.1.0-rc1 - 2026-08-25

### Added

- feat: JWT auth, ownership enforcement, teacher class analytics
- feat: React web dashboard (apps/web) + CI web build job
- feat: admin RBAC, rate limiting, body-size guard, CI-verified container
- feat: observability, Alembic migrations, evaluation harness
- feat: parent dashboard with scoped child linkage
- feat: quiz engine, student profiles and progress tracking
- feat: scaffold API service with health endpoints, provider layer, CI
- feat: secure tutor endpoint, Prometheus metrics, self-service profile API
- feat: student domain core - curriculum ingestion, Bangla BM25 retrieval, tutor endpoint

### Fixed

- fix: correct env var name ENV and README import path

### CI/CD

- ci: exempt .env.example from tracked-env sanity check
- ci: fix smoke import path after removing eager package app export
- ci: upgrade setuptools on runners to clear PYSEC-2026-3447 audit finding

### Documentation

- docs: MIT license, API reference, ops runbook, README/architecture Phase 8
- docs: add final enterprise validation report (57 tests, 0 vulns, release candidate verdict)

### Maintenance

- chore: initialize repository
