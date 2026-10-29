# AI risk register

Register of AI-specific risks for the Bangla GPT tutor and generators, at
BASE_SHA `7e8525e2` (2026-10-29). The NIST AI RMF functions
(Govern / Map / Measure / Manage) are used as an organising lens only; this is
not a compliance claim and implies no certification. Owners are roles and are
proposals until the project owner confirms who fills each role. Each row names
one trigger and at least one severity, and residual status is stated as
what the current evidence shows, not as an expectation.

Reading guide:

- "Mitigation" cites the code or document that exists now.
- "Tested by" cites the check IDs and evidence from `.qa-work/audit/` and
  `.qa-work/findings.csv`; `OPEN` findings are unfixed at the audit SHA.
- Residual `OPEN` means the risk is unmitigated or partially mitigated with a
  recorded finding; `MEASURED` means the control exists and was exercised;
  `UNMEASURED` means the control exists but was never measured.
- Review this register together with `docs/ai/system-card.md` (limitations and
  measurements) and `docs/ai/incident-response.md` (what to do when one fires).

| # | Risk | RMF function | Owner (role) | Mitigation | Tested by | Residual status |
|---|---|---|---|---|---|---|
| 1 | Misinformation: an answer is wrong, uncited or served for a question the corpus does not cover | Measure / Manage | Engineering lead (AI/retrieval) | Evidence-only prompt (`services/tutor.py:104-122`), coverage gate (`services/tutor.py:272-388`), server-side source list, `verify_citation` heuristic (`services/safety.py:120-135`), golden eval gate | RAG-14, RAG-15, RAG-20, LLM-03, LLM-04; F-RAG-2 (S1), F-RAG-7, F-RAG-16, F-RAG-6 | OPEN — gate serves 3/4 out-of-corpus probe questions (Wilson 95% CI [0.30, 0.95], n=4); fabricated text passes the citation heuristic; eval set partly generated from indexed text |
| 2 | Harmful content reaches a minor (hate, bullying, sexual, violence, dangerous instructions) | Govern / Manage | Child-safety owner | Keyword refusal screen with six categories and academic-context exception (`services/safety.py:25-106`), age-appropriateness rule in every prompt (`services/safety.py:214-220`), supportive refusal copy (`services/safety.py:109-117`), 23-item hermetic red-team suite | LLM-06, SEC-20 (PASS-RUN, 23/23 refused); F-LLM-1, F-LLM-2, F-LLM-3 | OPEN — no hate/bullying category, Romanized variants only for self-harm, tutor answers are not output-screened, image text is not labelled untrusted; live-model behaviour UNVERIFIED-LIVE |
| 3 | Over-reliance: students or parents treat generated answers as authoritative | Govern | Product owner | AI chip on assistant answers and "do not rely on it as the sole source of truth" statement (`apps/web/src/pages/LegalPage.tsx:71-76`), not-in-textbook rule (`services/tutor.py:104-122`), thumbs feedback with admin triage queue (`routers/tutor.py:944-1016`, `db/models.py:320-345`) | LLM-13, LEGAL-03; no finding recorded | MEASURED exposure, UNMEASURED effect — no metric follows reliance or drift over time |
| 4 | Privacy: child data collected, exposed or kept longer than stated | Govern / Manage | Data-protection owner | Guardian consent with version/at/ip (`routers/auth.py:154-172,205-212`), PII redaction before the provider call (`services/pii.py:29`), retention windows and sweep (`config.py:166-181`), k-anonymity floor for sharing, self-service export/erasure (`routers/users.py:82-151,152-157`) | PRIV-01..PRIV-10, PRIV-09, PRIV-10; F-PRIV-1, F-PRIV-2, F-PRIV-4, F-PRIV-7, F-PRIV-8 | OPEN — analytics props store free text/PII (F-PRIV-2), export omits several tables (F-PRIV-4), Sentry has no scrubbing or consent gate (F-PRIV-7); legal review required |
| 5 | Bias: quality, tone or refusal behaviour differs across regions, gender, religion or disability, or example content stereotypes | Measure | Engineering lead (AI/retrieval) | Paired synthetic prompt harness now exists (`apps/api/src/bangla_gpt_api/evaluation/fairness_probes.py`, F-030): 10 pairs across gender, religion, community, region, disability, socioeconomic and Bangla-name cues; `--selftest` validates the fixture offline, `--report` tabulates refusal/tone/length per pair and refuses the mock provider (mock output proves nothing) | AIG-04, F-030; harness selftest only — no live run exists | UNMEASURED — the harness is not the result: running `--report` against a LIVE provider is an OWNER ACTION and the fairness results are currently unmeasured |
| 6 | Manipulation: prompt injection or corpus poisoning turns untrusted text into instructions | Manage / Measure | Security owner | Query-side injection patterns (`services/safety.py:83-106,139-207`), ingest-time sentence stripping, delimiter sanitizing (`services/tutor.py:132-141`), data-only prompt rules (`services/tutor.py:104-122`), red-team gate | SEC-20 (PASS-RUN, 23/23, no leak markers), LLM-06, RAG-17; F-LLM-3 | MEASURED for text under mock; OPEN for image text (F-LLM-3) and for real models (UNVERIFIED-LIVE) |
| 7 | Data leakage: system prompt, secret or child data escapes through an answer, log or provider | Manage | Security owner | Refusal copy reveals no trigger (`services/safety.py:109-117`), no secrets in prompts (audit LLM-02), provider logs carry char counts not text, optional Sentry without payload scrubbing | LLM-02, PRIV-06, PRIV-08, SEC-13, SEC-20; F-PRIV-7, F-PRIV-6 | OPEN — Sentry has no scrubbing hook and no consent gate (F-PRIV-7); the provider free-tier data-use terms are unrecorded (F-PRIV-6, owner decision, legal review required) |
| 8 | Model or provider change: a swap, deprecation or outage changes behaviour without re-validation | Govern / Manage | Engineering lead (AI/retrieval) | Provider factory with production guards (`providers/__init__.py:20-35`; `main.py:324-345`), mock parity tests, optional fallback provider and circuit breaker (`providers/__init__.py:77-125`), eval gate in CI | LLM-01, LLM-12, LLM-04; eval gate (`.github/workflows/eval-gate.yml`) | MEASURED for config and mocks; UNVERIFIED-LIVE for real providers; no prompt or model version pinning recorded (F-RAG-11) |
| 9 | Scope and rights: the corpus is used or described beyond what has been cleared | Map / Govern | Product owner | Acquisition manifest records provenance and a restrictive `license_notes` (`data/nctb/manifests/acquisition_manifest.jsonl`); "textbook-grounded" claim flagged as broader than the curriculum-only corpus | LEGAL-02, LEGAL-05, DATA-01; F-LEGAL-1, F-LEGAL-3, F-RAG-14 | OPEN — rights confirmation is an unchecked launch gate; legal review required |

## Owner actions this register depends on

1. Confirm who holds each owner role above (roles are placeholders).
2. Resolve F-PRIV-6 (provider data-use terms) before minors' questions are sent
   to a real provider; record the resolution here.
3. Track every `OPEN` residual to its finding id in `.qa-work/findings.csv`
   while the QA run is open; after it closes, re-point them to the issue tracker
   the project adopts.
4. Run the fairness harness against a live provider (row 5):
   `cd apps/api && python -m bangla_gpt_api.evaluation.fairness_probes --report`
   with `LLM_PROVIDER=gemini` + `GEMINI_API_KEY` set, then record the results
   here and triage every pair flagged for review. Until that run exists, bias
   remains unmeasured and this row stays UNMEASURED.

## Rows added by the wave-2 generation/observability stream (2026-10-29)

| # | Risk | RMF function | Owner (role) | Mitigation | Tested by | Residual status |
|---|---|---|---|---|---|---|
| 10 | Undiagnosable answers: a wrong or uncited answer cannot be attributed to a prompt revision, corpus revision, model or parameters after the fact | Measure / Manage | Engineering lead (AI/retrieval) | Versioned prompt template with SHA-256 recorded on every answer (`services/tutor.py` `PROMPT_VERSION`/`PROMPT_SHA256`), per-answer trace store with query fingerprint, chunk ids/scores, prompt hashes, model, parameters, citation verdict and per-stage latency (`evaluation/observability.py`; capacity 500, in-process, no student text) | RAG-13, RAG-29, F-130; `tests/test_w2_eval_trace.py`, `tests/test_w2_llm_prompt_extraction.py` | MEASURED for the answer path under mock; the aggregate is not yet served by `/admin/ai/quality` (handoff: the admin router belongs to another stream) |
| 11 | Capacity collapse: parallel provider calls exhaust the quota or the worker, and a failing retrieval lane surfaces as a 500 | Manage | Engineering lead (AI/retrieval) | Per-process generation semaphore with a bounded queue and its own refusal envelope (`MAX_CONCURRENT_GENERATIONS`, `refused_reason="ai_busy"`), guarded retrieval that degrades to the lexical lane and refuses -- never generates -- when no lane serves, metered on `bgpt_generation_overload_total` and `bgpt_rag_retrieval_degraded_total` | RAG-28, LLM-11, F-117, F-131; `tests/test_w2_llm_concurrency.py`, `tests/test_w2_llm_retrieval_fallback.py` | MEASURED under mock; the cap value (8) and the latency targets in `docs/rag/architecture.md` section 6.3 are proposals pending load testing on real hardware |
| 12 | Language and arithmetic integrity: a Bangla answer carries Assamese letters or switches script, or a numeric answer key contradicts its own arithmetic | Measure | Engineering lead (AI/quality) | Deterministic answer-side language legs in the eval suite (Bengali script share, U+09F0/U+09F1 count; `evaluation/metrics.py`), golden v3 construct set with Bangla/Banglish/mixed/typo strata and a leakage gate (`docs/rag/golden-set-v3.md`), semantic output-validation module (unique options, counts against the request, recomputed numeric keys; `evaluation/output_validation.py`) | RAG-21, LLM-07, RAG-19, F-118, F-120; `tests/test_w2_eval_language.py`, `tests/test_w2_llm_output_validation.py` | MEASURED: 0 Assamese letters and 1.00 language consistency on the mock; the validator is not yet wired into `services/generators/**` (handoff); reference-correctness and register legs stay UNVERIFIED-LIVE |

## Licence and data inventory for the wave-2 additions

The generation/observability stream added no model, no dataset, no font and no
dependency: everything it introduces is standard-library Python plus the
Prometheus client already constrained in `apps/api/constraints.txt`. The
inventory of what the answer path already uses, for the record:

| Asset | Where | Licence / basis | Status |
|---|---|---|---|
| Hashing char n-gram embedder | `retrieval/embedding.py` (repo code) | repository code, no third-party model | shipped |
| Noto Sans Bengali | `data/fonts/`, `OFL.txt` | SIL Open Font License 1.1 | shipped with licence text |
| Bundled sample corpus text | `data/sample_nctb/*.md` | declared original synthetic text (`docs/architecture.md:72`) | shipped; sample-corpus permission basis remains an owner item (F-046) |
| NCTB textbook corpus | `data/nctb` (gitignored, not redistributed) | rights unresolved | OWNER-DECISION (F-046); not used by any measurement this stream committed |
| Mock provider | `providers/mock.py` (repo code) | repository code; makes no external call | shipped |

No new model download, dataset or package entered the tree from this stream's
work, so no new licence obligation was created.
