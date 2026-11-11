# RAG V3 — Final Execution Report

**Prompt executed:** `Bangla_GPT_RAG_V3_Enterprise_Execution_Master_Prompt.md` v3.0.0
**Date:** 2026-11-12 · **Branch:** `feat/rag-v3-phase-0-baseline` (created from `main` per §17)
**Baseline / ending commit:** `03dfe21b6f90bc27ca476bfa459318a14bf3d266` — **unchanged**
**Application code changed:** **none** (see §2 — this is deliberate, not an omission)

---

## 1. Executive outcome

**What is implemented: Phase 0, in full, with evidence.**
**What is not implemented: every phase from 1 onward — because the prompt itself forbids it at this point.**

V3 §22 lists mandatory stop conditions, and three of them are now active: source rights are
unresolved (§5: rights holder approval required), the required class/book/edition/product
decisions have no authorized owner decision, and Phase 0's own gate forbids code changes until
it is accepted. V3 §24 step 8 says *"implement the smallest safe, independently reviewable P0
improvements first"* — and §5 marks the decisions that gate exactly which improvements are
legal. None of them arrived, so the correct execution of this prompt is to stop and report,
not to guess.

I did create the feature branch (§5 authorises this autonomously; §17 requires it), and I did
carry out the single most important thing an agent can do here: **verify the evidence system
before trusting anything built on it.** That verification failed, and the failure is the most
valuable output of this session.

### The finding that matters

> **The CI gate that is supposed to protect RAG quality does not measure the corpus the product
> serves.** `golden_v3.json` (427 items, the only eval set CI blocks on) was generated from the
> bundled **78-chunk synthetic sample**, not from NCTB. **0 of its 406 content items share a
> chapter with the real corpus.** Neither it nor `baseline_v3.json` records a corpus digest,
> embedder identity, model, or timestamp.

The gate is not weak — it is honest and well-built (independent by construction, Wilcoxon/
bootstrap statistics, >2 pp blocking, leakage-audited). It is **bound to the wrong artefact**.
No retrieval or generation improvement can be validated until that is fixed, which is why I
recommended it as the first implementation slice.

## 2. What I did not do, and why that is compliance rather than incompleteness

| Not done | Reason |
|---|---|
| No Phase 1–11 code | Each is gated by a named human decision (V3 §5) that was not provided. V3 §22: stop the affected work, continue only independent safe tasks |
| No source registry populated | V3 §5: accepting rights, and choosing storage/index/display permissions, are **always** human. V3 §10.1.7: never infer a value |
| No teacher-reviewed `golden-v4` | V3 §3: *"It is **not** a real teacher … It must never impersonate those roles or fabricate their approval"* |
| No citation enforcement promoted to blocking | V3 §7.2.6 requires calibrated false-accept/false-reject rates **before** promotion. Implementing it blind risks converting correct answers into refusals — a regression in educational value that the existing golden gate could not even detect (§1) |
| No threshold, baseline, or ratchet touched | V3 §12: *"Do not change thresholds in the same change solely to turn a failing benchmark green"* |
| No dependency added, no migration, no deployment | Out of authorised scope; nothing justified one |
| **Nothing committed** | The worktree still carries the uncommitted frontend renovation from the earlier session. V3 §17 forbids bundling unrelated work, so I left everything uncommitted rather than create a mixed commit without your answer on how to separate it |

**I also decline the framing of "make sure every parameter is fully functional."** V3 §6.2 is
explicit that *"a local mock test is not proof of live-provider behaviour"* and that a skipped
job is not a pass. What I can report is measured (below); "every parameter fully functional" is
not a claim this evidence supports, and §20 forbids making it.

## 3. Verified baseline (Phase 0 acceptance: **PASS**)

| Check | Result |
|---|---|
| Repository identity | `tanviruchahs2580/Bangla-GPT-APP` — confirmed |
| HEAD / branch at start | `03dfe21` on `main`, tracking `origin/main` |
| Worktree | dirty — pre-existing frontend work only; **no RAG file touched** |
| `ruff check` | exit 0 — All checks passed |
| `ruff format --check` | exit 0 |
| `mypy src` | exit 0 |
| `lint-imports` (5 architecture contracts) | exit 0 |
| **API unit tests** | **2127 passed, 10 skipped, 0 failed — 748 s** |
| `check_lockfile.py` | exit 0 — all 34 dependencies satisfied |
| `check_changelog.py` | exit 0 — 637 commits / 14 releases accounted for |
| `check_corpus_manifest.py --data-dir` | exit 0 — 847 chunks, 1605 index chunks, tracked artefacts agree |
| `check_corpus_manifest.py --corpus-dir` | **exit 1 — loader builds 1598, manifest records 1605** |
| `content_qa.py report` × 9 sources | exit 0 × 9 — 0 flagged chunks each |

Full transcript: [`evidence/phase0-baseline-gates.log`](v3/evidence/phase0-baseline-gates.log).
Detailed findings, gap matrix and traceability: [`v3/RAG_V3_PHASE_0_BASELINE.md`](v3/RAG_V3_PHASE_0_BASELINE.md).

## 4. Phase-by-phase completion matrix

| Phase | Priority | Status | Evidence / blocker |
|---|---|---|---|
| 0 Baseline | P0 | **PASS** | `v3/RAG_V3_PHASE_0_BASELINE.md` |
| 1 Source scope & rights | P0 | **BLOCKED — HUMAN** | D-1, D-2 |
| 2 Ingestion / OCR / page QA | P0 | **NOT RUN** | depends on D-1; no quarantine list, no offset map exist today |
| 3 Metadata / provenance / chunking | P0 | **NOT RUN** | depends on D-1; identity fields absent (0/847 chunks) |
| 4 Independent educational evaluation | P0 | **BLOCKED — HUMAN** | D-4 (a real teacher); and the set is unbound to the corpus |
| 5 Semantic embedding benchmark | P1 | **BLOCKED — HUMAN** | D-6 (licence/cost/residency) |
| 6 Retrieval / fusion / reranking | P1 | **Largely already shipped** | BM25 k1=1.5/b=0.75, RRF k=60, deterministic reranker, bigram guard |
| 7 Answer validation enforcement | **P0** | **NOT RUN** | D-5 — must measure before enforcing |
| 8 Student tutor evidence UX | P1 | **Largely already shipped** | evidence modal, citations, grounding + confidence badges |
| 9 Index lifecycle | P0 subset | **NOT RUN** | D-7; no artefact, no atomic activation, no rollback exist |
| 10 Security / privacy / child safety | P0 | **PARTIAL — controls verified good; sign-off BLOCKED** | D-8; no DPIA |
| 11 Controlled pilot | Final | **NO-GO** | all of the above |

Requirement traceability for all `SRC/ING/META/EVAL/RET/ANS/UX/OPS/SEC/ENG` identifiers is in
`RAG_V3_PHASE_0_BASELINE.md` §5 — 12 PASS, 10 FAIL, 3 PARTIAL, 3 BLOCKED, 1 NOT RUN.

## 5. Corpus, coverage and rights status

| Item | Measured |
|---|---|
| Sources | 9 PDFs — 5 secondary (*prokaashkal 2012*), 4 HSC (edition/year **UNKNOWN**) |
| **Source type** | **curriculum documents (শিক্ষাক্রম), not student textbooks (পাঠ্যাপুস্তক)** — the project states this itself at `docs/NCTB_DATA_PIPELINE.md:36-40`; a code docstring contradicts it at `nctb/sources.py:48` |
| Chunks | 847 (manifest, disk and all 9 SHA-256s agree) |
| Chapter metadata | 163 / 847 (19.2 %) |
| Class metadata | **not recorded on any source** — class is *derived* from the level label via `LEVEL_CLASS_RANGE = {"secondary": (6,10), "hsc": (11,12)}` |
| Rights metadata | **absent.** One identical free-text `license_notes` string on all 9 sources; no `rights_status`, no reviewer, no date, no separate storage/index/display permissions |
| Duplicates | 292 / 847 cross-source duplicate chunks across 100 shared-text groups |
| **What may be claimed** | nothing as a *textbook-grounded* product for any specific class/book/edition |

## 6. Extraction / page QA

Per-page `encoding` flags exist but live only in the gitignored `data/nctb/extracted/*.pages.json`.
Measured unusable pages: English **89/93**, HSC Physics 12/52, Higher Mathematics 19/52, Chemistry 6/45, Biology 8/46, Bangla 2/93, Mathematics 3/146, ICT 2/111, Science-stream 2/241.

**Unexplained inconsistency:** `quality_report.json` records `usable_pages = 91` for the English
source while its own `page_encodings` marks **89 pages unusable**. Two counters, no definition
found — `NOT VERIFIED`, recorded rather than reconciled by guess. **No quarantine list exists
anywhere in the repository.**

## 7. Chunk / provenance integrity

`page_start`, `page_end`, `source_spans` present on **847/847 (100 %)**. `section` 27 %.
`chapter` 19 %. Every other V3-required identity field — `class_level`, `subject`, `book_id`,
`edition_id`, `curriculum_year`, `language`, `content_type`, `rights_status`, `review_status`,
`normalization_version`, `chunker_version`, `schema_version` — is **absent on 0/847**.

`content_qa.py` reports 0 flagged chunks, but its `seen_texts` set resets **per file**, so the
292 cross-source duplicates are structurally invisible to it.

## 8. Benchmarks — with the identity they actually carry

| Artefact | Items | Corpus identity | Teacher reference answers |
|---|---:|---|---|
| `golden_v3.json` | 427 (dev 122 / test 305; 406 answer, 21 refuse) | **none recorded**; generated from the 78-chunk sample corpus | **0 / 427** — expectation is a source judgment (`chapter` + `section`), not an approved answer |
| `baseline_v3.json` | 427, census, `bootstrap_seed=20261029` | **none** | n/a |
| `retrieval_eval.json` | family A n=100, family B n=80 | records `corpus_digest d574832089eacf33…` — **does not match** the corpus on disk (`1396faf223aeccf5…`) | n/a |
| `redteam_v2.json` | 36, all expect-refuse, 21 categories | none | n/a |

Recorded `baseline_v3` metrics: `grounded_rate 0.7963`, `precision_true 0.9969`,
`faithfulness_avg 0.8544` (`local_overlap` mode), `language_consistency 1.0`. **These describe
the sample corpus, not NCTB, and carry no confidence-interval denominators in the committed
file** — the statistics helpers exist (`evaluation/stats.py`) but the intervals are not in the
artefact.

## 9. Citation / claim / math validation

The citation check is **real** — per-sentence content-term support ≥ 0.6, minimum 2 judged
terms, explicit `no_evidence → False` and `insufficient_signal → True`
(`services/safety.py:551-593`). It is **not enforced**: the verdict is metered, warned and
returned as `citation_verified`, and never alters control flow
(`services/tutor.py:1508-1522`, `:1801-1811`). Warn-level is documented as deliberate
(`safety.py:466-469`).

Consequences, stated plainly: **an answer whose claims are not supported by the retrieved
evidence can currently be returned with `grounded=true`.** Output safety screening *does*
block (`tutor.py:1494-1503`). Numeric/math validators exist
(`evaluation/output_validation.py`) but the semantic validator has no parser call sites.

There is also **no canonical `answer_status` enum** — the response carries booleans plus a
free-form `refused_reason: str` and `confidence: float | None`
(`schemas.py:192-201`), so a partially-supported answer is not machine-distinguishable from a
fully-supported one.

## 10. Security / privacy / child safety

**Verified good:** PII redaction before egress on the question and every history turn
(`services/tutor.py:307-323`); retrieved content and attachments treated as data inside
`<evidence>` / `<attached_image>` with escaping (`services/context.py:40-51`); prompt-injection
patterns screened first (`safety.py:291-300`); `/metrics` requires auth + token with
`compare_digest` and a production boot guard (`system.py:140-159`, `main.py:299-306`); embedder
identity refusal on mismatch (`retrieval/embedding.py:242-268`); tenancy enforced server-side.

**Blocker:** **there is no DPIA.** This is a children's product handling minors' academic
records and guardian contact data, and the project documents this as its open governance gap.
V3 Phase 10 requires policy sign-off by an authorised owner — `BLOCKED — HUMAN` (D-8).

## 11. API / web / mobile compatibility

**`NOT VERIFIED`** — and honestly so. No API contract was changed, so nothing was broken; but
no compatibility test was run this session either, because there was no change to test. The
frontend renovation from the earlier session (uncommitted) does pass 114/114 web test files and
68/68 Playwright tests including 60 visual baselines — that is a *frontend* result and is not
evidence about the RAG path.

## 12. Performance, reliability and cost

`NOT MEASURED` against any approved target, and no target exists to measure against: V3 §13
forbids inventing SLOs. Known structural facts: the index is built **per API worker at
startup** (~26.5 s on the real corpus, `RAG_INDEX_BUILD_SECONDS`), and there is **no
distributed tracing** anywhere (0 hits for `opentelemetry`/`otel`/`jaeger`/`tempo`). Rollback
of the index means redeploying the previous container tag.

## 13. CI, skipped jobs, deployment

All applicable jobs pass at HEAD. Non-blocking or conditional by design, independently
verified: `markdownlint` (config exists, wired **nowhere**), `deptry` (configured, not in CI),
`check_archive_banners.py` (Makefile only), `apps/api/scripts/gate_g3_local.py` (orphan), the nightly
`retrieval-regression` job (**has never run — the corpus is gitignored, so it skips**), and the
`real_model` quality probe (`continue-on-error: true`).

**Deployment status: `NOT VERIFIED`.** Local builds and green gates are not evidence of what is
live, and I have no access to the live host. One documented contradiction remains open: the
runbook says the live API runs **SQLite**, while `docs/operations/PRODUCTION_DEPLOYMENT.md` and
`docs/architecture/DATABASE_ARCHITECTURE.md` say Postgres.

## 14. Index activation / rollback

**No artefact-level versioning, no atomic activation, no rehearsed rollback.** The index is
in-memory, rebuilt per worker at boot; the only swap is the admin reindex mutating under a lock
(`routers/admin.py:551-583`). Cache keys carry the corpus fingerprint so stale answers age out,
and a bad corpus fails boot/health — but there is no activation control.

## 15. Open blockers, risks and human decisions

| # | Decision needed | Owner | Blocks |
|---|---|---|---|
| D-1 | Record source rights for **storage / indexing / display separately**; decide whether the 5 garbled-cover curriculum documents stay as level-wide material or are replaced with class-specific textbooks | Content / rights | 1, 2, 3, 11 |
| D-2 | Confirm the **supported scope to claim** (today: curriculum documents, classes 6–10 + HSC 11–12 — *not* textbooks) | Curriculum | 1, 11 |
| D-3 | Select the **first pilot slice** | Product/content | 11 |
| D-4 | Authorise a **real teacher** to own `golden-v4` reference answers | Education | 4, 7, 11 |
| D-5 | Approve a **calibration window** before citation enforcement is promoted warn → blocking | GenAI + education QA | 7 |
| D-6 | Approve an **embedding model + vector store**, or explicitly keep `HashingEmbedder` | Infra + privacy | 5 |
| D-7 | Approve moving **index construction off worker startup** | Architecture / SRE | 9 |
| D-8 | **Consent / retention / safeguarding** sign-off and the standing **no-DPIA** gap | Policy / legal | 10, 11 |

**Top technical risks:** (1) the eval gate's binding — every future quality claim rests on it;
(2) the stale `retrieval_eval.json` fingerprint, whose self-reference is broken *by
construction*, so regeneration alone will not fix verifiability; (3) 81 % of chunks without
chapter metadata; (4) the acquisition year substituted for an unknown edition year in served
metadata.

## 16. Supported release scope, and what must not be claimed

**Supported for any student-facing textbook-grounded claim: nothing.**

Do not claim, on this evidence: "production-ready", "enterprise-grade certified",
"100 % accurate", "fully NCTB-covered", "all Classes 6–12 supported", or any per-class
textbook coverage. The corpus is curriculum documentation, its rights status is one free-text
string, most chunks carry no chapter or class identity, and the only blocking quality gate
measures a synthetic sample.

## 17. Recommendation

### `NO-GO` for a student pilot.

This is V3 §21's own default, and it holds on three independent grounds: source rights are
unresolved (D-1), no curriculum slice has been authorised (D-2/D-3), and the evaluation
evidence is not bound to the corpus actually served (§1). Per §21, `CONDITIONAL GO` may not be
used to bypass a source-rights or student-safety blocker, and both are present — the second as
the absent DPIA.

**The single next action with the highest expected value** is the evidence-binding slice: bind
`golden_v3`/`baseline_v3`/`retrieval_eval` to a corpus digest and embedder identity, fix the
manifest back-reference so it is verifiable, and add a gate that fails on fingerprint
mismatch. It is V3 P0 (`EVAL-02`, `ING-04`), additive, touches no threshold or serving
behaviour, needs no human decision, and is the prerequisite for any later phase being provable
at all.

---

## Appendix — V3 §21 launch approval template

| Gate | Owner role | Status | Evidence |
|---|---|---|---|
| Official source and rights verified for storage/index/display | Content / rights owner | **NOT VERIFIED** | one shared free-text `license_notes`; no rights fields exist |
| Edition and supported scope confirmed | Curriculum owner | **NOT VERIFIED** | 4 HSC sources `UNKNOWN`; class derived from a level label |
| Extraction and page QA passed | Data eng + content reviewer | **NOT VERIFIED** | English source 89/93 unusable; `usable_pages=91` unreconciled; no quarantine list |
| Metadata and page provenance passed | RAG / data eng | **FAIL** | 0/847 chunks carry V3 identity fields; chapter 19 % |
| Held-out retrieval benchmark passed | ML evaluation owner | **NOT VERIFIED** | benchmark is bound to the sample corpus; real-corpus metric file fingerprint-stale |
| Teacher answer correctness passed | Authorised teacher / education QA | **NOT VERIFIED** | 0/427 items have reference answers; no teacher engaged (D-4) |
| Claim / citation / math enforcement passed | GenAI eng + QA | **FAIL** | citation check computed but not enforced (ANS-02) |
| API / client compatibility passed | Backend + frontend QA | **NOT RUN** | no change made to test |
| Privacy, security and child-safety approved | Security / privacy / policy owner | **BLOCKED** | controls verified good; **no DPIA**; D-8 unsigned |
| Load, cost, index lifecycle and rollback passed | SRE / operations | **FAIL** | no artefact versioning, no atomic activation, no rehearsed rollback |
| Consent / safeguarding process approved | School / guardian / policy owner | **NOT VERIFIED** | D-8 |
| Pilot experience approved | Product + education owner | **NOT VERIFIED** | D-3 |

**Decision: `NO-GO`** — the default under §21, unchanged.
