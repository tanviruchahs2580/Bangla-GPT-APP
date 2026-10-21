# Threat model — Bangla GPT APP

Status: **engineering threat model, v1 (2026-10-18)**. Owner: engineering.
Method: STRIDE per trust boundary (Shostack), the OWASP Top 10 for LLM
Applications **2025** list for the model-facing surface, and a LINDDUN-lite
pass for the personal data of minors. This document records what is
*implemented and tested*; it is not an aspiration list.

Ground rules (audit truth protocol §3 apply to this file):

- Every mitigation line cites a real control by `path:line` or a test name
  that exists in `apps/api/tests/`. A mitigation with neither is listed under
  "Residual risk" instead — nothing here is claimed without a control.
- Commands and numbers are reproducible; measurement records live under
  `.audit/evidence/` (`E-FIX-JK-*`, `E-JK-*`).
- Severities are the audit's own scale (S0–S3), not CVSS.

Scope of this version: the two shipped services (API + web SPA), the corpus
pipeline, the LLM boundary, CI/CD, and the admin surfaces. Out of scope:
the hosting provider and its hypervisor, the reviewer's browser extensions,
and any deployment that has not enabled the production posture enforced by
`apps/api/src/bangla_gpt_api/main.py:72` (`enforce_production_safety`).

## 1. Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| Children's personal data (name, class, guardian phone, chat, quiz answers, consent evidence) | API database (`db/models.py`); guardian phone encrypted (`security.py:28`) | Data about minors; the highest-harm asset in the system |
| Credentials: password hashes, JWTs, reset/verification/invite tokens | `users.password_hash` (Argon2id), token tables storing SHA-256 hashes only | Account takeover, impersonation |
| Curriculum corpus + provenance ledgers | `data/nctb/**` (raw text gitignored), committed manifests | Grounding integrity of every tutor answer |
| Model context: system prompt, retrieved evidence, user question and history | In-process only; egress boundary in `services/tutor.py` | Leakage of the system prompt or one student's text to another |
| Release/CI identity and artifacts | GitHub Actions, GHCR images, `release.yml` | Supply-chain compromise; the update channel for the app |
| Money/abuse budget: LLM quota, rate windows | `ratelimit.py`, provider settings | Unbounded consumption that bills the owner |

## 2. Trust boundaries

```text
TB1  student/guardian browser  ──untrusted input──►  SPA (static, Caddy)
TB2  browser ──HTTP/SSE, JWT──► API edge (Caddy TLS ─► uvicorn)
TB3  API process ──SQL──► SQLite/PostgreSQL dataset
TB4  API process ──file read (NCTB_CORPUS_DIR)──► corpus on disk
TB5  API process ──HTTPS egress──► LLM provider (external)
TB6  API process ──SMTP──► mail relay (external)
TB7  CI/CD (GitHub Actions) ──push/tag──► image registry + deploy host
TB8  maintainer workstation ──dependencies, hooks──► repository & build
TB9  privileged in-app surfaces (admin/impersonation/purge/audit)   [inside TB2]
TB10 ops scraper ──HTTPS (bearer token)──► /metrics, /status
```

The corpus *acquisition* boundary (downloading PDFs from `nctb.gov.bd`) is a
one-time maintainer-side action documented in `docs/NCTB_DATA_PIPELINE.md`; it
is not a runtime surface and is covered here only as an integrity concern
(Spoofing/Tampering row of TB4).

## 3. STRIDE per boundary

Each row: threat → control (verified citation) → residual. "Test" means the
test file/function exists in the tree at this commit; the regression gate for
all of them is `pytest -q` in `.github/workflows/ci.yml:83`.

### TB1 — untrusted browser to SPA

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Fake UI copied from the project | Product is open source; a phishing clone is out of code control. No control claimed. | Accepted (operational) |
| Tampering | DOM XSS through tutor markdown | `apps/web/src/lib/safeMarkdown.tsx:13` renders through `react-markdown` **without** `rehype-raw`, so model HTML arrives as text; link/image schemes restricted to `http/https/mailto` and same-origin (`isSafeHref`, same file). The earlier regex stripper was removed in `1121925` (CodeQL `js/incomplete-multi-character-sanitization`); the structural design is the control. | None open in-tree; the code-scanning alerts on the default branch close when this branch merges (evidence `E-FIX-JK-002`) |
| Repudiation | n/a (no authoring) | — | — |
| Information disclosure | Offline corpus copies and cached assets left on a shared device | Browser-side only; PWA cache. No server control. | Accepted, documented in `docs/data_minimization.md` |
| DoS | n/a | Client-side rendering only | — |
| Elevation | n/a | — | — |

### TB2 — browser to API edge

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Credential stuffing / brute force on `/auth/login` | Progressive per-account lockout, `routers/auth.py` `_lockout_seconds()` — tests `tests/test_login_lockout.py::test_lock_is_progressive`, `::test_correct_password_is_refused_while_locked`; per-IP limiter `ratelimit.py` (`build_limiter`) — `tests/test_ratelimit_backends.py` | Lockout is in-DB (works across workers); IP limiter is per-process unless Redis is configured |
| Spoofing | Forged/expired JWT, wrong audience | Issuer/audience binding and session epochs per ADR-0010; `tests/test_jwt_claims.py`; revocation via `jti` deny-list (`tests/test_security_v2.py::test_impersonated_token_is_short_lived_and_attributable`) | Single HS256 shared secret (`docs/owasp_checklist.md` A02 PARTIAL) — RS256 rotation is an owner/infra item |
| Tampering | Cross-site request forgery | Bearer-token auth in `Authorization` header (no cookie sessions); CORS allowlist `CORS_ORIGINS` — `tests/test_cors.py::test_unknown_origin_gets_no_allow_header` | None open |
| Tampering | Request smuggling / oversized bodies | Uvicorn + explicit upload validation; `tests/test_phase1_exploits.py::test_fsec04_chunked_body_413` | Depends on the edge proxy config (`deploy/caddy/Caddyfile`) |
| Repudiation | A privileged action with no actor record | `audit_log` table (migration `f9a0b1c2d3e4_audit_log_phone_enc.py`), five event types — `tests/test_security_v2.py::test_all_five_event_types_write_audit_rows` | Only five privileged actions are audited; ordinary reads are not (by design) |
| Information disclosure | Tenant leak (school A reads school B's content) | `authorize_student_access()` `routers/deps.py:349`; `tests/test_cross_school_content.py::test_other_school_cannot_overwrite_authored_content` | School-less staff resolve to the default school (documented in `docs/qa/QA_REPORT_2026-10-17.md` §6) |
| Information disclosure | Secrets in responses / debug surfaces | `docs_url=None` etc. in production (`main.py`), `tests/test_docs_exposure.py::test_production_refuses_to_serve_the_api_reference`; structured logs with redaction `logging_config.py:78` (`redact_value`) | None open |
| DoS | Auth endpoint flooding | Limiter + 413 handling; `tests/test_audit_remediations.py::test_metrics_rejects_garbage_bearer`, `::test_mfa_challenge_rate_limited` | k6 soak was BLOCKED in this environment (`.audit/reports/FINAL.md` §10) |
| Elevation | Authorization gaps on any route | Route-level auth matrix over the OpenAPI spec — `tests/test_openapi_auth_matrix.py::test_no_operation_is_public_without_being_declared`, `::test_protected_operations_still_declare_security` | Matrix is generated from declared security, so a route added without declaration fails the test; that is the point |

### TB3 — API to dataset

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | n/a (local socket/DSN) | Production refuses SQLite (`main.py:72` posture) | — |
| Tampering | SQL injection | SQLAlchemy ORM/Core only; no string-built SQL in `apps/api/src` (`docs/owasp_checklist.md` A03) | — |
| Information disclosure | Charts/backups leaving the host with plaintext PII | Guardian phone Fernet-encrypted at rest (`security.py:17,28`); `tests/test_security_v2.py::test_guardian_phone_encrypted_at_rest_and_roundtrips`; `PII_ENC_KEY` deliberately excluded from backups (`docs/backup_dr.md`) | `consent_ip` and answer records are not encrypted (kept as consent evidence) — `docs/data_minimization.md` |
| Information disclosure | A historic DB backup in public git history | **No code control.** `apps/api/dev.db.bak-wave2` remains fetchable from history (finding AUD-JK-04, owner action recorded in `.audit/findings-jk.csv`) | Owner decision: accept with notice or scrub (history rewrite not authorised) |
| Repudiation | Deletion/export without trace | Export and delete flows audited (`audit_log`), `tests/test_data_export.py`, `tests/test_account_deletion.py`, `tests/test_delete_cascade_v2.py::test_student_delete_removes_every_child_row` | — |
| DoS | DB file growth | Retention sweep `services/retention.py:39` (chat history default 180 days) run by the nightly job and `POST /admin/maintenance/purge` | No dormancy purge yet (`docs/data_minimization.md` "Honest gaps") |
| Elevation | Direct DB access by a co-tenant on the host | Deployment topology ADR-0007 (two services); DB not exposed publicly | Host compromise is out of scope |

### TB4 — API to corpus files

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Poisoned PDF fetched from a look-alike host during acquisition | Acquisition only visits officially linked URLs from `nctb/sources.py`, records sha256 per artifact, and prefers content-type `application/pdf` (`docs/NCTB_DATA_PIPELINE.md` §2) | The acquisition host is trusted by domain name; a TLS-compromised gov site is out of scope |
| Tampering | Corpus modified after acquisition | Committed `manifests/acquisition_manifest.jsonl` records hashes; raw content is gitignored and supplied by the operator at deploy time (`docs/NCTB_DATA_PIPELINE.md` §6) | Nothing re-verifies the hash of `data/nctb/raw` at boot — operator-supplied directory is trusted |
| Tampering | Malformed text poisoning the index (mojibake, PUA residue, legacy Bijoy) | Build-time per-chunk QA gate (`nctb/content_qa.py`; report `<data-dir>/qa_report.json`; non-zero exit on failure — `tests/test_corpus_qa_gate.py`) and load-time strip/drop (`data/nctb_loader.py:105`) | Flagged-chunk threshold is 2 % (`DEFAULT_FLAGGED_THRESHOLD`), documented |
| Information disclosure | Copyrighted textbook text redistributed from the public repo | Raw/extracted/normalized directories are gitignored; only metadata and reports are committed (`docs/NCTB_DATA_PIPELINE.md` §1, `.gitignore`) | Redistribution rights remain an **owner/legal** item (`docs/LAUNCH_READINESS_CHECKLIST.md` §3) |
| DoS | Corpus absent ⇒ every answer refuses | Boot identity log + `bgpt_rag_index_chunks{corpus}` metric; `/ready` and `/status` degrade truthfully when the index is missing (`docs/RAG_ARCHITECTURE.md` "Runtime execution notes") | Bundled 78-chunk sample is the loud fallback — classes 6–10 only |
| Elevation | n/a | — | — |

### TB5 — API to LLM provider

See §4 (LLM-specific threats) for the model-facing analysis; STRIDE summary:

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Rogue provider endpoint | Only fixed base URLs from config (`providers/gemini.py:55` `_API_BASE`); no user-controlled URL reaches the HTTP client | Provider trust itself is an owner/licensing question |
| Tampering | Provider response manipulated in transit | HTTPS only | — |
| Repudiation | Unbounded provider spend with no record | Per-user rate limits + cost accounting (`tests/test_ai_costs.py`); `docs/capacity_plan.md` | Live key absent in this environment ⇒ live evaluation BLOCKED (`.audit/reports/FINAL.md` §10) |
| Information disclosure | Student text sent to the provider, or one student's text echoed into another's answer | PII redaction at the egress boundary `services/pii.py:29` (`redact_pii`, returns redaction counts); no Gemini request/response logging (`docs/data_minimization.md`) | Provider terms for minors' data are an owner/legal item |
| DoS | Provider latency/outage stalls tutoring | Circuit breaker + fallback chain (`tests/test_circuit_breaker.py`) | — |
| Elevation | Model output driving privileged actions | The model has no tool/action surface: output is only rendered as text — see LLM06 row in §4 | — |

### TB6 — API to mail relay

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Verify/reset mail sent to an attacker-chosen address | Addresses come from account records only; tokens single-use and hashed (`docs/data_minimization.md`) | — |
| Information disclosure | Token in an email body logged by the relay | Tokens single-use, expiry-bounded; `apps/api/tests/test_single_use_tokens.py` (CI job, `ci.yml:226`) | SMTP provider trust; production refuses to boot with SMTP disabled only where enforced (`tests/test_phase1_exploits.py::test_fsec03_production_requires_smtp`) |

### TB7 — CI/CD and release

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Unreviewed code merged to `main` | Branch protection requires 7 checks + 1 review (E-JK-041); `.github/CODEOWNERS` routes review; merge is a maintainer action | Repository settings are owner-administered (this token is read-only) |
| Tampering | Dependency or action swapped under a tag | Actions pinned by commit SHA in workflows (e.g. `gitleaks-action@ff98106e…`, `setup-python@a26af69…`); `pre-commit` revs pinned (`.pre-commit-config.yaml`) | Dependabot alerts are disabled platform-side (AUD-JK-02, owner action) |
| Tampering | A release image built from unverified code | `release.yml` gates the build on a successful `API CI` (ci.yml) run for the tagged commit — `.github/workflows/release.yml:83`, error path at `:135`; tag push is an owner action | The queued `v0.9.0` release run is stale (AUD-JK-06, owner) |
| Information disclosure | Secrets committed to a public repo | `detect-private-key` + file-hygiene hooks (`.pre-commit-config.yaml`), gitleaks full-history scan in CI (`ci.yml:417`), `.gitleaks.toml` | Secret scanning + push protection are disabled platform-side (owner action) |
| DoS | Red CI blocks the pipeline forever | Timeouts + `cancel-in-progress` concurrency (`.github/workflows/ci.yml:11-12`) | — |
| Elevation | Compromised workflow token | `permissions: contents: read` default (`ci.yml:15`) | GHCR write scopes are per-job and were not audited here |

### TB8 — maintainer workstation / supply chain

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Tampering | A hallucinated or typosquatted dependency | Lockfile with per-artifact hashes (`apps/api/constraints.txt`) installed with `--require-hashes`; `apps/api/scripts/check_lockfile.py` vs `pyproject.toml` — `tests/test_lockfile_gate.py`; `npm ci` (not `npm install`) in CI | No SBOM artifact (BLOCKED in this environment, `.audit/reports/FINAL.md` §10) |
| Information disclosure | Vulnerable dependency exploited | `pip-audit` (fail on vulnerability, `ci.yml:114`) and `npm audit --audit-level=high --omit=dev` (`ci.yml:313`); triage register `docs/security_scans.md` | Register entries with waivers carry expiry (`docs/dependency_waivers.md`) |

### TB9 — privileged in-app surfaces (inside TB2)

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Impersonation token used as a standing credential | Purpose-bound JWT with 15-minute ceiling; `POST /auth/impersonate/exit` parks the `jti` in the shared deny-list; start/exit audited (`tests/test_security_v2.py::test_impersonated_token_is_short_lived_and_attributable`) | Admin account compromise is the precondition; MFA exists (`tests/test_mfa.py`) |
| Elevation | Role change without review | Admin-only + audited (`audit_log` role_change); `tests/test_admin_center.py` | — |
| Information disclosure | Audit/purge views expose content | Purge detail is counts-only (`tests/test_security_v2.py::test_purge_audit_detail_is_counts_only`); chat content never logged (`docs/data_minimization.md`) | — |
| Tampering | Destructive maintenance without a dry run | `POST /admin/maintenance/purge` supports `dry_run=true` (`docs/data_minimization.md` "What the sweep enforces") | — |

### TB10 — ops scraping

| STRIDE | Threat | Control (real, cited) | Residual |
|---|---|---|---|
| Spoofing | Anyone reads `/metrics` | Production refuses an open metrics endpoint and gates it by bearer token — `tests/test_metrics_auth.py::test_prod_boot_refuses_open_metrics`, `::test_prod_metrics_gated_by_token` | Scrape token is a static secret (rotation is an ops item) |
| Information disclosure | Metrics leak tenant data | Metric label set is bounded to gate/corpus names (`docs/RAG_ARCHITECTURE.md` "Runtime execution notes"); labeled alerts in `deploy/prometheus/alerts.yml` | — |

## 4. LLM-specific threats (OWASP Top 10 for LLM Applications 2025)

Mapping verified against the OWASP GenAI Security Project list on 2026-10-18
(evidence `E-FIX-JK-005`). For each entry: the control that exists today, and
the honest gap.

| OWASP ID | Threat | Control in this codebase | Gap / status |
|---|---|---|---|
| LLM01:2025 Prompt Injection | User text overrides instructions or smuggles delimiter escapes into the evidence block | System/user separation with an injected-instruction rule; evidence wrapped and sanitised — `tests/test_injection_guard.py::test_sanitize_neutralizes_delimiter_escape`, `::test_poisoned_chunk_cannot_break_out_of_evidence_block`, `::test_system_prompt_contains_injection_rule`; input screen `tests/test_injection_screen.py::test_injection_attempts_are_screened` | Breadth deferred: AUD-A2-04 / issue (`.audit/reports/FINAL.md` §5); no full adversarial corpus yet |
| LLM02:2025 Sensitive Information Disclosure | A student's PII or the system prompt reaches the model or another user | Redaction at the egress boundary `services/pii.py:29`; no raw provider transcripts retained (`docs/data_minimization.md`); tenant checks on every read (`routers/deps.py:349`) | Provider-side retention is governed by provider terms (owner) |
| LLM03:2025 Supply Chain | Model/provider, packages, or corpora swapped or poisoned | Fixed provider base URL (`providers/gemini.py:55`); hash-pinned lockfile + `check_lockfile.py`; corpus hash manifest + QA gate (`docs/NCTB_DATA_PIPELINE.md` §2, §4) | Platform Dependabot alerts disabled (owner); provider model pinning is deliberate (model name from config, evaluated per release) |
| LLM04:2025 Data and Model Poisoning | Corpus content steers the tutor (deliberate or from extraction damage) | Provenance ledger with sha256 per artifact; per-chunk QA gate at build and load — `tests/test_corpus_qa_gate.py`, `data/nctb_loader.py:105`; vector-lane candidates must share Bangla bigrams with the query (`retrieval/hybrid_index.py:250`) so hash collisions cannot manufacture evidence | Raw corpus hash is not re-verified at boot (operator-supplied); documented |
| LLM05:2025 Improper Output Handling | Model output treated as trusted HTML/URLs | `react-markdown` without `rehype-raw`; scheme allowlist in `apps/web/src/lib/safeMarkdown.tsx`; no `dangerouslySetInnerHTML` of model output (`docs/owasp_checklist.md` A03) | Closed in-tree; alert closure follows the change to `main` (evidence `E-FIX-JK-002`) |
| LLM06:2025 Excessive Agency | Model triggers actions (writes, deletes, payments) | There is no tool/action surface: the provider call returns text only (`providers/` has generate/stream, no tool calls); every write path is a user- or admin-authenticated route with its own authorization | Structurally absent today; add this row to the design review of any future tool-calling feature |
| LLM07:2025 System Prompt Leakage | Extracting the system prompt / internal rules | Red-team set `apps/api/eval/redteam_v2.json` (16 items, BN+EN) asserts refusal **and** no system-prompt leakage; run as a regression gate by the eval CLI with a >2pp drop threshold (`apps/api/eval/baseline_v2.json`) | Refusal is the strategy; the prompt contains no secrets by design |
| LLM08:2025 Vector and Embedding Weaknesses | Embedding/vector lane manipulated; evidence from wrong documents | Deterministic model-free embedder + shared-bigram gate (`retrieval/hybrid_index.py:250`); grounding gate over IDF-weighted content terms (`services/tutor.py:272`) with an out-of-domain refusal budget | Real embedding model + vector store still a staged infra decision (`docs/RAG_ARCHITECTURE.md` "Known open items" 1) |
| LLM09:2025 Misinformation | Confident wrong answer to a child | Grounding gate refuses below threshold (`services/tutor.py:272`, refusal at `:728`); post-generation citation verification `verify_citation` (`services/tutor.py:652`) and `citation_verified` on every grounded response; measured red-team refusal 16/16 and grounded rate 1.00 on the committed artifacts (`apps/api/eval/baseline_v2.json`, `docs/RAG_ARCHITECTURE.md` "Measured baseline") | Faithfulness judge is `local_overlap` until a provider is configured (owner/staged) |
| LLM10:2025 Unbounded Consumption | Quota/cost drain via the tutor or streaming endpoints | Per-user rate limits (`ratelimit.py`); cost accounting `tests/test_ai_costs.py`; image upload validation `tests/test_chat_image_validation.py`; streaming discards partial output on failure (`docs/RAG_ARCHITECTURE.md`) | No token-budget cap per conversation beyond rate windows; k6 soak not run (BLOCKED) |

## 5. LINDDUN-lite — minors' personal data

Seven LINDDUN categories applied to the student dataset only (the highest-harm
asset). Each row lists the privacy threat, the mitigation that exists, and what
is *not* covered.

| Category | Privacy threat for a child user | Mitigation present | Not covered |
|---|---|---|---|
| **L**inkability | Joining chat content, quiz answers and consent metadata to build a richer profile than either piece alone | Data minimization review is field-by-field (`docs/data_minimization.md`); analytics events store name + prop **keys** only, never values (`routers/tutor.py:768` `record_event`); `consent_ip` is never joined to logs or analytics by policy | Within the DB, rows are joinable by design (that is the product); no k-anonymity on internal reads |
| **I**dentifiability | Direct identifiers (name, guardian phone) exposed at rest or in exports | Guardian phone Fernet-encrypted (`security.py:17,28`); exports are per-user and authenticated (`tests/test_data_export.py::test_export_requires_auth`) | Names are plaintext; that is required to address a student |
| **N**on-repudiation | A child's question cannot be denied/erased because it is duplicated in logs, backups or provider systems | Chat content is never logged; no provider transcript retained; purge sweep + audited deletion (`services/retention.py:39`, `tests/test_account_deletion.py`); `PII_ENC_KEY` excluded from backups | Provider-side retention governed by provider terms; historic `dev.db.bak-wave2` in git history (AUD-JK-04) |
| **D**etectability | Inferring that a specific child uses the platform | Public signup (no directory); no third-party analytics loaded by the SPA (`docs/data_minimization.md` "Honest gaps") | Server access logs and metrics label corpus/gate names only, but request logs still show accounts (structured, whitelisted keys) |
| **D**isclosure of information | Leak of one student's data to another student, guardian without a link, or another school | `authorize_student_access()` (`routers/deps.py:349`); guardian linking via invite codes; cross-school tests (`tests/test_cross_school_content.py`); impersonation refusals (`tests/test_security_v2.py`, later fix `689c0e9`) | A guardian with a redeemed invite sees their linked child by design |
| **U**nawareness | Child/guardian does not know what is stored or how to remove it | Consent checkbox with version + timestamp + IP (`routers/auth.py:145`), re-confirm flow (`routers/users.py:772`), self-service export and `DELETE /users/me`, retention default published `chat_retention_days=180` | Bangladesh legal review of the consent copy is a **human step not done** (`docs/LAUNCH_READINESS_CHECKLIST.md` §1) |
| **N**on-compliance | Processing minors' data without a lawful basis or with wrong retention | Consent evidence persisted; retention sweep enforced by `services/retention.py`; DPA template + data-minimization review in tree (`docs/dpa_template.md`) | Jurisdiction-specific legal interpretation is owner/legal (I10) |

## 6. Residual risk register (not claimable as mitigated)

| # | Risk | Severity | Owner action / issue |
|---|---|---|---|
| R1 | Historic `apps/api/dev.db.bak-wave2` (1.3 MB) remains in public git history: 129 PBKDF2 hashes, 376 chat messages, synthetic test domains only | S2 | Owner decision: notice or scrub (rewrite not authorised). `.audit/findings-jk.csv` AUD-JK-04 |
| R2 | Platform security features off: secret scanning, push protection, Dependabot alerts; PVR disabled ⇒ no preferred disclosure channel | S1 | Owner (admin scope). AUD-JK-01/JK-02; exact `gh api` payload in `.audit/handoffs/ef-from-jk.md` |
| R3 | 6 CodeQL alerts open on `main`; the code fix is on this branch (`1121925`) and closes them after merge + analysis | S1 | Merge PR / re-run analysis. Evidence `E-FIX-JK-002` |
| R4 | Zero GitHub Releases for 13 tags; stale queued release run for `v0.9.0` | S2 | Owner (tags/releases). AUD-JK-06 |
| R5 | Live LLM key absent ⇒ every live evaluation is BLOCKED; faithfulness judge stays `local_overlap` | S2 | Owner. `.audit/reports/FINAL.md` §11.1 |
| R6 | NCTB redistribution permission undocumented | S1 (launch blocker) | Owner/legal. `docs/LAUNCH_READINESS_CHECKLIST.md` §3 |
| R7 | No automatic dormancy purge; `consent_at`/`consent_ip` horizon is policy-on-paper | S3 | Product decision (`docs/data_minimization.md`) |
| R8 | `/assignments/mine` platform-wide window and check-then-insert races (reproduced, unfixed) | S2 | Scheduled next (`docs/qa/QA_REPORT_2026-10-17.md` §6) |
| R9 | Historic dev DB blob plus no gitleaks rule for `*.db` blobs (rule addition proposed in the same finding) | S3 | With R1 |

## 7. Review process

- Re-review this file when: a trust boundary moves (new service, new provider,
  new tool-calling capability), a new personal-data field is stored, or a
  release changes the deployment topology. ADR-0007 changes are automatically
  in scope.
- Every new mitigation row must land with its test in the same pull request
  (CONTRIBUTING definition of done).
- The measured numbers cited here are regenerated from the committed
  artifacts; if an artifact changes, the citation changes with it.
