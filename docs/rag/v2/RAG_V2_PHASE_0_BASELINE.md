# RAG V2 — Phase 0 Baseline Report

**Prompt executed:** `Bangla_GPT_RAG_V2_Enterprise_Upgrade_Master_Prompt.md` v2.1.0
**Date:** 2026-11-12 · **Branch:** `feat/rag-v3-phase-0-baseline` · **`main`:** `03dfe21`
**Application code changed in this phase:** **none**

Companion evidence (all measured at `03dfe21`): `docs/rag/v3/RAG_V3_PHASE_0_BASELINE.md`,
`docs/rag/v3/RAG_ARCHITECTURE_REVIEW_AND_ELEVATION_PLAN.md`,
`docs/rag/v3/STAGE_D_SOURCE_AVAILABILITY_FINDING.md`,
`docs/rag/v3/PROVIDED_DOCUMENT_ASSESSMENT.md`,
`docs/rag/v3/evidence/phase0-baseline-gates.log`.

---

## 1. Repository identity (re-verified)

| Item | Value |
|---|---|
| Remote | `https://github.com/tanviruchahs2580/Bangla-GPT-APP.git` |
| Branch | `feat/rag-v3-phase-0-baseline` (created from `main` per §17; `main` untouched) |
| HEAD | `03dfe21b6f90bc27ca476bfa459318a14bf3d266` — **identical to the historical reviewed SHA**, so the V2 baseline is current, not stale |
| Working tree | carries the earlier frontend renovation (14 files under `apps/web`) **plus this phase's documentation only**; **zero `apps/api` changes**, **zero `data/` changes** |
| Latest release tag | `v0.10.0` |

## 2. Baseline gates at HEAD (executed, not assumed)

| Gate | Command | Result | Exit |
|---|---|---|---:|
| Lint | `python -m ruff check .` | All checks passed | 0 |
| Format | `python -m ruff format --check .` | clean | 0 |
| Typecheck | `python -m mypy src` | clean | 0 |
| Architecture | `lint-imports` (5 contracts) | clean | 0 |
| **Unit/component** | `python -m pytest -q` | **2127 passed, 10 skipped, 0 failed** (748 s) | 0 |
| Lockfile | `check_lockfile.py` | all 34 dependencies satisfied | 0 |
| Changelog | `check_changelog.py` | 637 commits / 14 releases accounted | 0 |
| Corpus manifest (tracked) | `check_corpus_manifest.py --data-dir data/nctb` | 847 chunks / 1605 index chunks; artefacts agree | 0 |
| **Corpus manifest (served)** | `check_corpus_manifest.py --corpus-dir` | **loader builds 1598, manifest records 1605** | **1** |
| Content QA × 9 | `content_qa.py report <each>` | `flagged_chunks=0` each | 0 ×9 |

Full transcript: `docs/rag/v3/evidence/phase0-baseline-gates.log`.

**No pre-existing red.** The one failure (§2, served-manifest count) is a *finding* about corpus
identity, not a regression introduced here.

## 3. As-built architecture (verified, summarised)

Online: `POST /tutor/ask` / `…/messages[/stream]` → normalise (NFKC + zero-width) → **safety
screen before retrieval** → query analysis (stop-words, framing, grade numerals, glossary,
Banglish romanisation, spelling repair) → **BM25 (k1=1.5, b=0.75) + hashing-vector lane (char
2–4-gram, dim 384, `hash-ngram-local`)** over a 3×`top_k` candidate pool → **RRF k=60** →
deterministic reranker (IDF coverage 0.5 / proximity 0.8 / trigram 0.3) → **grounding gate**
(IDF-weighted content-term coverage ≥ 0.5, `OUT_OF_CORPUS_ABSENT_BUDGET = 2`, fuzzy ≥ 0.6) →
`top_k=3`, `EVIDENCE_TOKEN_BUDGET=768` → `sanitize_evidence` → **PII redaction before egress** →
provider (breaker + fallback, bounded concurrency 8) → **output screen blocks** →
`citation_check` computed but **not enforced** → `AskResponse{answer, grounded, sources[],
refused_reason, citation_verified, confidence}`.

Offline: acquisition (sha256) → pypdf extraction + per-page encoding flags → Bijoy→Unicode
where detected → NFC + zero-width strip → structure-aware chunking (220/60/450 tokens, no
overlap) → `normalized/*.chunks.jsonl` + `quality_report.json` → `corpus_manifest.json` →
**index built at API worker startup** (`initialize/dependencies.py:212-330`), in memory only.

## 4. Phase 0 gap matrix against V2

| Phase | Priority | Status | Note |
|---|---|---|---|
| 0 Baseline | P0 | **PASS** | this document |
| 1 Source scope & rights | P0 | **BLOCKED** | §5 — no approved Class 6 source exists |
| 2 Ingestion / OCR / page QA | P0 | **BLOCKED** | depends on Phase 1; no OCR capability in the repo (`tesseract`/`ocrmypdf` absent; no OCR dependency in `pyproject.toml`; `OcrUnavailable` declared at `pyproject.toml:169` but never implemented) |
| 3 Metadata / provenance | P0 | **BLOCKED** | depends on Phase 1; 0/847 chunks carry any V2 identity field |
| 4 Independent educational evaluation | P0 | **BLOCKED** | `golden_v3` has **0/427 reference answers** and is generated from the 78-chunk synthetic sample, not NCTB |
| 5 Semantic embedding benchmark | P1 | **NOT RUN** | decision requires owner (licence/cost/residency) |
| 6 Retrieval / fusion / reranking | P1 | **Largely shipped** | no change justified by evidence yet |
| 7 Answer validation enforcement | **P0** | **NOT RUN** | `citation_check` computed, metered, logged — **never blocks** (`tutor.py:1508-1522`, `:1801-1811`) |
| 8 Tutor / evidence UX | P1 | **Largely shipped** | evidence modal, citations, badges |
| 9 Index lifecycle | P0 subset | **BLOCKED** | no artefact, no atomic activation, no rehearsed rollback; per-worker boot build |
| 10 Security / privacy / child safety | P0 | **PARTIAL** | controls verified good; **no DPIA** |
| 11 Controlled pilot | Final | **NO-GO** | §7 |

## 5. Phase 1 — Class 6 inventory (V2 §0.1, executed as a read-only sweep)

V2 §0.1 authorises this autonomously: *"Determine which Class 6 books are actually present in
the approved dataset | Yes, by read-only inventory."*

| Candidate | Measured | Verdict |
|---|---|---|
| `data/nctb/normalized/*.chunks.jsonl` — 847 chunks | **0** carry class 6 in `detected_classes`. The 5 secondary sources have `detected_classes=None`; the 4 HSC sources have `[11,12]` | **No Class 6 content** |
| Class-6 attribution mechanism | `LEVEL_CLASS_RANGE = {"secondary": (6,10), "hsc": (11,12)}` (`nctb/data/nctb_loader.py:55`) — class is a **level range**, never a book class | Cannot yield a Class-6-only corpus |
| `apps/api/src/bangla_gpt_api/data/sample_nctb/` | contains `class6_bangla.md`, `class6_math.md`, `class6_science.md` | **Excluded by V2 §0.1 itself** — *"Files under `sample_nctb` … are test fixtures …; never treat synthetic sample text as an actual NCTB textbook"* |
| Official registry `nctb/sources.py` | declares 16 secondary + 32 HSC artifacts; only **one** is class-named — `bba604a3…` "আইসিটি (ষষ্ঠ শ্রেণি)" | **Not held** on disk, and measured to be an **11-page legacy-Bijoy curriculum extract** (learning-outcome / assessment tables), not a textbook |
| Both official listing pages | headed `মাধ্যমিক স্তরের শিক্ষাক্রম` / `উচ্চ মাধ্যমিক স্তরের শিক্ষাক্রম` — **শিক্ষাক্রম = curriculum** | The verified source pages publish **curriculum documents, not textbooks**. The `sources.py` docstring calling them "textbook PDFs" is factually wrong (gap `SRC-03`) |
| User-supplied `ICT_compressed.pdf` | 74 pp scan, 21 MB, **0 extracted characters**, pages 2–5 yield no text *and* no images, largest image ≈92 DPI; **no OCR engine present** | **Not ingestible** without building a rights-approved OCR path and human-validating it (V2 Phase 2 gate) |

**Conclusion: the approved dataset contains zero genuine Class 6 textbook sources.**

## 6. V2 §7.4 hard stop — declared

> *"if the repository/runtime contains only synthetic sample material or broad curriculum
> documents and no approved Class 6 textbook corpus, continue safe engineering work on
> deterministic fixtures and contracts, but mark real textbook ingestion and student-corpus
> acceptance `BLOCKED — APPROVED CLASS 6 SOURCE DATA NOT AVAILABLE`. Do not manufacture, scrape,
> mirror, or relabel content to make the pipeline appear complete."*

### `BLOCKED — APPROVED CLASS 6 SOURCE DATA NOT AVAILABLE`

This is **the prescribed SOP outcome**, not a failure to execute. Wiring the curriculum
documents, the HSC sources, or `sample_nctb` into the active Class 6 corpus would each violate
V2 §0.1 directly, and would make the product *look* Class-6-scoped while serving level-wide or
synthetic content.

**What is deliberately not done, and why:**
- No source deleted — `data/nctb/` is entirely untracked and gitignored, so removal is
  irreversible; and dropping the 4 HSC sources removes classes 11–12 coverage, contradicting the
  existing-feature protection rule (§0).
- No synthetic or curriculum content relabelled as Class 6.
- No threshold, baseline, ratchet or manifest touched.

## 7. Status of the user's instructions

| Instruction | Status |
|---|---|
| "execute by strictly maintaining swe sop" | **PASS** — Phase 0 executed to V2 §8/§6; hard stop applied at V2 §7.4 |
| "test run after finishing all the task" | Gates executed at HEAD (§2). The 2127-test suite is the pre-change baseline; it is re-run after any code change |
| "make sure every parameter is fully functional" | **Cannot be claimed.** V2 §6.2: a local mock test is not proof of live-provider behaviour, and a skipped job is `NOT RUN` |
| "do not break any existing feature" | **PASS** — zero `apps/api` and zero `data/` changes; all gates identical to the recorded baseline |

## 8. Safe engineering that does NOT depend on Class 6 data (authorised by §7.4)

These are the "deterministic fixtures and contracts" V2 directs me to continue with. Each is
additive, needs no corpus, and is listed with its target:

| Item | V2 anchor | Target |
|---|---|---|
| **A1** Corpus identity in every eval report (`corpus_digest`, embedder, prompt version, dataset version) | Phase 4 acceptance; `EVAL-02` | `evaluation/cli.py` report payload |
| **A2** Fix the manifest self-reference that can never verify (hash captured before `_update_manifest` rewrites it, `scripts/evaluate_nctb_retrieval.py:405` vs `:494`) | Phase 3 acceptance | same script, plus `check_corpus_manifest.py` |
| **A3** Eval-binding gate that fails on a corpus-fingerprint mismatch | Phase 4 | new a new eval-binding gate (**not yet written**) under `apps/api/scripts/` + `eval-gate.yml` |
| **A4** Stop fabricating the acquisition year **2026** for an `UNKNOWN` edition year in served metadata | Phase 1 task 7; Phase 3 task 4 | `nctb/data/nctb_loader.py:163-173` |
| **A5** Canonical `answer_status` / `grounding_status` / `citation_status` / `validation_status`, additive | §7.1 (`V2-A14`) | `schemas.py` + client-compat tests |

**A1–A3 are the critical path**: they are what makes *any* later corpus change measurable, and
A2's fix is what makes the recorded evidence verifiable at all.

## 9. Human decisions still required

| # | Decision | Owner | Blocks |
|---|---|---|---|
| D-1 | Supply an **approved Class 6 textbook** with a text layer, or authorise and fund the OCR path (rights-approved adapter + human validation of Bangla OCR accuracy) | Content / rights owner | Phases 2, 3, 11 |
| D-2 | Confirm the supported-scope claim (Class 6 only; all other classes labelled unsupported) | Curriculum owner | Phase 1, 11 |
| D-3 | A **real teacher** to own reference answers for `golden-v4` | Education owner | Phase 4, 7, 11 |
| D-4 | Consent / retention / safeguarding sign-off and the absent **DPIA** | Policy / legal owner | Phase 10, 11 |

## 10. Phase 0 acceptance

**PASS.** HEAD, branch, worktree, package commands, existing contracts, corpus identity and
applicable CI are documented with command evidence; the Class 6 inventory is complete; the hard
stop is declared with evidence; no application code was changed; unknown production facts remain
`NOT VERIFIED` rather than inferred.
