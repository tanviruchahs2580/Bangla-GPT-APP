# OpenSSF Best Practices — self-assessment (Passing level)

Assessed: 2026-10-18, at commit `0b7dfe6` (branch
`chore/enterprise-hardening-20261018`). Source of the criteria list: the
OpenSSF Best Practices Badge "FLOSS Best Practices Criteria (Passing Badge)"
page, <https://www.bestpractices.dev/en/criteria/0>, fetched 2026-10-18
(evidence `E-FIX-JK-012`). Criterion ids below are the badge form's own ids.

This is a **self-assessment**, not a certification: the project has not been
submitted at bestpractices.dev and no badge is claimed anywhere. Recorded by
engineering under audit work item K-11. Status legend:

- **MET** — evidence exists today and is cited.
- **PARTIAL** — some of the requirement is satisfied; the gap is named.
- **UNMET** — not satisfied; the gap is named with its owner action.
- **N/A** — the criterion does not apply (justification given).
- **UNKNOWN** — cannot be determined yet (no data).

## Basics

| # | Criterion (id) | Status | Evidence / gap |
|---|---|---|---|
| 1 | Project website describes the software (`description_good`) | MET | `README.md` purpose section + `docs/` index; `docs/ai-system-card.md` §1 states intended use |
| 2 | How to obtain, give feedback and contribute (`interact`) | MET | `README.md` quick start, `SUPPORT.md`, `CONTRIBUTING.md` |
| 3 | Contribution process explained (`contribution`) | MET | `CONTRIBUTING.md` (branch, commit, PR, review rules) |
| 4 | Requirements for acceptable contributions (`contribution_requirements`) | MET | `CONTRIBUTING.md` definition-of-done table + Guardrails CI job (`ci.yml:335`) |
| 5 | Released as FLOSS (`floss_license`) | MET | `LICENSE` (MIT) |
| 6 | Licence OSI-approved (`floss_license_osi`) | MET | MIT is OSI-approved; `THIRD_PARTY_NOTICES.md` lists bundled licences |
| 7 | Licence in a standard location (`license_location`) | MET | `LICENSE` at repository root |
| 8 | Basic documentation (`documentation_basics`) | MET | `docs/README.md`, `docs/runbook.md`, `docs/operations/*`, `docs/adr/ADRs.md` |
| 9 | Reference documentation for the external interface (`documentation_interface`) | MET | `docs/API.md` + the FastAPI OpenAPI schema (134 operations; contract tests `tests/test_openapi_contract.py`, `tests/test_openapi_auth_matrix.py`) |
| 10 | HTTPS for project sites (`sites_https`) | MET | GitHub serves the repository over HTTPS; the hosted deployment uses Caddy TLS (`deploy/caddy/Caddyfile`) |
| 11 | Searchable discussion mechanism (`discussion`) | PARTIAL | Issues + PRs are searchable and the tracker is enabled, but zero issues have ever been filed (AUD-JK-08); discussion happens in PRs today |
| 12 | English documentation and bug reports (`english`) | MET | All living docs and templates are in English (Bangla exists only as product copy) |
| 13 | Project is maintained (`maintained`) | MET | 290 commits on `HEAD`, latest 2026-10-18; CI on every push (`ci.yml:4-11`) |

## Change control

| # | Criterion (id) | Status | Evidence / gap |
|---|---|---|---|
| 14 | Publicly readable version-controlled repository (`repo_public`) | MET | `https://github.com/tanviruchahs2580/Bangla-GPT-APP` (public) |
| 15 | Tracks what/who/when (`repo_track`) | MET | git history; Conventional Commits + `CHANGELOG.md` generated from history with a CI gate (`apps/api/scripts/check_changelog.py`) |
| 16 | Interim versions for review, no unversioned releases (`repo_interim`) | MET | Feature branches + PRs (e.g. PR #30); release workflow publishes only tagged builds (`.github/workflows/release.yml:83`) |
| 17 | Distributed version control (`repo_distributed`) | MET | git |
| 18 | Unique version per release (`version_unique`) | MET | Annotated SemVer tags `v0.1.0-rc1`…`v0.9.2`; `scripts/check_version.py` now asserts the recorded version agrees everywhere |
| 19 | SemVer/CalVer suggested (`version_semver`) | MET | SemVer 2.0.0 tags |
| 20 | Release identified in version control (`version_tags`) | MET | 13 annotated tags (`E-JK-046`) |
| 21 | Release notes per release (`release_notes`) | PARTIAL | `CHANGELOG.md` is generated per release, but **no GitHub Release objects exist** for any tag, so there are no published release notes (AUD-JK-06; owner action) |
| 22 | Release notes list fixed vulnerabilities (`release_notes_vulns`) | UNKNOWN | No CVE-assigned vulnerability has been fixed in a release to date; the process is untested (state it as such in the first release that fixes one) |

## Reporting

| # | Criterion (id) | Status | Evidence / gap |
|---|---|---|---|
| 23 | Bug-report process (`report_process`) | MET | `.github/ISSUE_TEMPLATE/bug.yml` + `SUPPORT.md` |
| 24 | Issue tracker used (`report_tracker`) | PARTIAL | A tracker exists and templates are substantive, but no issue has ever been filed; template label references (`needs-triage`, `needs-review`) do not exist as labels yet (AUD-JK-08; labels are an owner action) |
| 25 | Acknowledge most bug reports (2–12 months) (`report_responses`) | UNKNOWN | No bug reports in the window (tracker unused) — cannot demonstrate |
| 26 | Respond to a majority of enhancement requests (`enhancement_responses`) | UNKNOWN | Same as #25 (SUGGESTED level) |
| 27 | Publicly searchable archive of reports (`report_archive`) | MET | GitHub issues + PRs are public and searchable (currently 8 open PRs, `E-JK-045`) |
| 28 | Published vulnerability-report process (`vulnerability_report_process`) | MET | `SECURITY.md` (scope, targets, "do not open a public issue") |
| 29 | Private channel for vulnerability reports (`vulnerability_report_private`) | MET | `SECURITY.md` documents the maintainer email as the working private channel; note GitHub private vulnerability reporting is **disabled** on the repository, so the in-GitHub form is absent (AUD-JK-01; owner action to enable) |
| 30 | Initial response to a vulnerability report ≤ 14 days (`vulnerability_report_response`) | UNKNOWN | No report received in the last 6 months; the documented target is 3 working days, stricter than the criterion, but unproven |

## Quality

| # | Criterion (id) | Status | Evidence / gap |
|---|---|---|---|
| 31 | Working build system (`build`) | MET | `Dockerfile` (digest-pinned), `docker-compose.yml`, `Makefile` (`make setup`), `.github/workflows/ci.yml` docker job |
| 32 | Common build tools (`build_common_tools`) | MET | pip + setuptools, npm, Docker (SUGGESTED level) |
| 33 | Buildable with only FLOSS tools (`build_floss_tools`) | MET | Python, Node, Docker and every dependency are FLOSS (SUGGESTED level) |
| 34 | Automated FLOSS test suite (`test`) | MET | pytest suites in `apps/api/tests/` (1,106+ tests) and vitest in `apps/web/src`; both run in CI |
| 35 | Standard test invocation (`test_invocation`) | MET | `pytest`, `npm test`; documented in `CONTRIBUTING.md` and wrapped by `make test` |
| 36 | Test suite covers most branches/inputs (`test_most`) | MET | Coverage 92.54 line / 86.22 branch at baseline (`E-EF-001`) (SUGGESTED level) |
| 37 | Continuous integration (`test_continuous_integration`) | MET | `ci.yml` on push + PR, six jobs (SUGGESTED level) |
| 38 | Policy that new functionality is tested (`test_policy`) | MET | `CONTRIBUTING.md` "New behaviour has a test that fails without the change" |
| 39 | Policy adhered to in recent changes (`tests_are_added`) | MET | The hardening commits shipped tests with the fixes (e.g. `7a9f383`, `689c0e9`, `145a0ab`) |
| 40 | Policy documented in change-proposal instructions (`tests_documented_added`) | MET | `CONTRIBUTING.md` + PR template checkbox (SUGGESTED level) |
| 41 | Warning flags / linter enabled (`warnings`) | MET | ruff (API), mypy, ESLint `--max-warnings 0`, prettier (all in CI) |
| 42 | Warnings addressed (`warnings_fixed`) | MET | Lint/type steps are failing gates, so the tree is warning-clean by construction (`ci.yml:74-80`) |
| 43 | Maximally strict warnings where practical (`warnings_strict`) | MET | `--max-warnings 0`; ruff + mypy blocking (SUGGESTED level) |

## Security

| # | Criterion (id) | Status | Evidence / gap |
|---|---|---|---|
| 44 | Primary developer knows secure design (`know_secure_design`) | MET (self-attested) | Sole maintainer; design decisions recorded in `docs/adr/ADRs.md` and `docs/threat-model.md` |
| 45 | Knows common error classes (`know_common_errors`) | MET (self-attested) | `docs/owasp_checklist.md` maps each OWASP Top-10 (2021) class to controls and tests; `docs/threat-model.md` covers STRIDE + OWASP LLM Top 10 (2025) |
| 46 | Published, reviewed crypto only (`crypto_published`) | MET | Argon2id, PBKDF2 (verification only), Fernet/AES-128-CBC+HMAC, HS256 JWT, SHA-256 (`docs/owasp_checklist.md` A02) |
| 47 | Use a proven crypto library rather than rolling your own (`crypto_call`) | MET | `cryptography`, `argon2-cffi`, `PyJWT` only (`THIRD_PARTY_NOTICES.md`) |
| 48 | Crypto implementable with FLOSS (`crypto_floss`) | MET | All crypto dependencies are FLOSS |
| 49 | Default key lengths meet NIST minimums (`crypto_keylength`) | MET | Argon2id 19 MiB/2 iterations; AES-128 equivalents via Fernet; JWT secret keyboard length enforced at boot (`enforce_production_safety`, `main.py:72`) |
| 50 | No broken algorithms by default (`crypto_working`) | MET | No MD5/SHA-1 for security purposes; legacy PBKDF2 accepted only for verification with in-place rehash |
| 51 | No algorithms with known serious weaknesses (`crypto_weaknesses`) | MET | No RC4/3DES/ECB; single HS256 secret is a documented PARTIAL in the OWASP checklist (rotation item) |
| 52 | Perfect forward secrecy for key agreement (`crypto_pfs`) | N/A | The application does not terminate TLS or implement key agreement; Caddy handles TLS (SUGGESTED level) |
| 53 | Password storage per OWASP cheat sheet (`crypto_password_storage`) | MET | Argon2id `time_cost=2, memory_cost=19 MiB, parallelism=1` (`auth/security.py:20`); `tests/test_password_hashing.py` |
| 54 | Keys and nonces from a CSPRNG (`crypto_random`) | MET | `secrets`/`os.urandom`-backed generation in auth code; Fernet key generation documented in `.env.example` |
| 55 | Delivery counters MITM (`delivery_mitm`) | MET | HTTPS everywhere (GitHub, Caddy TLS, GHCR); no plaintext delivery path |
| 56 | No unsigned hash fetched over HTTP (`delivery_unsigned`) | MET | Dependencies install from hash-pinned locks over HTTPS; container base pinned by digest |
| 57 | No unpatched publicly known vulns > 60 days (medium+) (`vulnerabilities_fixed_60_days`) | PARTIAL | `pip-audit` + `npm audit` are failing gates (`ci.yml:114`, `:313`) and the register is `docs/security_scans.md` with waivers + expiry in `docs/dependency_waivers.md`; **Dependabot alerts are disabled platform-side**, so alert triage cannot be demonstrated (AUD-JK-02, owner action) |
| 58 | Critical vulnerabilities fixed rapidly (`vulnerabilities_critical_fixed`) | MET | No critical vulnerability has been reported; two S1-class findings were fixed within the audit round (commits `4735d5b`, `1121925`) (SHOULD level) |
| 59 | No leaked valid credentials in public repos (`no_leaked_credentials`) | PARTIAL | gitleaks full-history scan in CI (`ci.yml:417`), `detect-private-key` hook; no `.env`/key material was ever committed. A historic `apps/api/dev.db.bak-wave2` containing **password hashes** of synthetic test accounts remains in history (AUD-JK-04) — not a usable credential, but recorded rather than hidden (owner decision) |

## Analysis

| # | Criterion (id) | Status | Evidence / gap |
|---|---|---|---|
| 60 | Static analysis tool applied (`static_analysis`) | MET | CodeQL (`.github/workflows/codeql.yml`, configured by `.github/codeql-config.yml`); ruff/mypy also run |
| 61 | Rules cover common vulnerabilities (`static_analysis_common_vulnerabilities`) | MET | CodeQL default suites include injection/XSS classes; the 6 open alerts are JS/TS XSS class (SUGGESTED level) |
| 62 | Static-analysis findings fixed in a timely way (`static_analysis_fixed`) | PARTIAL | The `js/xss-through-dom` and `js/incomplete-multi-character-sanitization` findings are fixed on this branch (`1121925`); the alert objects on `main` close after merge + analysis (`E-FIX-JK-002`) |
| 63 | Static analysis on every commit or daily (`static_analysis_often`) | MET | CodeQL workflow runs on push/PR + schedule (SUGGESTED level) |
| 64 | Dynamic analysis before releases (`dynamic_analysis`) | PARTIAL | The acceptance protocol (Playwright journeys) and load-test script exist, but no DAST tool or container scan runs in CI in this environment (`.audit/reports/FINAL.md` §10) (SUGGESTED level) |
| 65 | Memory-unsafe-language dynamic analysis (`dynamic_analysis_unsafe`) | N/A | Python + TypeScript only (SUGGESTED level) |
| 66 | Assertions enabled in dynamic analysis (`dynamic_analysis_enable_assertions`) | MET | pytest runs with assertions enabled; production refuses debug/test posture at boot (`main.py:72`) (SUGGESTED level) |
| 67 | Dynamic-analysis findings fixed (`dynamic_analysis_fixed`) | UNKNOWN | No DAST run has produced findings yet |

## Summary and owner actions

- MET: 53 · PARTIAL: 7 · UNKNOWN: 5 · N/A: 2 · UNMET: 0 (of 67 rows).
- Before claiming the badge publicly, the owner should close: release notes
  (#21), issue-tracker use (#24), private-reporting enablement (#29),
  Dependabot/secret-scanning settings (#57), and record one dynamic-analysis
  run (#64). The exact `gh api` payloads are in
  `.audit/handoffs/ef-from-jk.md`.
- Registering the project at <https://www.bestpractices.dev> and adding the
  resulting badge to `README.md` is an owner action (a badge cannot be claimed
  before the assessment is submitted there).
- Re-assess when the blocking owner actions land; several UNKNOWN rows become
  MET or PARTIAL with data.
