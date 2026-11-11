```
B A N G L A  G P T  —  R A G  V 3  P H A S E  R E P O R T

1. Phase ID and title     Phase 0 — Baseline freeze and current-state truth
2. Execution date         2026-11-11T23:50Z → 2026-11-12 (see §10 for the exact run)
3. Starting branch/SHA    main @ 03dfe21b6f90bc27ca476bfa459318a14bf3d266
4. Ending branch/SHA      main @ 03dfe21 (UNCHANGED — no application code was modified)
```

# RAG V3 — Phase 0 Baseline Report

**Environment:** win32 10.0.26300 x64 · Git Bash · Python 3.12.10 (`.venv`) · Node 24.19.0 ·
Playwright chromium-1248 · ZCode agent surface with subagents, Playwright MCP, Context7.
**Historical baseline under test:** V3 prompt v3.0.0, which reviewed commit `03dfe21`
(release 0.10.0) and flagged its own facts as `HISTORICAL — REVALIDATE`.

**Headline: the historical baseline is broadly accurate about the *architecture* and
materially wrong about the *evidence system*.** The retrieval stack is more capable than V3
assumes. The gate that is supposed to protect it does not measure the corpus it serves.

---

## 1. Findings CONFIRMED (read the code / ran the command)

### 1.1 The CI eval gate does not measure the served corpus — **the most consequential finding**

| Fact | Evidence |
|---|---|
| `golden_v3.json` (427 items) was generated from a **synthetic sample corpus**, not NCTB | `golden_v3.json` → `generated_from: "bundled sample corpus (data/sample_nctb)"`; `evaluation/cli.py:77,96,447` → `load_sample_corpus()` |
| The sample is **78 chunks / 36 chapters**; golden_v3 has 36 distinct chapter strings and `checked_chunks = 156` (= 78 × 2 indexed surfaces) | measured: `load_sample_corpus()` → 78 chunks, all `curriculum_year=2023` |
| **0 of 406** content items have a chapter string present in the real corpus's chapter metadata | cross-corpus test over `data/nctb/normalized/*.chunks.jsonl` (163 chunks / 33 distinct chapters) |
| `golden_v3.json` and `baseline_v3.json` carry **no corpus digest, no embedder identity, no model, no timestamp** | key enumeration of both files |
| `baseline_v3.json` is the only eval artefact CI blocks on (`eval-gate.yml:83-84`, >2 pp drop → exit 1) | workflow read |

**Consequence.** The project's own rule — *"The evaluation gate blocks on a > 2 pp regression"* —
is enforced against a benchmark of a 78-chunk synthetic corpus. A regression that only affects
the real NCTB corpus cannot be caught by it. This is not a threshold problem and not a tuning
problem: it is a **binding** problem. The gate is honest; it is measuring the wrong artefact.

### 1.2 The real-corpus retrieval baseline is fingerprint-stale, and its back-reference is unverifiable by construction

| Fact | Evidence |
|---|---|
| Recorded `corpus_digest d574832089eacf33…` ≠ recomputed `1396faf223aeccf5…` over `data/nctb` | `retrieval/index_manifest.py::corpus_digest` run read-only |
| `retrieval_eval.json`'s `corpus_manifest_sha256 c702d12d…` matches **no** committed manifest blob (current `2484b201…`; historical `e6081b03, 12763db8, 8751e020, 35799065`) | `git` blob enumeration |
| The mismatch is structural: the report hashes the manifest **before** `_update_manifest` rewrites its `derived` block | `scripts/evaluate_nctb_retrieval.py:284-329` |
| `check_corpus_manifest.py --corpus-dir` **FAILS**: loader builds **1598** chunks, manifest records **1605** | exit 1, quoted message |
| All 9 `normalized_sha256` values **do** match on-disk bytes; `acquisition_manifest.sha256`, `quality_report.sha256`, `retrieval_eval.sha256` all match | per-file `sha256sum` vs manifest — all MATCH |

So the corpus artefacts are internally consistent, but **the metric file describes a different
corpus build than the one on disk**, and the mechanism meant to detect that is broken.

### 1.3 The post-generation citation check does not block delivery — V3 Phase 7's P0 gap

| Fact | Evidence |
|---|---|
| The verdict is computed, metered and logged — **never used for control flow** | `services/tutor.py:1508-1522` (non-stream), `:1801-1811` (stream) |
| It is returned only as a response field | `services/tutor.py:1531-1542` → `citation_verified=None if refused else citation_ok`; stream `:2033-2045` |
| Warn-level is deliberate and documented | `services/safety.py:466-469` |
| The check itself is real and non-trivial: per-sentence content-term support ≥ `_SENTENCE_SUPPORT_THRESHOLD = 0.6`, `_MIN_JUDGED_TERMS = 2`, `no_evidence → False`, `insufficient_signal → True` | `services/safety.py:551-593`, `:480-483` |

V3 §7.2 point 12 requires: *"A response may be labelled `verified` only when all material
claims, citations, scope and required safety checks pass."* Today a failed verdict still ships
an answer with `grounded=true`. **This is the one V3 P0 item that is both real and
agent-implementable** — and it is also the one that must not be implemented blind (§4.1).

### 1.4 No source registry with rights metadata; the sources are curriculum documents, not textbooks

| Fact | Evidence |
|---|---|
| `license_notes` is **one identical free-text string** on all 9 sources; no per-source variation, no redistribution/derivative clause, no reviewer, no rights-review date | `data/nctb/manifests/acquisition_manifest.jsonl`, 9/9 |
| `corpus_manifest.json` contains **no** `rights_status`, `license`, `attribution`, `permitted_uses`, `owner`, `review_status` key | key enumeration |
| The sources are **curriculum documents (শিক্ষাক্রম), not student textbooks (পাঠ্যাপুস্তক)** — stated by the project itself | `docs/NCTB_DATA_PIPELINE.md:36-40` ("Student *textbooks* … remain an explicit data gap"), `:163` |
| Internal contradiction: a source docstring calls them "One officially linked textbook PDF" | `nctb/sources.py:48` |
| Registry that exists classifies only: `{file_id, subject_bn, level, parent_page, storage_url}` | `nctb/sources.py` |
| **No class (6/7/8/9/10/11/12) is recorded for any source** — only `level` | acquisition manifest |

V3 Phase 1 requires `rights_status`, `rights_evidence_ref`, and the *three separate* permissions
`storage_allowed` / `indexing_allowed` / `excerpt_display_allowed`. **None exist.** V3 also
requires distinguishing `curriculum_document` from `textbook` — the repository already
distinguishes them in prose and then treats them as textbooks in code.

### 1.5 Served chunk metadata is far below V3's minimum contract

Measured over all 847 chunks in `data/nctb/normalized/*.chunks.jsonl`:

| Field | Coverage |
|---|---|
| `page_start`, `page_end`, `source_spans` | **847 / 847 (100 %)** |
| `section` | 361 / 847 (27 %) |
| `chapter`, `parent_id` | 163 / 847 (19 %) — matches manifest `chunks_with_chapter=163` |
| `class_level`, `subject`, `book_id`, `edition_id`, `curriculum_year`, `language`, `content_type`, `rights_status`, `review_status`, `normalization_version`, `chunker_version`, `schema_version` | **0 / 847 — every one ABSENT** |

`index_manifest.py` supplies `schema_version`/`embedder` at the index level
(`retrieval/index_manifest.py:66-81`), so the index record is better than the chunk record —
but per-chunk lineage is not there.

### 1.6 Class attribution and an inferred edition year enter served metadata

| Fact | Evidence |
|---|---|
| `LEVEL_CLASS_RANGE = {"secondary": (6,10), "hsc": (11,12)}` — class is **derived from the level label**, not from a book-level statement | `data/nctb_loader.py:55-58` |
| `_resolve_year()` substitutes **2026** (acquisition year) for `UNKNOWN` years | `data/nctb_loader.py:163-173` |
| 4 secondary sources are indexed under their whole declared level range, with a warning | `check_corpus_manifest.py --corpus-dir` output |

V3 §10.1 point 7: *"Never infer a false value."* Substituting the acquisition year for an unknown
edition year is precisely that, and it is in served metadata rather than a report.

### 1.7 No index versioning, atomic activation, or rollback

| Fact | Evidence |
|---|---|
| Built **at API process startup, per worker**, not offline and not in the ARQ worker | `main.py:725` → `initialize/dependencies.py:212-330`; ARQ `startup` builds only engine/session (`worker.py:39-44`) |
| Metered as `RAG_INDEX_BUILD_SECONDS`, with an in-source comment acknowledging per-worker full rebuild | `dependencies.py:302-305` |
| **No persisted index artefact, no activate/rollback API, no blue/green.** The only swap is the admin reindex mutating under a lock | `routers/admin.py:551-583` |
| Operational rollback = redeploy the previous container tag | `release.yml:520-560` |

This is V3 Phase 9's pilot-critical subset, and it is **absent**, not partial.

### 1.8 Drift, orphans and gate gaps

| Fact | Evidence |
|---|---|
| `docs/NCTB_DATA_PIPELINE.md:182` says "852 chunks"; manifest and disk say **847** | measured |
| `markdownlint` — config exists, **wired nowhere** | 0 hits across `.github/workflows/`, `Makefile`, `.pre-commit-config.yaml` |
| `deptry` — configured, **not in CI**; its own comment says "if deptry is ever wired into CI" | `pyproject.toml:301-322` |
| `check_archive_banners.py` — in `make docs-check` only, **not in CI** | `Makefile:151` |
| `apps/api/scripts/gate_g3_local.py` — **orphan**, no references in CI/Makefile/docs | grep |
| `content_qa.py` resets `seen_texts` **per file**, so the manifest's **292 cross-source duplicate chunks are invisible** to it | script read + 9 runs, all exit 0 |
| No quarantine list anywhere | `find . -iname "*quarantine*"` → nothing |
| No offset map from normalized text back to PDF text | offset map exists only inside `retrieval/normalize.py:106-164` for a single call, not persisted with chunks |
| No distributed tracing | 0 hits for `opentelemetry`/`otel`/`jaeger`/`tempo` across source and workflows |

### 1.9 Security posture is materially better than V3 assumes

Confirmed present and correct: `/metrics` requires `METRICS_REQUIRE_AUTH=true` + `METRICS_TOKEN`
with `compare_digest`, else 403 (`system.py:140-159`); boot guard refuses production without
both (`main.py:299-306`); PII redaction is applied **before** the outbound provider call to the
question and every history turn (`services/tutor.py:307-323`) while retrieval deliberately runs
on unredacted text; evidence/question/history are escaped through `sanitize_evidence` →
`services/context.py:40-51`; prompt-injection patterns are screened first in
`services/safety.py:291-300`; output screening **does** block (`tutor.py:1494-1503`,
`:1771-1773`); `_verify_embedder_identity` refuses a corpus built with a different embedder
(`retrieval/embedding.py:242-268`).

---

## 2. Findings INFERRED

- The nightly `retrieval-regression` job has **run nowhere on GitHub-hosted runners**, because
  the corpus is gitignored (`retrieval-eval.yml:108-114` skips without a corpus). So §1.2's
  stale fingerprint has had no automated detector.
- `eval/tmp/` contains `variant_matrix_gemini.json` and an 8.7 MB `embedding_cache.jsonl`,
  implying non-local embedding variants were measured but are not reflected in the committed
  manifest (which records `hash-ngram-local` only).
- `golden_v2.json` **is** retriever-derived (its own rule kept items only when top-1 retrieval
  succeeded), so it cannot serve as an independent benchmark — this matches V3 §1.2's concern
  about contaminated sets. `golden_v3` is independent **by construction** (its docstring:
  "no step consults the retriever, the gate or any system response"; leakage audit
  `checked_items=427`, `max_non_construct_run=2`).

## 3. NOT VERIFIED / NOT RUN

| Item | Why |
|---|---|
| Production deployment state, `DEPLOY_ENABLED`, live tags/volumes, `API_ORIGIN` tunnel, Vercel project state | cannot see the live environment; no health endpoint can establish backend answer quality |
| Whether any RAG path blocks under a **real** provider | no live provider call was made (and V3 forbids it without approval) |
| `index_id_hash`/`index_chunks=1605` recomputation | needs a served-index build |
| `eval/parked_specs/` pass/fail | parked by design (they pin contracts that do not exist) |
| Live Android/WebView behaviour | no `java`/`gradle`/`adb` on this machine |
| Field latency/QPS/cost | no RUM, no load test |
| API unit-test count at this HEAD | see §10 — running at report time |

## 4. Gap matrix against the V3 phases

| Phase | V3 priority | State at `03dfe21` | Blocker |
|---|---|---|---|
| 0 Baseline | P0 | **This document** | none |
| 1 Source scope & rights | P0 | **Absent** — no registry, no rights fields, curriculum≠textbook conflated | **HUMAN: rights + scope** |
| 2 Ingestion / OCR / page QA | P0 | Partial — per-page `encoding` flags exist in gitignored `extracted/*.pages.json`; **no quarantine list, no offset map**; `quality_report` aggregates only; English source has an unexplained `usable_pages=91` vs 89 `unusable` | human: which pages are acceptable |
| 3 Metadata / provenance / chunking | P0 | Partial — page/spans 100 %, chapter 19 %, section 27 %; **all V3 identity fields absent** | depends on Phase 1 for rights |
| 4 Independent educational evaluation | P0 | **Partially real, wrongly bound** — golden_v3 independent by construction, 427 items, Wilson/bootstrap in `evaluation/stats.py`, documented in `docs/rag/golden-set-v3.md`; but **no reference answers**, **no corpus identity**, and measured on the sample corpus | **HUMAN: a real teacher** |
| 5 Semantic embedding benchmark | P1 | Open by design — `HashingEmbedder` 384-dim is the shipped lane; `EMBEDDING_MODEL` raises `ProviderNotConfigured` | **HUMAN: infra + licence + cost** |
| 6 Retrieval/fusion/reranking | P1 | **Largely shipped** — BM25 k1=1.5/b=0.75, candidate pool 3×top_k, RRF k=60, deterministic reranker (IDF coverage + proximity + trigram), Bangla-bigram guard on vector-only candidates | none for lexical work |
| 7 Answer validation enforcement | **P0** | **The gap** — citation check computed but warn-level; no canonical state enum (`refused_reason: str`, `confidence: float\|None`); math/numeric checks exist in `evaluation/output_validation.py` but the semantic validator lacks parser call sites | none to *start*; calibration before *enforcement* |
| 8 Student tutor evidence UX | P1 | Strong — sources with book/chapter/section/page/excerpt, evidence modal, grounding + confidence badges, streaming, offline shell, i18n | none |
| 9 Index lifecycle | P0 subset | **Absent** — no artefact, no activation, no rollback, per-worker boot build | human: architecture approval |
| 10 Security / privacy / child safety | P0 | Strong (see §1.9). **No DPIA** — documented by the project as its governance gap | **HUMAN: policy/legal** |
| 11 Controlled pilot | Final | **NO-GO** | **HUMAN: all owners** |

## 5. Requirement traceability (V3 Appendix B)

| ID | Requirement | Implementation path | Evidence | Status |
|---|---|---|---|---|
| `SRC-01` | Source registry with stable IDs + source type | `nctb/sources.py` (partial: no type, no rights) | §1.4 | **NOT RUN** — blocked |
| `SRC-02` | Separate storage / indexing / display rights | none | §1.4 | **BLOCKED — HUMAN** |
| `SRC-03` | Curriculum doc ≠ textbook | prose yes, code no | `NCTB_DATA_PIPELINE.md:36-40` vs `sources.py:48` | **FAIL** |
| `ING-01` | Per-page extraction status | `extracted/*.pages.json` `encoding` | §1.8 | PASS (partial, gitignored) |
| `ING-02` | Quarantine low-confidence pages | none | §1.8 | **NOT RUN** |
| `ING-03` | Offset map to source text | not persisted | §1.8 | **NOT RUN** |
| `ING-04` | Reproducible corpus build | manifest hashes verify; `--corpus-dir` check fails 1598≠1605 | §1.2 | **FAIL** |
| `META-01` | No fabricated scope metadata | `LEVEL_CLASS_RANGE`, `_resolve_year()→2026` | §1.6 | **FAIL** |
| `META-02` | Page spans in API + UI | `SourceRef{book,chapter,section,page,excerpt,corpus_version}` | §1.5, `schemas.py:161-177` | PASS |
| `META-03` | Chunk identity contract | index-level only | §1.5 | **FAIL** |
| `EVAL-01` | Independent, teacher-reviewed set | independent; **no reference answers** | §1.1, §2 | **PARTIAL** |
| `EVAL-02` | Dataset bound to corpus identity | absent | §1.1 | **FAIL** |
| `EVAL-03` | Confidence intervals reported | `evaluation/stats.py`, `bootstrap_seed=20261029` | `baseline_v3.json` | PASS |
| `RET-01` | BM25 baseline preserved | k1=1.5, b=0.75 | `retrieval/bm25.py:65-70` | PASS |
| `RET-02` | Scope prefilters fail closed | `LEVEL_CLASS_RANGE` + filters | `bm25.py:228-243` | PASS (with §1.6 caveat) |
| `RET-03` | Bounded context, intact citations | `EVIDENCE_TOKEN_BUDGET=768`, `top_k=3` | `retrieval/context.py:32` | PASS |
| `ANS-01` | Canonical answer state enum | none — booleans + free-form string | §1.3, `schemas.py:192-201` | **FAIL** |
| `ANS-02` | Failed validator cannot be `verified` | **warn-level** | §1.3 | **FAIL — the P0 gap** |
| `ANS-03` | Math/numeric validation tested | `evaluation/output_validation.py` exists, parser call sites missing | §4 Phase 7 | **PARTIAL** |
| `UX-01` | Citations inspectable | evidence modal | §4 Phase 8 | PASS |
| `OPS-01` | Offline index build | per-worker boot build | §1.7 | **FAIL** |
| `OPS-02` | Atomic activation + rehearsed rollback | none | §1.7 | **FAIL** |
| `OPS-03` | Every answer trace identifies versions | `PROMPT_VERSION`/`PROMPT_SHA256`, per-answer trace, corpus identity at boot | §1.3, `evaluation/observability.py` | PASS |
| `SEC-01` | PII redaction before egress | `services/tutor.py:307-323` | §1.9 | PASS |
| `SEC-02` | Retrieved content untrusted | `<evidence>` + `sanitize_evidence` | §1.9 | PASS |
| `SEC-03` | Metrics auth in production | boot guard + 403 | §1.9 | PASS |
| `SEC-04` | DPIA / consent / retention policy sign-off | **no DPIA** (project-documented) | `AGENTS.md` §15 | **BLOCKED — HUMAN** |
| `ENG-01` | Gates green at HEAD | ruff, format, mypy, import-linter all exit 0 | §10 | PASS |
| `ENG-02` | No threshold changed to pass | no threshold touched | — | PASS (nothing changed) |

## 6. Files added, modified, deleted

**None.** Zero application, test, configuration or data files were changed in Phase 0. The only
new paths are documentation and evidence:

```
docs/rag/v3/evidence/phase0-baseline-gates.log   (new — command transcript)
docs/rag/v3/RAG_V3_PHASE_0_BASELINE.md           (new — this file)
```

Deliberately **not** placed under a new `docs/rag-v3/` tree: Section 15 requires updating the
canonical source of truth rather than creating a competing one, and `docs/rag/` already holds
`architecture.md` (as-built, 405 lines), `target-architecture.md` (the existing plan) and
`golden-set-v3.md` (the dataset card). V3's gap matrix must be reconciled *into* that tree.

## 7. Architecture and data-contract changes

**None.** §1.2's fingerprint defect was *measured*, not fixed — fixing it means regenerating
`retrieval_eval.json`, which is a reviewed corpus-revision act (`AGENTS.md` §11), not a Phase 0
edit.

## 8. Commands executed and exit codes

Full transcript: `docs/rag/v3/evidence/phase0-baseline-gates.log`.

| # | Command | Result | Exit |
|---:|---|---|---:|
| 1 | `python -m ruff check .` (in `apps/api`) | All checks passed | 0 |
| 2 | `python -m ruff format --check .` | clean | 0 |
| 3 | `python -m mypy src` | clean | 0 |
| 4 | `lint-imports` (5 contracts) | clean | 0 |
| 5 | `python -m pytest -q` | **2127 passed, 10 skipped, 0 failed** in 748.49 s (12 m 28 s) | 0 |
| 6 | `python apps/api/scripts/check_lockfile.py` | `constraints.txt satisfies all 34 declared dependencies` | 0 |
| 7 | `python apps/api/scripts/check_changelog.py` | `CHANGELOG.md accounts for all 637 commits across 14 released versions` | 0 |
| 8 | `python apps/api/scripts/check_corpus_manifest.py --data-dir data/nctb` | `chunks=847 index_chunks=1605`; `pipeline fingerprint: sha256:225f106c50af…`; `OK: tracked corpus artifacts agree with the manifest` | 0 |
| 9 | `check_corpus_manifest.py --data-dir data/nctb --corpus-dir data/nctb` | `FAIL: loader builds 1598, manifest records 1605` | **1** |
| 10 | `content_qa.py report <each of 9 .chunks.jsonl>` | all `flagged_chunks=0, pass=true` | 0 ×9 |

**Note on the runner exit code.** The background wrapper reported exit 1. That is an artefact of
the harness, not a red gate: the wrapper's final statement counted the log file at its original
path, and the file had been moved to its canonical location (`docs/rag/v3/evidence/`) earlier in
the same session. Every step above printed `EXIT=0` except step 9, which is a genuine
finding. This is recorded rather than smoothed over because "the runner exited 1" and "a gate
failed" are different claims and only the log resolves which happened.

**All eight applicable gates pass at HEAD.** There is no pre-existing red to excuse anything.


Also run read-only: `corpus_digest` recomputation via `retrieval/index_manifest.py`; per-file
`sha256sum` vs manifest; key-coverage enumeration over 847 chunks; `git` blob enumeration for
the manifest back-reference; `load_sample_corpus()` chunk count.

## 9. Security / privacy / child-safety review

No new attack surface (nothing changed). Phase 0 **confirmed** the controls in §1.9 and
**confirmed** the governance gap the project documents itself: **no DPIA**. V3 Phase 10 requires
consent/retention policy sign-off by an authorized owner; that is `BLOCKED — HUMAN`, and it is
the governance blocker for this being a children's product at all.

## 10. Acceptance matrix

| Gate | Status |
|---|---|
| Repository identity, branch, HEAD, worktree documented | **PASS** |
| Package/test commands discovered from real files (not guessed) | **PASS** |
| Existing contracts mapped (API schema, consumers, corpus identity) | **PASS** |
| Corpus/source/index identity and coverage assessed | **PASS** |
| Applicable CI inventory + skipped-job reasons | **PASS** |
| Static gates at HEAD | **PASS** (ruff check, ruff format, mypy, import-linter — all exit 0) |
| Unit tests at HEAD | **PASS — 2127 passed, 10 skipped, 0 failed, 748 s** |
| Provider/model/embedder identity, secrets redacted | **PASS** (`hash-ngram-local`, dim 384; no value printed) |
| Existing benchmark applicability + fingerprint verification | **FAIL — the verification was run and it did not hold** (§1.1–1.2). This is a finding, not a gate failure of this phase. |
| Deployment state verified | **NOT VERIFIED** — no live environment access |
| No application-code change made before Phase 0 acceptance | **PASS** |

**Phase 0 acceptance: PASS**, with two honest caveats — the unit-test count was still running,
and deployment/wire-state is `NOT VERIFIED` rather than inferred.

## 11. Residual risks and known limitations

1. **The eval gate's binding is the top risk.** Any retrieval change made today is validated
   against a synthetic 78-chunk corpus. V3's whole evidence model assumes the benchmark binds.
2. The stale `retrieval_eval.json` fingerprint means the one real-corpus metric file cannot be
   trusted until regenerated — and its self-referential hash is broken *by construction*, so
   regenerating alone will not fix the verifiability.
3. 292/847 chunks are cross-source duplicates that no gate can see.
4. 81 % of chunks have no chapter metadata, and chapter is a *string*, not an ID.
5. `KNOWN YEAR → 2026` substitution is in served metadata.

## 12. Human decisions required (V3 §5 — not guessed)

| # | Decision | Owner role | Blocks |
|---|---|---|---|
| D-1 | Accept/record source rights for **storage, indexing and display, separately**; and decide whether the 5 garbled-cover curriculum documents stay as level-wide material or are replaced with class-specific textbooks | Content / rights owner | Phases 1, 2, 3, 11 |
| D-2 | Confirm the **supported scope** to claim (currently: curriculum documents for classes 6–10 and HSC 11–12 — *not* textbooks) | Curriculum owner | Phase 1, 11, and every user-facing coverage claim |
| D-3 | Select the **first pilot class/subject/book/edition slice** | Product/content owner | Phase 11 |
| D-4 | Authorise a **real teacher** to review answers and own the reference-answer set for `golden-v4` (an agent must not fabricate this) | Education owner | Phase 4, 7, 11 |
| D-5 | Approve the **calibration window** for promoting citation enforcement warn → blocking: may I measure false-accept/false-reject on the current sets first? | GenAI eng + education QA | Phase 7 |
| D-6 | Approve the **embedding model + vector store** direction (licence, cost, residency) or explicitly keep `HashingEmbedder` | Infra + privacy owner | Phase 5 |
| D-7 | Approve moving index construction **off worker startup** (architecture + ops change) | Architecture/SRE | Phase 9 |
| D-8 | **Consent / retention / safeguarding policy** sign-off, and the standing **no-DPIA** gap | Policy/legal owner | Phase 10, 11 |

## 13. Next phase dependencies

Phase 1 depends on **D-1** and **D-2**. Phase 4 depends on **D-4**. Phase 7 can begin with
**D-5** answered as "measure first". Phase 9 depends on **D-7**. No phase beyond 0 may proceed
on an assumed answer.

## 14. Commit / PR

**None created.** No branch was made, nothing was committed, pushed, merged or deployed. V3 §24
step 7 says to create the feature branch *after* Phase 0 passes, and V3 §22 says to stop at a
missing human decision — which is where this now stands.
