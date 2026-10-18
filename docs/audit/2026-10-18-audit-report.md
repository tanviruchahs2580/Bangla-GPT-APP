# INCOMPLETE — BLOCKED

**Reason:** the repository was audited end to end and the tractable findings were fixed and
re-verified, but three gates cannot be made green in this run: **G4** (live-model RAG evaluation
— `GEMINI_API_KEY` is empty; recorded BLOCKED per the gate's own wording), **G3** (no DAST
baseline and no container scanner available in this environment; SARIF, SCA and secrets screens
are green), and **G10** (the user-simulation suite ran 11 journeys on the pushed head with 0
console errors, but the full mandatory archetype list was not executed inside this run's budget).
Everything claimed below is backed by an evidence file listed in `.audit/evidence/`.

| | |
|---|---|
| Repository | https://github.com/tanviruchahs2580/Bangla-GPT-APP (public, MIT) |
| Verified SHA | `e214a0b` on `chore/enterprise-hardening-20261018` (baseline `88ded22`); acceptance re-run on `3c28b42`; the report commit is a docs-only descendant |
| Pull request | [#30](https://github.com/tanviruchahs2580/Bangla-GPT-APP/pull/30) — **not merged** (merge is authorized only when G0–G9 are green; see the gate table) |
| Date | 2026-10-18 |
| Score | baseline **51.8 / 100** → achieved **52.1 / 100** (capped; uncapped 51.9 → 52.6); band: Beta/prototype (50–64) |
| Projected | ~60–65 if the owner actions and the four Domain A issues (#31–#34) land — projection, not a measurement |
| Issues opened | #31–#45 (15 deferred findings) |

## Gate table

| Gate | Verdict | Basis |
|---|---|---|
| G0 Reproducible build | **PASS** | fresh clone built and ran from the README (J-01 log; E-R-123 image build + `/health` 200 `/ready` 200, non-root uid 10001) |
| G1 Static quality | **PARTIAL** | format/lint/type green for both stacks (E-R-121, E-R-120); complexity, duplication and dead-code gates do not exist in the repo (AUD-CD-02/03, issues not yet opened for gates) |
| G2 Automated tests | **PASS (local+CI)** | 1112 passed / 6 skipped API (E-R-112), 237 passed web (E-R-125), alembic up→check→down→up (E-R-122), Postgres job green in CI |
| G3 Security | **PARTIAL** | secrets clean tree+history, pip-audit/npm-audit/bandit clean, CodeQL green, authz negative suites green (E-B-110..159); DAST baseline and container image scan not executed here; 4 open CodeQL alerts remain (2 addressed by 1121925, re-analysis pending) |
| G4 RAG quality | **BLOCKED** | replay/mock evaluation green (golden-set gate in CI); live-model evaluation impossible — key empty (AUD-A2-01, E-A2-806/807). Domain A ≤ 75% cap applied (no effect: 40.8%) |
| G5 Performance | **PARTIAL** | retrieval eval regenerated; latency host-dependent 93–1,010 ms p95 across runs (E-R-001/006/007); no load test executed (k6 absent) |
| G6 Accessibility & Bangla | **PARTIAL** | Lighthouse mobile a11y 1.00 on six public routes (E-R-105); authenticated-route axe unverified; screen-reader pass BLOCKED (none available); Bangla rendering verified in one engine only |
| G7 Anti-slop | **PARTIAL** | taxonomy sweep run (E-CD-020/022, E-A1-004/012); all known user-visible false claims corrected this run; cold-read protocol not completed (documented below) |
| G8 Docs verified | **PASS** | doc-path guard, changelog guard, i18n guard, mojibake scan all green (CI "Repository guardrails"); every command executed this run is logged |
| G9 CI/CD | **PASS (on this head)** | all workflows green on the PR head (API CI 3.11+3.12, Postgres, eval gate, benchmark, Docker, CodeQL, Vercel); least-privilege pins verified by zizmor/actionlint (E-EF-*) |
| G10 User-simulation acceptance | **PARTIAL** | 11 journeys PASS on the pushed head, 0 console errors (`.audit/acceptance/results.json`); live-LLM scenarios BLOCKED; remaining archetypes (quiz/notes/reader/TTS/PWA offline/notifications/export-delete/Create-hub jobs/PDF/school admin/resilience injections, WebKit/Firefox, Slow-3G) not executed |
| G11 Git hygiene | **PASS** | 16 atomic Conventional Commits with `Refs:` footers; clean tree; no tags; no secrets |
| G12 Report integrity | **PASS** | claim-evidence lint run before commit (script `.audit/lint_report.py`) |

## 1. Executive summary

The repository is a real, working product: 134 OpenAPI operations, a genuine retrieval stack
(BM25 + vector + fusion + rerank), five roles, Postgres/SQLite migrations, PWA, and CI that
mostly bites. The audit found 154 defects (10 S1, 66 S2, 78 S3; no S0). The two most serious
Domain A defects were *measurable untruths in its own evidence*: the retrieval harness reported
`recall@1` as top-5 membership (0.98 / 0.98 with MRR 0.61 — impossible), and the served index
carried 907 of 2,508 chunks flagged by the project's own content-QA gate, which ran nowhere.
Both are now fixed and pinned by tests (true recall@1 0.51; served corpus 0 of 2,504 flagged).
A child-safety copy defect (unverified helpline number), an impersonation path that could
irreversibly delete a user's account, a false hashing claim in the privacy policy, dead Grafana
panels, IME-unsafe Enter handling and WCAG failures on the registration page were fixed in the
same round (12 substantive commits, PR #30). The remaining deductions are dominated by work the
run could not responsibly start or finish: redesigning the golden evaluation (its positives were
lifted from the sections' own vocabulary), enforcing grounding after generation, timestamptz
migration, browser e2e automation, and the acceptance archetypes above. Fifteen deferred
findings are filed as issues #31–#45.

## 2. Method and environment

Windows 11 host, Git Bash. Python 3.12.10 (repo venv), Node v24.19.0, Docker 29.7.2, `gh`
authenticated as the owner. Tooling: ruff 0.17.0, mypy 2.4.0, pytest 9.1.1 (+cov 7.1.0,
asyncio), bandit 1.9.4, coverage 7.16.2, plus radon/vulture/deptry/jscpd/pytest-randomly
installed by the domain sweeps into the venv only. Playwright 1.49.1 + Chromium were installed in
a scratch directory (`C:\Users\DST\projects\bgpt-accept-tools`) for the acceptance run; the
repository itself gained no dependency. Missing scanners (gitleaks binary, trivy, semgrep, ZAP,
k6) limited G3/G5 as recorded. Eight domain sweeps (A1, A2, B, CD, EF, G, HI, JK) graded all 260
catalog parameters against code and runtime at `88ded22`; every status carries evidence
(348 distinct evidence references; `.audit/catalog-status.csv`). The live LLM was unavailable
(`GEMINI_API_KEY` empty in `apps/api/.env`; no key in the process, Windows user environment or
any `.env*` file — E-A2-806/807), so every generation-dependent check ran through the mock
provider and the live-mode rows are BLOCKED, not guessed.

## 3. Scorecard

| Domain | Pts | Baseline | Final | Notes (largest remaining deductions) |
|---|---|---|---|---|
| A RAG & LLM | 20 | 8.2 | 8.2 | eval construction (A8-01/02), grounding enforcement (A6-01/02/04/05), injection breadth (A7-01), live eval BLOCKED (A8-05), ablation/index lifecycle (A3-02/04, A4-01) |
| B Security & privacy | 12 | 8.6 | 8.6 | backup encryption + drill re-run (B-33), PVR/settings owner actions (B-09/30/32), Permissions-Policy (B-14) |
| C Architecture | 10 | 4.8 | 4.8 | C4 diagrams absent (C-01), god modules (C-03), error taxonomy (C-06), design review (C-05) |
| D Code quality | 10 | 6.0 (capped) | 6.0 (capped) | complexity gate (D-03), type strictness ratchet (D-02) |
| E Testing | 10 | 4.9 | 4.9 | no browser e2e (E-10), mutation gate (E-04), test strategy doc (E-20), critical-branch coverage (E-03) |
| F CI/CD | 8 | 4.8 | 4.8 | artifacts/badges (F-14), scheduled live eval (F-15), Scorecard (F-16) |
| G Frontend/UX/Bangla | 8 | 3.5 (after fixes) | 3.5 | glossary + native review (G-25/27), perf budgets (G-15), screenshots/keyboard/SR (G-07/11/12), Collator/Segmenter (G-23) |
| H Backend/API | 6 | 2.8 | 2.8 | naive datetimes (H-04/14), strict schemas (H-02), API.md generation (H-01), load benchmarks (H-06) |
| I Observability | 6 | 3.2 | 3.2 | tracing absent (I-03), business metrics + dashboards (I-02), soak/SLO (I-04/08) |
| J Docs/DX | 5 | 2.3 | 2.3 | threat model (J-05), AI system card (J-06), markdown link-check (J-10) |
| K Git/GitHub | 5 | 3.0 | 3.0 | release objects absent (K-08), issue hygiene (K-07), OpenSSF (K-11) |

**Caps applied** (lowest wins, each with evidence):
- Domain A ≤ 75% — live evaluation BLOCKED (no key, E-A2-806/807); no effect, A = 40.8% (E-R-114).
- Domains D and J ≤ 60% — a user-visible metric that is not calibrated remains (the confidence badge, issue #32; at baseline the legal-copy claim was also false, E-B-143); D was 64.9% uncapped → 6.0, J 46.9% (E-R-114).
- No overall cap applies: no live secret (E-B-159), no cross-tenant exposure, builds and runs from docs (E-R-123), tests cover auth/tenancy/tutor (E-R-112).

**Score confidence: moderate (~75%)** (E-R-114). All 260 statuses carry evidence; the majority of
verdicts rest on commands executed in this run (suites, scans, runtime probes), but the Phase-5
re-execution sample was reduced below the protocol's 40-item floor (performed: the full API and
web suites, the retrieval evaluation, the container smoke, and the acceptance journeys on the
pushed head), and some PARTIAL verdicts rest on source reading where the environment lacked a
tool (screen reader, DAST, k6, live model).

## 4. RAG architecture (Domain A)

As-built at `88ded22` (from code): acquisition → pypdf extraction → Bijoy conversion →
NFC/zero-width normalization → structure-aware chunking (`nctb/chunking.py`) →
`normalized/*.chunks.jsonl` + `quality_report.json` → `load_nctb_corpus` → BM25 + deterministic
vector lane + RRF fusion + lexical rerank → tutor coverage gate → mock/Gemini provider →
server-attached citations → SSE stream. As delivered by this run, two stages changed:
`normalize_bangla` now strips private-use glyph residue and the loader drops unreadable
legacy-Bijoy chunks (2 raw / 4 served), and the build script runs the content-QA gate and exits 1
on any failing source (report `<data-dir>/qa_report.json`).

| Measurement (real corpus) | Before | After (committed artifact, `E-R-006/007`) |
|---|---|---|
| Served chunks / QA-flagged | 2,508 / 907 (36.2%) | 2,504 / 0 (0.0%) (E-R-002) |
| Family A self-sentence recall@1 / @5 | 0.98 / 0.98 *(metric bug: top-5 membership)* | **0.51 / 0.99** (E-R-006) |
| Family A MRR | 0.6107 | 0.6945 (E-R-006) |
| Family B chapter-title | 1.00 / 1.00 | 1.00 / 1.00 (E-R-006) |
| Adversarial refusal rate | 1.00 | 1.00 (E-R-006) |
| Search latency p95 | 133 ms (own first run) | 133–1,010 ms across runs — **host-contended, not a stable figure** (E-R-001/006/007) |

Safety results: red-team replay 16/16 refusal (mock), injection screen tests green, no
system-prompt leakage in mock mode; the live-model leak claim remains BLOCKED. Cost: per-answer
token accounting exists (`services/costs.py`) but live cost per 1,000 answers is unmeasured
(A9-02 PARTIAL). Remaining Domain A gaps are issues #31–#37.

## 5. Findings

154 findings (10 S1 / 66 S2 / 78 S3; 0 S0). Fixed this run: the three S1s that were code-fixable
(A1-01/A1-02/A1-03) plus S1 helpline copy and the two S1 governance items' code halves; 12
substantive commits. Deferred with links: #31 (golden-eval construction, S1), #32 (grounding
enforcement, S1), #33 (injection breadth, S1), #34 (corpus metadata/duplicates), #35 (chunker),
#36 (index lifecycle), #37 (doc-vs-code divergences), #38 (browser e2e), #39 (naive timestamps),
#40 (strict schemas), #41 (architecture quality), #42 (perf budgets), #43 (glossary/review
sheet), #44 (historic DB backup in git history — owner decision), #45 (docker smoke flake).
Owner actions that are not code: verified helpline number before any re-addition; live LLM key;
GitHub security features (secret scanning, push protection, Dependabot alerts, private
vulnerability reporting — currently disabled); branch-protection review; NCTB corpus licence
decision; provider-terms acknowledgement for minors' data; SLO ratification; teacher/native
review of Bangla copy and golden items; release/tag/deploy decision (not authorized this run).

## 6. Changes delivered

16 commits on `chore/enterprise-hardening-20261018` (PR #30), grouped: RAG correctness
(`7d4eb2f`, `7a9f383`, `0542c6e`), security (`689c0e9`, `1121925`), web quality (`66e18cd`,
`de89145`, `145a0ab`, `22239b4`, `3c28b42`), safety copy (`a70f5be`), ops/docs (`d52c75d`,
`4735d5b`, `d6c4a35`), changelog bookkeeping (`3569e76`, `e214a0b`). Files removed: none.
Dependency changes: none added to the repository; no new runtime dependency; `constraints.txt`
untouched. No migrations, no schema change, no deploy, no tags.

## 7. User-simulation results (Phase 7, fresh clone of the pushed branch)

Environment: clone of `3c28b42`, README-only install (venv + constraints + `npm ci`), API with
the real corpus (2,504 chunks) and the mock provider, web via Vite dev proxy, Chromium headless
1280×850 + one 390×844 viewport; direct API calls only for environment setup.

| ID | Scenario | Result | Notes (screens in `.audit/acceptance/<id>/`) |
|---|---|---|---|
| XC-01 | first visit, language toggle, persistence across reload | PASS | `lang` bn→en→en after reload |
| AU-01 | student registration (consent required) | PASS | accepted, no bounce |
| AU-02 | student login | PASS | lands on `/student`; `bgpt_token` present |
| ST-01 | in-corpus tutor question, citation chip, source modal | PASS | answer + chip; modal opened (screenshot) |
| ST-02 | out-of-corpus question | PASS | refusal-shaped response |
| TE-01 | teacher registration | PASS | lands on `/teacher` |
| TE-02 | teacher classrooms page | PARTIAL | page and empty-state verified; creating a classroom was not exercised (no create affordance found in the flow tried) |
| PA-01 | student invite code → parent register → link | PASS | code `BGPT-F037A237…`; parent page lists child "রহিম উদ্দিন / 9" |
| AD-01 | admin login, user list, audit surface | PASS | created users visible; impersonation control not exercised in this flow |
| XC-02 | logout clears token | PASS | token present→absent |
| XC-03 | mobile viewport home | PASS | screenshot only |

Defects found by acceptance and fixed same-round: React "unique key" warnings on the teacher
home and Create pages (`3c28b42`, found via console capture; 0 console errors after the fix).
Not executed (BLOCKED in this run, listed in the gate table): live-model answers, quiz/notes/
reader/TTS/PWA-offline/notifications/export-delete journeys, Create-hub job lifecycle, generated
PDFs, school-admin and government-export paths, resilience injections, WebKit/Firefox, Slow-3G.

## 8. Anti-slop attestation

The taxonomy sweep (Section 9 IDs) ran across code, UI, docs, tests and config. Closed this
run: S-03 fabricated metrics (retrieval table, dashboard panels), S-19 security theatre (dead
regex sanitizer), S-11/S-12 user-visible copy defects (hashing claim, unverified helpline),
S-08 silent failure swallows, S-21's confidence-badge caveat retained as an open finding (#32).
Verified absent: TODO/FIXME placeholders, `print`/`console.log` in app code, committed
artifacts, fake testimonials. The cold-read sampling protocol (20+10+10 artifacts, two seeds)
was **not completed** — recorded as a limitation rather than asserted. Slop-free exit criteria
(a)–(g) are correspondingly PARTIAL.

## 9. Suppressions register

No new suppression was added in this run (no `noqa`, `type: ignore`, `eslint-disable`, scanner
allowlist or threshold change). The existing register (dated waivers for npm dev advisories,
`tests/test_phase1_exploits.py` B011) is unchanged and listed in the repository.

## 10. Limitations (every BLOCKED / UNVERIFIED item)

- Live-model evaluation, live injection/leak proof, live cost measurement: BLOCKED (no key).
- DAST baseline; container image CVE scan; SBOM/provenance generation: not executed (tools absent).
- Load/soak testing and stable latency figures: k6 absent; host-contended timings 93–1,010 ms p95 (E-R-001/006/007).
- Screen-reader pass; WebKit/Firefox runs; 7-width screenshot matrix; cold-read protocol: not executed.
- Deploy-path verification (SSH deploy, rollback drill), backup-restore drill on Postgres/pgBackRest:
  not re-executed; doc claims remain claims.
- Corpus extraction fidelity sample vs source pages; correction of remaining PUA/duplicate
  content in committed artifacts (they are untracked locally): not done.
- All numbers are from this Windows host at the stated SHAs; dates and counts are as measured.

## 11. Owner actions (ordered)

1. Provide a spend-limited LLM key (or accept Domain A's live-eval BLOCKED cap) and, if provided,
   run `apps/api/scripts/evaluate_golden.py` live within budget.
2. Verify a helpline number before any is shown to children again (the copy now names a trusted
   adult and local emergency services only).
3. Enable GitHub secret scanning + push protection + Dependabot alerts + private vulnerability
   reporting; review branch protection (7 checks + 1 review is current).
4. Decide on the historic `dev.db.bak-wave2` (issue #44) — rewrite is not authorized; rotation is
   the alternative.
5. NCTB corpus licence/permission documentation; provider-terms check for minors' data.
6. Ratify SLOs; schedule a backup-restore drill; commission the native-speaker/teacher review sheet.
7. Release decision: the PR is not merged (see verdict box); merge when G0–G9 are all green.

## 12. Roadmap

- **30 days:** merge PR #30; issues #31–#33 (eval redesign, grounding enforcement, injection
  breadth); enable the GitHub security features; add complexity + duplication gates (G1) and the
  DAST + image-scan jobs (G3).
- **60 days:** issues #34–#37 (corpus metadata, chunker, index lifecycle, doc reconciliation);
  timestamptz migration (#39); browser e2e smoke (#38); perf budgets in CI (#42).
- **90 days:** issues #40/#41/#43–#45; Playwright matrix + accessibility gate; SLOs and soak;
  school-admin and government-export journeys in the acceptance suite.

## Appendices

- **Evidence:** `.audit/evidence/` (348 referenced files; each carries timestamp + git SHA +
  command or file:line). Acceptance artifacts: `.audit/acceptance/<scenario>/{screens/,notes.md}`,
  `results.json`. Ledgers: `.audit/{STATE.md,env.md,commands.log,catalog-status.csv,fixes.csv,findings-*.csv}`.
- **Reproduction:** `python .audit/score.py .audit/master-prompt.md .audit/catalog-status.csv`;
  `bash .audit/acceptance/setup.sh` then `node acceptance.js` (scratch tooling path above).
- **Glossary:** NCTB — Bangladesh National Curriculum and Textbook Board; PUA — Unicode
  private-use area; RRF — reciprocal rank fusion; SSE — server-sent events; RAG — retrieval
  augmented generation.
