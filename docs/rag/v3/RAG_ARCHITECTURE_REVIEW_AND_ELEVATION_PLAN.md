# Bangla GPT — RAG System Architecture Review, QA Audit & Enterprise Elevation Plan

**Review type:** full architecture review + QA audit + readiness assessment (read-only; no code changed)
**Date:** 2026-11-12 · **Branch:** `feat/rag-v3-phase-0-baseline` · **Reviewed commit:** `03dfe21`
**Review lens:** OpenAI senior generative-AI engineer + cross-functional team
(Solutions Architect · RAG/GenAI · IR/Search · Data/PDF-OCR · Backend · Frontend/Android ·
ML Evaluation & Statistics · QA Automation · AppSec & Privacy · SRE · Education-domain QA)

**Basis:** direct code reads with `path:line`, executed commands with exit codes, and measured
artefact statistics. Everything is labelled `CONFIRMED` (measured), `INFERRED` (reasoned from
adjacent evidence), or `NOT VERIFIED`. No runtime claim about production is made.

Companion evidence: `docs/rag/v3/RAG_V3_PHASE_0_BASELINE.md`,
`docs/rag/v3/RAG_V3_FINAL_EXECUTION_REPORT.md`,
`docs/rag/v3/evidence/phase0-baseline-gates.log`.

---

# PART 1 — EXECUTIVE VERDICT

## 1.1 The one-paragraph answer

Bangla GPT's RAG is **engineering-mature and pedagogically unverified**. The pipeline is real
and thoughtfully built — hybrid retrieval, RRF fusion, a deterministic reranker, an
IDF-weighted grounding gate that refuses rather than guesses, PII redaction before egress,
prompt-injection screening, evidence delimiters, streaming with per-delta safety screening. In
several places it is **better than the V3 prompt assumed**. But the system cannot honestly
claim to be *curriculum-scoped* or *textbook-grounded* today, for four independent reasons that
compound: (1) the corpus is **curriculum documents, not student textbooks**; (2) **no source
carries a book-level class**, so class scoping is a level-wide range for all 9 sources; (3) the
benchmark that gates quality is **bound to a 78-chunk synthetic sample**, not to the corpus
served; and (4) the corpus's **rights status is a single free-text sentence** with no
permission split for storage / indexing / display. The engineering is ready to be trusted; the
**evidence and the content rights are not yet ready to be trusted**. That distinction is the
whole audit.

## 1.2 Readiness scorecard

| Dimension | Grade | Why |
|---|---|---|
| Pipeline architecture & modularity | **A−** | Modular monolith, clean boundaries, 5 enforced import-linter contracts, sensible online/offline split *in intent* |
| Retrieval engineering | **B+** | BM25 correctly tuned, RRF k=60, deterministic reranker with documented weights, anti-collision bigram guard on vector-only candidates |
| Refusal / honesty design | **A−** | Gate refuses on insufficient evidence; refusal is a first-class outcome asserted in tests; helpline numbers pinned |
| Answer enforcement | **D** | The citation validator is computed, metered, logged — **and never blocks** |
| Evaluation integrity | **F** | The blocking benchmark measures a synthetic sample; **0 of 406** items share a chapter with the real corpus; no corpus digest anywhere |
| Metadata & provenance | **D** | Page spans 100 %, but chapter 19 %, section 27 %, and **every identity field absent on 0/847 chunks** |
| Curriculum scope correctness | **F** | Class is a level range for all 9 sources; 5 of 9 have **no class at all** in the artefact |
| Source rights governance | **F** | One identical free-text note on 9 sources; no reviewer, no date, no storage/index/display split |
| Security & privacy controls | **A−** | PII redaction pre-egress, evidence treated as data, metrics auth + boot guards, tenancy server-side |
| Governance (consent/DPIA) | **F** | **No DPIA** for a children's product handling minors' records — the project documents this itself |
| Observability | **C+** | Good Prometheus surface for the RAG hot path; **zero distributed tracing**; traces can silently vanish |
| Index lifecycle | **F** | Rebuilt per worker at boot (~26.5 s); no artefact, no atomic activation, no rehearsed rollback |
| CI & engineering discipline | **A−** | Excellent gate coverage, ratchets, import-linter, nightly retrieval job — but 4 declared gates are wired nowhere |
| Frontend / evidence UX | **B** | Citations inspectable, evidence modal, grounding + confidence badges, offline shell, bn/en parity |
| **Student-serving readiness** | **NO-GO** | See §6 |

## 1.3 The five findings a senior review would escalate first

1. **The quality gate is bound to the wrong corpus.** `golden_v3.json` — the only set CI blocks
   on — declares `generated_from: "bundled sample corpus (data/sample_nctb)"`. 78 chunks, 36
   chapters. **0 of 406 content items share a chapter with the real corpus.** Neither it nor
   `baseline_v3.json` records a corpus digest, embedder, model or timestamp. *Every quality
   claim the project makes currently rests on this.*
2. **The citation validator does not enforce.** `services/tutor.py:1508-1522` / `:1801-1811`
   compute the verdict, increment a metric, log a warning, set a response field — and never
   alter control flow. Warn-level is documented as deliberate (`safety.py:466-469`). An answer
   whose claims are unsupported by the retrieved evidence can ship with `grounded=true`.
3. **Nothing is curriculum-scoped.** Measured over all 847 chunks: the 4 HSC sources carry
   `detected_classes=[11,12]`; **the 5 secondary sources carry `detected_class=None` and
   `detected_classes=None` — no class at all.** Class enters only at load time via
   `LEVEL_CLASS_RANGE = {"secondary": (6,10), "hsc": (11,12)}` (`nctb/data/nctb_loader.py:55`).
   A class-6 student can be grounded on class-10 material.
4. **An unknown edition year is fabricated into served metadata.** `_resolve_year()`
   (`nctb_loader.py:163-173`) substitutes **2026** (the acquisition year) where the manifest says
   `UNKNOWN`. Four HSC sources record `edition: UNKNOWN`.
5. **The corpus is not what the product says it is.** `docs/NCTB_DATA_PIPELINE.md:36-40` states
   the sources are curriculum documents (শিক্ষাক্রম) and that student textbooks remain "an
   explicit data gap"; `nctb/sources.py:48` calls them "textbook PDF". A curriculum document
   states objectives and assessment structure — it is **not** a source a student's answer can be
   grounded in.

---

# PART 2 — AS-BUILT ARCHITECTURE (verified)

## 2.1 Online request path

```
POST /tutor/ask · /tutor/conversations/{id}/messages[/stream]
  routers/tutor.py:268 · :759 · :893            (CurrentUser; rate-limited; consent-gated)
    ↓ kill switch (AI_GENERATION_ENABLED) :274  ↓ AI budget services/costs.py:234 → 429
    ↓ normalize_query  services/tutor.py:275-287  (NFKC + narrow zero-width strip)
    ↓ _screen_safety   services/tutor.py:1573   ← BEFORE retrieval (correct order)
      8 categories + prompt_injection first (safety.py:291-300)
      evasion layers: _screening_variants :268 · bijoy pass :380 · academic lift :226
    ↓ _retrieve_and_gate :1588
      query analysis (stop-words, framing, grade-numerals)  retrieval/query_analysis.py
      BM25 k1=1.5 b=0.75 (bm25.py:65) + vector lane (char 2-4gram hash, dim 384)
        lexically indexed as section×2 + chapter + body
        query-side: synonyms · spelling repair · Banglish romanisation · EN glossary
      RRF k=60 (fusion.py:11) over candidate pool 3×top_k = 9/lane
      vector-only candidates gated on shared Bangla bigrams (hybrid_index.py:275-281)
      deterministic rerank: W_rrf 1.0 / W_coverage 0.5 / W_proximity 0.8 / W_trigram 0.3
    ↓ grounding gate: IDF-weighted content-term coverage ≥ 0.5 (RAG_MIN_COVERAGE)
        + OUT_OF_CORPUS_ABSENT_BUDGET = 2  (tutor.py:615)
        + fuzzy trigram ≥ 0.6 per term    (FUZZY_MATCH_SIMILARITY, tutor.py:609)
        fail → INSUFFICIENT_EVIDENCE_ANSWER, grounded=false   :1617 / :1887
    ↓ context assembly: top_k=3, EVIDENCE_TOKEN_BUDGET=768 (context.py:32)
    ↓ sanitize_evidence on chunks/question/history  (services/context.py:40-51)
    ↓ PII redaction on question + every history turn  tutor.py:307-323   ← BEFORE egress
    ↓ provider.generate / stream  (breaker + fallback; timeouts fit LLM_TOTAL_BUDGET_SECONDS=45)
    ↓ output screen — BLOCKS (tutor.py:1494-1503) + per-delta screening on stream :1771
    ↓ citation_check (safety.py:551-593) → ⚠ COMPUTED, NOT ENFORCED
  AskResponse{answer, grounded, sources[], refused_reason, citation_verified, confidence}
```

**Measured at HEAD:** `pytest -q` → **2127 passed, 10 skipped, 0 failed (748 s)**;
`ruff check` / `ruff format --check` / `mypy src` / `lint-imports` all exit 0.

## 2.2 Offline corpus path

```
nctb.gov.bd listings → acquisition (sha256, idempotent) → data/nctb/raw (9 PDFs, gitignored)
  → pypdf extraction + per-page encoding flags → extracted/*.pages.json
  → legacy Bijoy→Unicode where detected → NFC + zero-width strip
  → structure-aware chunking (220 target / 60 min / 450 max tokens, no overlap)
  → normalized/*.chunks.jsonl + quality_report.json → manifests/corpus_manifest.json
  → index built AT API WORKER STARTUP (main.py:725 → initialize/dependencies.py:212-330)
```

## 2.3 Measured corpus reality

| Metric | Value |
|---|---|
| Sources | 9 (5 secondary `প্রকাশকাল ২০১২`; 4 HSC `edition: UNKNOWN`) |
| Chunks | **847** (manifest == disk; all 9 `normalized_sha256` verified byte-exact) |
| Chunk size (words as proxy) | p10 94 · **p50 210** · p90 226 · max 285 · min 55 |
| `page_start`/`page_end`/`source_spans` | **847/847 (100 %)** |
| `section` | 361/847 (27 %) |
| `chapter` / `parent_id` | **163/847 (19 %)** |
| `class_level`, `subject`, `book_id`, `edition_id`, `curriculum_year`, `language`, `content_type`, `rights_status`, `review_status`, `normalization_version`, `chunker_version`, `schema_version` | **0/847 — all absent** |
| Cross-source duplicates | 292/847 (555 unique texts; 100 shared-text groups) |
| Class attribution in artefact | HSC: `[11,12]` · **Secondary: `None` (no class)** |
| Unusable pages | English **89/93** · HSC Physics 12/52 · H. Math 19/52 · Chemistry 6/45 · Biology 8/46 |
| Quarantine list | **does not exist** |
| Offset map to PDF text | **not persisted** |

---

# PART 3 — REVIEW BY DIMENSION

## 3.1 Retrieval architecture

**What is right.** BM25 is correctly parametrised (k1=1.5, b=0.75) and, unusually well, indexes
`section×2 + chapter + body` so a heading can satisfy the gate. The query side is genuinely
thoughtful for this user population: curated synonyms, spelling repair (`কোশ`→`কোষ`), Banglish
romanisation with a vowel-skeleton second pass, and a ~75-concept English glossary. RRF at
k=60 is standard and correct. The vector-only-candidate guard — a candidate admitted by the
hashing lane must share Bangla bigrams with the query — is a genuinely sophisticated
anti-hallucination control that most production systems lack.

**Critique 1 — there is no semantic retrieval.** The vector lane is `HashingEmbedder`
(char 2–4-grams, dim 384, `retrieval/embedding.py:28-29,79-81`). Character n-gram hashing
captures **orthographic and phonetic** similarity, not meaning. It cannot connect
`আলো কীভাবে কাজ করে?` to `আলোর প্রতিসরণ`, because they share almost no character n-grams. The
project is honest about this in `docs/RAG_ARCHITECTURE.md` ("deterministic phonetic lane"), so
this is a **known architectural gap, not a hidden defect** — but it is the single largest
capability limitation, and every recall number in the repo is achieved without it.

**Critique 2 — the evidence budget is thin for the question types the product advertises.**
`top_k=3` and `EVIDENCE_TOKEN_BUDGET=768` (`retrieval/context.py:32`) against a measured median
chunk of ~210 words means the third chunk is frequently trimmed. So an answer is typically built
from **~2.5 passages**. That is workable for "define X". It is thin for the comparison,
multi-hop and worked-mathematics questions the frontend offers, and V3 Phase 6 explicitly
requires "multi-hop questions receive adequate distinct evidence".

**Critique 3 — no parent/neighbour expansion is possible even in principle.** Expansion needs
`sibling links` and a parent chain. `chapter`/`parent_id` exist on only 19 % of chunks and
`chapter` is a **string, not an ID**. Section 81 % of the corpus is an orphan passage.

**Critique 4 — a broken lane degrades silently.** `_retrieve_guarded:992` wraps retrieval in a
bare `except Exception` and falls back to the BM25 lane alone; a second path returns `[]`,
which the gate then refuses. The intent (RAG-28) is sound, but a **permanently** broken vector
or rerank stage would be visible only in logs and a metric delta — not as a failure. There is no
assertion that the active lane count is what configuration says it is.

## 3.2 Chunking and provenance

The chunker is structure-aware with a token budget (220/60/450) and **no overlap**. Measured
distribution is tight (p10 94 → p90 226) and the 450 ceiling is never approached (max 285
words), so the budget is not the constraint — **structure is**: the chunker only finds a
boundary when the extraction preserved a heading, which is why 81 % of chunks have no chapter.

**Consequences.** (a) A definition split across a boundary is unrecoverable without overlap.
(b) 292/847 chunks are cross-source duplicates and the QA gate **cannot see them** —
`content_qa.py` resets `seen_texts` per file, so the manifest's own `duplicate_chunks=292` is
invisible to the checker that is supposed to catch it. (c) There is **no quarantine list
anywhere in the repo** (`find -iname "*quarantine*"` → nothing), despite V3 Phase 2 requiring
one and the English source being 96 % unusable. (d) There is **no persisted offset map** from
normalized text back to PDF text, so exact-span highlighting is not achievable — the offset
machinery exists (`retrieval/normalize.py:106-164`) but its output is not stored with the chunk.

**Data-quality anomaly left unexplained:** `quality_report.json` records
`usable_pages = 91` for the English source while its own `page_encodings` marks **89 pages
unusable** out of 93. Two counters, no definition found. `NOT VERIFIED`.

## 3.3 Grounding gate and refusal design

This is the strongest part of the system and the part most aligned with the product's duty of
care. The gate runs on **content terms** (stop-word planes for Bangla, romanised and English;
question-framing removal; grade-numeral removal), weighted by corpus document frequency
`ln(1 + N/df)`, with a trigram fuzzy allowance ≥ 0.6 for a dropped conjunct. The
`OUT_OF_CORPUS_ABSENT_BUDGET = 2` rule was a genuine fix: before it, `ক্রিকেট বিশ্বকাপ ফাইনালে কে
জিতেছিল?` was grounded at coverage 1.0 on the word `কে` (df=183).

**Critique 5 — the out-of-domain rule was validated on four items.** The corrections note reads
"re-measured false-answer 3/4 → 0/4 on the family-C probes". `n=4` supports no conclusion; the
difference between 3/4 and 0/4 is not statistically distinguishable from noise at any
conventional level. The fix is almost certainly right on inspection — but it is **unvalidated**,
and it is the single most safety-relevant threshold in the system. This is exactly the V3 §1.2
concern about thresholds that "operationalize" without sample size, strata or intervals.

**Critique 6 — two thresholds are hard-coded in source, not configuration.**
`OUT_OF_CORPUS_ABSENT_BUDGET = 2` (`tutor.py:615`), `OUT_OF_DOMAIN_WEIGHT_FRACTION = 0.7`
(`:622`), `OUT_OF_DOMAIN_MIN_DOCUMENTS = 200` (`:625`), `FUZZY_MATCH_SIMILARITY = 0.6`
(`tutor.py:609`), `_SENTENCE_SUPPORT_THRESHOLD = 0.6` (`safety.py:480`),
`_MIN_JUDGED_TERMS = 2` (`:483`). Only `RAG_MIN_COVERAGE`, `RAG_TOP_K`, `RAG_RRF_K` and
`RAG_CANDIDATE_FACTOR` are settings. Untuning-by-configuration means every threshold experiment
is a code change — which is why the `n=4` validation has not been improved.

**Critique 7 — the false-refusal rate is the untracked risk.** In-corpus false refusal measured
5/624 (0.8 %) on golden_v2 — acceptable. But that was measured on the **sample** corpus. On the
real curriculum corpus, whose vocabulary differs from student phrasing (objectives language, not
teaching language), **the false-refusal rate is unknown**. A refusal is a correct outcome, but a
*needless* refusal on a class-6 question is a failed learning moment.

## 3.4 Generation, prompt and provider

**Good:** `PROMPT_VERSION = "tutor-prompt-v1"` with `PROMPT_SHA256` computed at import and
recorded in traces (`tutor.py:245-253`, `:1390-1396`). Evidence is injected inside
`<evidence>`/`</evidence>` with escaping that rewrites the closing tag, both tag names, the
`<user_question>` tag and `[education-context]` pairs (`services/context.py:40-51`). The image
part is declared inside `<attached_image>` with a matching data-only rule. PII redaction is
applied to the question and **every history turn** before egress (`tutor.py:307-323`), while
retrieval deliberately runs on unredacted text — a correct and subtle distinction.

**Critique 8 — nothing verifies the prompt hash at runtime.** It is computed and recorded, and
no code checks it (`grep` found only recording sites). So the identity exists for audit but
cannot detect drift.

**Critique 9 — provider fallback can abandon a partial stream.** `_stream_with_fallback` restarts
generation on another provider and emits `onReset`; the frontend drops the orphaned partial
(verified in the frontend review). This is handled correctly for the student, but it means a
single answer can be billed twice, and there is no cap on cumulative spend per turn beyond the
budget guard.

## 3.5 Answer contract and validation

**Critique 10 — there is no canonical answer state machine.** `AskResponse`
(`schemas.py:192-201`) is `answer: str`, `grounded: bool`, `sources[]`,
`refused_reason: str | None`, `citation_verified: bool | None`, `confidence: float | None`.
V3 §7.1 requires `answer_status ∈ {verified, partially_supported, general_guidance,
clarification_required, refused, error}` plus `grounding_status`, `citation_status`,
`validation_status`. Two problems follow: (a) a client cannot distinguish a **fully supported**
answer from a **partially supported** one — both are `grounded=true`; (b) `refused_reason` is a
free-form `str`, not a `Literal`, so the frontend must string-match values and a rename breaks
consumers silently.

**Critique 11 — `confidence` is a formula, not a calibrated probability.** Derived via
`services/safety.py::answer_confidence(grounded, reason, sources)`. V3 §7.1: *"Do not expose a
numeric confidence probability unless calibrated against human labels."* The frontend renders
this number to a child. The faithfulness judge is `mode="local_overlap"` — a lexical-overlap
proxy, not entailment — so the number is not even indirectly validated.

**Critique 12 — the citation check is real but toothless.** Per-sentence content-term support
≥ 0.6, minimum 2 judged terms, `no_evidence → False`, `insufficient_signal → True`
(`safety.py:551-593`). It replaces an older whole-answer stem-overlap check that a fabricated
sentence passed (documented correction #4). The replacement is materially better. **But it never
blocks.** `tutor.py:1508-1522` computes → `RAG_CITATION_CHECKS_TOTAL.inc()` → `log.warning` →
field. `tutor.py:1801-1811` does the same on the stream.

**Critique 13 — maths/numeric validation has no call site.** `evaluation/output_validation.py`
exists and is deterministic, but the semantic validator has no parser call sites; nothing
recomputes a numeric answer. The frontend renders KaTeX, so a wrong worked step is presented
with the visual authority of typeset mathematics.

## 3.6 Evaluation and benchmark integrity — **the critical section**

| Artefact | Items | Bound to corpus? | Reference answers |
|---|---:|---|---|
| `golden_v3.json` | 427 (dev 122 / test 305; 406 answer / 21 refuse) | **No** — `generated_from: "bundled sample corpus (data/sample_nctb)"` | **0/427** |
| `baseline_v3.json` | 427, census, `bootstrap_seed=20261029` | **No** — no digest, no embedder, no model, no timestamp | n/a |
| `golden_v2.json` | 634 | **No** — and **retriever-derived** by its own rule (kept only items whose top-1 retrieval succeeded) → contaminated as a benchmark | 0/634 |
| `retrieval_eval.json` | family A n=100, family B n=80 | records `corpus_digest d574832089eacf33…` — **does not match** the on-disk corpus (`1396faf223aeccf5…`) | n/a |
| `redteam_v2.json` | 36, all expect-refuse, 21 categories | No | n/a |

**Critique 14 — the blocking gate measures the wrong artefact.** This is the review's central
finding. `eval-gate.yml:83-84` runs `python -m bangla_gpt_api.evaluation.cli`, which defaults to
`golden_v3.json` / `baseline_v3.json`, which are measured over `load_sample_corpus()` — 78
chunks, 36 chapters. I tested independence directly: **0 of 406 content items have a chapter
string present in the real corpus's chapter metadata.** So a retrieval or generation change
that helps or harms the **served** corpus is invisible to the only gate that can fail a build.
`baseline_v3`'s `grounded_rate 0.7963` describes synthetic material.

**Critique 15 — the metric file's self-reference is broken by construction.**
`retrieval_eval.json` records `corpus_manifest_sha256 = c702d12d…`, which matches **no** committed
manifest blob (current `2484b201…`; historical `e6081b03, 12763db8, 8751e020, 35799065`). Cause:
`scripts/evaluate_nctb_retrieval.py:284-329` hashes the manifest **before** `_update_manifest`
rewrites its `derived` block. So regenerating the file will **not** fix verifiability — the
ordering must change first.

**Critique 16 — nothing detects a stale benchmark.** `check_corpus_manifest.py --corpus-dir`
**fails** today (loader builds **1598** chunks, manifest records **1605**), exit 1. And the
nightly `retrieval-regression` job has **never run on a GitHub-hosted runner** — the corpus is
gitignored, so it skips (`retrieval-eval.yml:108-114`). There is therefore no automated detector
for the exact class of drift already present.

**Critique 17 — the leakage audit is real but narrow.** `checked_items=427`,
`checked_chunks=156`, `max_non_construct_run=2`, 9 prompt surfaces. Good practice. But there is
no strata-level reporting, no per-class/per-subject denominators in the committed baseline, and
no confidence intervals **in the artefact** (the helpers exist in `evaluation/stats.py`).

## 3.7 Curriculum scope and metadata truthfulness

**Critique 18 — the product's central claim is not implemented.** Measured across all 847
chunks: **the 5 secondary sources carry no class at all** (`detected_class=None`,
`detected_classes=None`); the 4 HSC sources carry the range `[11,12]`. Class is applied only at
load time from `LEVEL_CLASS_RANGE` (`nctb_loader.py:55`). So *every* source is served under a
level-wide range and **no chunk is attributable to a specific class/book/edition**. A class-6
student asking about a topic can be grounded on class-10 curriculum content. This is not a
rounding error — it is the difference between "curriculum-scoped tutor" and "level-scoped
search".

**Critique 19 — an unknown value is fabricated.** `_resolve_year()` (`nctb_loader.py:163-173`)
substitutes the acquisition year **2026** where the manifest records `UNKNOWN`. V3 §10.1.7:
*"Preserve unknown edition/year/rights values as explicit UNKNOWN, PENDING or UNVERIFIED; never
infer a false value."* This is in served metadata, not a report.

**Critique 20 — `chapter` and `section` are strings, not IDs.** No stable identifiers exist, so
there is no way to express "same chapter, different section", to join to `concepts`, or to
detect a chapter rename as a change rather than a new chapter.

## 3.8 Source rights and content governance

**Critique 21 — rights are one sentence.** All 9 sources share an **identical** free-text
`license_notes`: "Official NCTB public download; copyright NCTB/Government of Bangladesh. Use
restricted to curriculum-grounded tutoring research/product." No per-source variation, **no
reviewer, no review date, no redistribution/derivative clause**, and — critically — **no split
between the three distinct permissions the product depends on**: storage, indexing, and
**excerpt display to a student**. The last is the one that matters most, because the product
shows page-level excerpts in the evidence modal. V3 Phase 1 requires these as separate fields
with evidence references.

**Critique 22 — a docstring contradicts the project's own documentation.**
`docs/NCTB_DATA_PIPELINE.md:36-40` correctly says student textbooks are "an explicit data gap";
`nctb/sources.py:48` says "One officially linked textbook PDF". When code and docs disagree about
what the corpus *is*, the product's public claims are unsourced.

## 3.9 Security, privacy and child safety

**Verified good.** PII redaction pre-egress on question + all history turns (`tutor.py:307-323`);
`<evidence>`/`<attached_image>` delimiters with escaping; prompt-injection patterns screened
**first** among safety checks; output screening **does block** (`tutor.py:1494-1503`);
`/metrics` requires `METRICS_REQUIRE_AUTH` + token with `compare_digest`, else 403, with a
production boot guard; `_verify_embedder_identity` refuses a corpus built with a different
embedder; tenancy enforced server-side; helpline numbers pinned to the government values and
test-enforced.

**Critique 23 — a stream can leak an unsafe prefix.** `tutor.py:1765-1773`: screening runs
*before each delta leaves*, so a student receives "at most the longest screen-clean prefix of a
bad completion" — the comment says so itself. An answer that becomes unsafe at sentence four has
already emitted sentences one to three. This is a deliberate latency/safety trade-off, but it is
a real child-safety exposure and V3 Phase 10 requires testing "conversation/history poisoning"
and unsafe-answer spikes. There is no bound on the leaked prefix length.

**Critique 24 — degradation paths are silent.** `_retrieve_guarded:992` bare `except Exception`;
`_record_trace:1409-1410` `except Exception: logger.warning` (so **the audit trace, including
`citation_verdict` and `composed_prompt_sha256`, can silently vanish**); `safety.py:400-401`
swallows the Bijoy-conversion failure and therefore **skips an entire screening pass** for that
input; `middleware.py:124` `_user_key` failure silently downgrades a per-user rate limit to
per-IP (weaker).

**Critique 25 — no DPIA.** This is a children's product processing minors' academic records,
misconception profiles and guardian contact data. `docs/data_minimization.md`,
`docs/dpa_template.md`, `docs/security/threat-model.md`, `docs/ai/risk-register.md` and
`docs/ai/system-card.md` all exist. **None is a DPIA.** The project documents this as its open
governance gap. It is a hard blocker for student service.

## 3.10 Observability, reliability and cost

**Good.** A real Prometheus surface for the hot path: `RAG_INDEX_CHUNKS`,
`RAG_RETRIEVAL_LATENCY_SECONDS`, `RAG_INDEX_BUILD_SECONDS`, `RAG_GATE_OUTCOMES_TOTAL`,
`RAG_GATE_REFUSALS_TOTAL{reason}`, `RAG_CITATION_CHECKS_TOTAL{result}`,
`RAG_LANE_LATENCY_SECONDS`, `RAG_GATE_COVERAGE`, `RAG_INDEX_REBUILDS_TOTAL`, with alerts
(`HighRAGRefusalRate`, `RAGCitationCheckFailures`). Structured JSON logging with a request-id
contextvar. `/ready` is truthful — it degrades to 503 when the index is absent rather than
answering every turn with a failure.

**Critique 26 — no distributed tracing.** Zero hits for `opentelemetry`/`otel`/`jaeger`/`tempo`
across Python source and workflows. Per-stage latency is aggregated, not traceable per request,
so "why was this answer bad?" cannot be answered from telemetry — only from a trace record that
may itself have been swallowed (Critique 24).

**Critique 27 — no SLO, no measured baseline for load.** No request-rate, p95/p99, TTFT, memory
or per-student cost figures exist. `docs/capacity_plan.md` is dated 2026-09-08 and is a
projection, not a measurement. V3 §13 correctly forbids inventing targets — but that means the
capacity question is currently **unanswered**, not merely unapproved.

## 3.11 Index lifecycle

**Critique 28 — the pilot-critical subset is entirely absent.** V3 Phase 9's P0 list requires:
build outside request handling ✔ (partially — it is outside the request path but *inside* worker
startup); immutable versioned artefacts ✘; manifest verified before activation ✘ (it is verified
*after* boot, by refusing to start); atomic activation ✘; rehearsed rollback ✘; answer trace
identifies corpus/index versions ~ (boot log + cache fingerprint, not per answer); fail safely on
mismatch ✔ (embedder pin).

Concretely: the index is rebuilt **per worker at boot**, ~**26.5 s** on the real corpus
(`RAG_INDEX_BUILD_SECONDS`), in memory only. There is **no persisted artefact, no
activate/rollback API, no blue/green swap**. The only swap is the admin reindex mutating under
`reindex_lock` (`routers/admin.py:551-583`). Index rollback = redeploy the previous container
tag. With `WEB_CONCURRENCY` workers, a bad corpus is discovered by failing health checks, not by
activation control.

## 3.12 API and client contracts

**Critique 29 — no client inventory exists.** `AskResponse` is consumed by web, PWA and the
Capacitor Android app. Any change to it is a three-client change, and there is no recorded
inventory of which client reads which field, no contract test, and no versioning of the answer
schema. V3 §11.4 requires the inventory before a schema change. `citation_verified` is absent
from `ChatMessageOut` (`schemas.py:254-265`), so the same answer shown from history cannot
display the same verification state as when it was live — an inconsistency the frontend already
has to work around.

## 3.13 Frontend / evidence UX

**Good**, and independently reviewed earlier in this session: citations open an evidence modal
with book/chapter/section/page/excerpt; grounding and confidence badges; streaming with Stop;
`X-Request-ID`; offline shell; bn/en parity; 60 visual baselines; 68/68 e2e passing.

**Critique 30 — the UI exposes a number it should not.** The confidence badge renders
`formatNumber(...)` of an uncalibrated formula (Critique 11) to a child. And because
`citation_verified` is not enforced, the UI's "grounded" presentation can accompany unsupported
claims. **The frontend is currently more trustworthy-looking than the backend is.**

## 3.14 CI/CD and engineering discipline

**Excellent baseline:** 14 workflow files; blocking `api` matrix (3.11 + 3.12) with Redis,
Postgres with `alembic check`, SBOM, guardrails (pip-audit, semgrep, gitleaks full history,
CodeQL, Trivy, Scorecard), Lighthouse CI, Playwright across three engines, `eval-gate`,
`retrieval-eval` nightly, radon complexity ratchet, coverage floors as ratchets,
`check_corpus_manifest.py`, `content_qa.py`, pre-commit.

**Critique 31 — four declared gates are wired nowhere** (independently verified, not taken from
docs): `markdownlint` (config current, zero CI hits), `deptry` (configured; its own comment says
"if deptry is ever wired into CI"), `check_archive_banners.py` (Makefile `docs-check` only), and
`scripts/gate_g3_local.py` (orphan). Plus `content_qa.py`'s per-file `seen_texts` blind spot.

**Critique 32 — the API suite takes 12.5 minutes** (2127 tests). That is a workable but
attention-worthy figure for a 42-table app, and it is the reason `web` is gated behind
`needs: eval` rather than running fully parallel.

---

# PART 4 — GAP REGISTER (complete, severity-ranked)

Severity: **P0** = blocks any student service · **P1** = blocks a *credible* pilot · **P2** = scale/ops · **P3** = refinement.

| # | ID | Gap | Sev | Evidence |
|---|---|---|---|---|
| 1 | `EVAL-02` | Blocking benchmark bound to a 78-chunk synthetic sample; 0/406 items share a chapter with the served corpus | **P0** | `golden_v3.generated_from`; cross-corpus test |
| 2 | `EVAL-04` | No corpus digest / embedder / model / prompt identity in `golden_v3` or `baseline_v3` | **P0** | key enumeration |
| 3 | `META-01` | No class attribution for any source; 5/9 have `detected_class=None`; class = level range | **P0** | measured over 847 chunks; `nctb_loader.py:55` |
| 4 | `ANS-02` | Citation validator computed but never blocks | **P0** | `tutor.py:1508-1522`, `:1801-1811` |
| 5 | `SRC-02` | No rights registry; storage / indexing / display not separated; no reviewer or date | **P0** | `acquisition_manifest.jsonl` 9/9 identical |
| 6 | `SEC-04` | **No DPIA** for a children's product | **P0** | project self-documented (`AGENTS.md` §15) |
| 7 | `SRC-03` | Corpus is curriculum documents, not textbooks; docs and code contradict | **P0** | `NCTB_DATA_PIPELINE.md:36-40` vs `sources.py:48` |
| 8 | `ANS-01` | No canonical `answer_status` enum; `refused_reason` is free-form `str` | **P0** | `schemas.py:192-201` |
| 9 | `META-05` | `chapter`/`section` are strings, not stable IDs | **P0** | 0/847 identity fields |
| 10 | `META-03` | 81 % of chunks lack chapter; 73 % lack section → no parent expansion possible | **P0** | 163/847, 361/847 |
| 11 | `ANS-04` | `confidence` is an uncalibrated formula rendered to a child | **P0** | `safety.answer_confidence`; V3 §7.1 |
| 12 | `EVAL-05` | `retrieval_eval.json` corpus digest stale; manifest back-reference unverifiable by construction | **P0** | recomputation; `evaluate_nctb_retrieval.py:284-329` |
| 13 | `ING-04` | `check_corpus_manifest.py --corpus-dir` fails: 1598 ≠ 1605 | **P0** | exit 1 |
| 14 | `RET-05` | Out-of-domain budget validated on **n=4** | **P0** | corrections note "3/4 → 0/4" |
| 15 | `SEC-05` | Streaming emits an unsafe prefix before the trip is detected; prefix length unbounded | **P1** | `tutor.py:1765-1773` comment |
| 16 | `ING-02` | No quarantine list anywhere | **P1** | `find -iname "*quarantine*"` → none |
| 17 | `ING-03` | No persisted offset map → exact-span highlighting impossible | **P1** | offset machinery exists but unpersisted |
| 18 | `ING-05` | `content_qa.py` blind to 292 cross-source duplicates (per-file `seen_texts`) | **P1** | script read |
| 19 | `INTG-01` | `usable_pages=91` vs 89 `unusable` of 93 for English source — unexplained | **P1** | `quality_report.json` |
| 20 | `META-06` | `_resolve_year()` substitutes 2026 for UNKNOWN edition years in served metadata | **P1** | `nctb_loader.py:163-173` |
| 21 | `ANS-03` | Numeric/maths validation has no call site despite KaTeX rendering | **P1** | `evaluation/output_validation.py` unused |
| 22 | `EVAL-06` | `golden_v3` has 0 reference answers → answer correctness cannot be measured | **P1** | 0/427 |
| 23 | `EVAL-07` | `golden_v2` is retriever-derived → contaminated if used as a benchmark | **P1** | its own `rule` field |
| 24 | `RET-06` | Evidence budget thin for multi-hop/comparison (`top_k=3`, 768 tokens, ~2.5 passages) | **P1** | `context.py:32` + chunk stats |
| 25 | `EMB-01` | No semantic retrieval; hashing lane is orthographic only | **P1** | `embedding.py:28-29` |
| 26 | `OPS-02` | No index artefact, no atomic activation, no rehearsed rollback | **P1** | `admin.py:551-583`; deploy-based rollback |
| 27 | `OPS-04` | Index rebuilt per worker at boot (~26.5 s, in memory) | **P1** | `RAG_INDEX_BUILD_SECONDS` |
| 28 | `OBS-01` | No distributed tracing | **P1** | zero otel hits |
| 29 | `OBS-02` | `_record_trace` swallows exceptions → audit evidence can vanish | **P1** | `tutor.py:1409-1410` |
| 30 | `SEC-06` | Bijoy-conversion failure silently skips an entire screening pass | **P1** | `safety.py:400-401` |
| 31 | `SEC-07` | Rate-limit `_user_key` failure silently degrades to per-IP | **P1** | `middleware.py:124` |
| 32 | `ANS-05` | All safety/gate thresholds hard-coded, not configurable | **P1** | 6 named constants in source |
| 33 | `ENG-03` | No client inventory / answer-schema versioning across web + PWA + Android | **P1** | `ChatMessageOut` lacks `citation_verified` |
| 34 | `ENG-04` | `prompt_sha256` computed and recorded but never verified at runtime | **P2** | grep |
| 35 | `RET-07` | Silent lane degradation via bare `except` in `_retrieve_guarded` | **P2** | `tutor.py:992` |
| 36 | `ENG-05` | `markdownlint`, `deptry`, `check_archive_banners.py`, `gate_g3_local.py` wired nowhere | **P2** | independent verification |
| 37 | `OPS-05` | Nightly retrieval job has never run (corpus gitignored) | **P2** | `retrieval-eval.yml:108-114` |
| 38 | `OPS-06` | No SLO, no measured load baseline; `capacity_plan.md` is a projection | **P2** | doc date 2026-09-08 |
| 39 | `ENG-06` | Docs/DB contradiction: runbook says live is SQLite; two other docs say Postgres | **P2** | three docs disagree |
| 40 | `ENG-07` | Doc drift: `NCTB_DATA_PIPELINE.md:182` says 852 chunks; truth is 847 | **P3** | measured |
| 41 | `RET-08` | Chunker has no overlap; a boundary-split definition is unrecoverable | **P3** | 220/60/450, no overlap |

---

# PART 5 — STEP-BY-STEP ELEVATION PATH TO STUDENT-READY

Staged by dependency. Each step states **objective · why now · changes · acceptance · evidence
required · owner · risk**. Stages are gated: do not start stage *n+1* until *n*'s acceptance is
`PASS`, because later stages consume earlier artefacts as inputs.

> **Sequencing principle.** Stage A must be first: it is the only stage that requires **no human
> decision**, and every later stage's proof depends on it. A system that cannot prove its own
> quality cannot be trusted with a child's question.

---

## STAGE A — Evidence integrity *(no human decision required; ~1–2 weeks)*

**Objective.** Make every benchmark provably describe the corpus it was measured against.

**Why first.** Gaps #1, #2, #12, #13, #35. Until a benchmark is bound to a corpus fingerprint,
no retrieval or generation change can be validated, and the `>2 pp` regression gate protects
nothing that matters.

**Changes.**
1. `evaluation/cli.py` + `evaluation/observability.py` — record in every report:
   `corpus_digest`, `corpus_manifest_sha256`, `embedder_name`, `embedding_dimension`,
   `prompt_version`, `prompt_sha256`, `retrieval_config_version`, `dataset_version`,
   `split`, `model_provider_id`, `generated_at`.
2. `scripts/evaluate_nctb_retrieval.py:284-329` — hash the manifest **after**
   `_update_manifest` rewrites `derived`, so the back-reference can verify.
3. New gate `scripts/check_eval_binding.py` — fail when a report's `corpus_digest` ≠ the corpus
   in use, or when `embedder_name`/`dimension` ≠ the built index.
4. Wire it into `eval-gate.yml` as a blocking step, and into `retrieval-eval.yml`.
5. Unit tests: a report with a wrong digest fails; a correct one passes; a missing field fails
   closed.
6. Record in `docs/rag/architecture.md` what is now bound and what is deliberately not.

**Acceptance.** Running the eval emits a report carrying a corpus digest that
`check_eval_binding.py` accepts, and the checker exits 1 when the digest is perturbed. Exit codes
recorded on the final diff.

**Evidence required.** Command + exit code for both the pass and the perturbed-fail case;
the report artefact path; the checker's source path.

**Owner.** ML Evaluation + GenAI engineering.
**Risk.** Low — additive, no threshold or serving change. **Do not** regenerate
`baseline_v3.json` in this stage; that is a separate reviewed act (project rule: never regenerate
a baseline in the same change as the retrieval change it would mask).

---

## STAGE B — Metadata truthfulness and provenance *(~2–3 weeks)*

**Objective.** Stop asserting scope the corpus cannot support; make each passage traceable.

**Why.** Gaps #3, #5, #9, #10, #17, #20. The product's promise is *curriculum-scoped*; today it is
*level-scoped*, and an unknown edition year is fabricated.

**Changes.**
1. **Remove the fabrication.** `nctb_loader._resolve_year()` must emit `None`/`UNKNOWN` rather
   than the acquisition year. Any consumer that needs an int must handle unknown explicitly.
2. **Stop deriving class from a level label.** Introduce an explicit `class_scope` that is either
   a resolved class list *with its evidence* (a cover statement) or `UNKNOWN` — never a silent
   range. Where the corpus genuinely cannot attribute a class, the scope must say so.
3. **Stable IDs.** Add `book_id`, `edition_id`, `chapter_id`, `section_id`, `subject_id`,
   `source_id` to the chunk contract (`META-05`), with `schema_version` on the artefact.
4. **Persist the offset map** (`ING-03`) so exact-span highlighting becomes possible.
5. **Chunk contract fields** the index must carry: `rights_status`, `review_status`, `language`,
   `content_type`, `normalization_version`, `chunker_version`.
6. **Quarantine** (`ING-02`): a persisted list with reason + source/page identity + resolution
   status; low-confidence pages excluded from the active corpus rather than silently indexed.
7. Migration + compatibility: chunk schema version bump; loader tolerates the previous version
   for one release (expand/migrate/contract).

**Acceptance.** A schema-validated artefact in which (a) no field carries an inferred value,
(b) 100 % of chunks carry a resolvable page span **and** an explicit chapter-or-UNKNOWN,
(c) every identity field is present or explicitly UNKNOWN, (d) a quarantine file exists and is
honoured by the build.

**Evidence required.** Artefact with `schema_version`; a query showing class attribution with
evidence vs `UNKNOWN`; the quarantine file; `check_corpus_manifest.py --corpus-dir` passing;
regenerated manifest with a recorded diff.

**Owner.** Data/PDF-OCR + RAG engineering, with a content reviewer for attribution evidence.
**Risk.** **High** — this changes served scoping. It *must* land only after Stage A, and its
retrieval impact must be measured with the now-bound benchmark. Expect recall to move; that
movement is the finding, not a failure.

---

## STAGE C — Answer validation enforcement *(~2–3 weeks)*

**Objective.** Make it impossible to present an unsupported answer as supported.

**Why.** Gaps #4, #8, #11, #21, #32. This is the difference between a system that *knows* and a
system that *claims*.

**Changes.**
1. **Canonical answer state machine** (`ANS-01`): add `answer_status`, `grounding_status`,
   `citation_status`, `validation_status` to `AskResponse` as **additive** fields; make
   `refused_reason` a `Literal` enum with a compatibility shim for unknown values.
2. **Move thresholds to configuration** (`ANS-05`) with the current values as documented
   defaults, so calibration experiments are config changes.
3. **Measure before enforcing** (`ANS-02`, V3 §7.2.6): instrument a labelled sample and report
   `citation_check` false-accept and false-reject rates **with confidence intervals and strata**.
   Build the label set from Stage E's teacher review; until it exists, use an interim
   teacher-labelled sample of ≥200 answers.
4. **Then** promote to blocking **only for the measured-safe categories** (e.g. block on
   `citation_status = failed` when the verdict is high-confidence), keeping a bounded repair
   attempt with full revalidation (V3 §7.2.10) and a conservative refusal otherwise.
5. **Stop rendering an uncalibrated number** (`ANS-04`): replace the numeric `confidence` in the
   UI with a descriptive label whose policy is documented, or hide it until calibrated.
6. **Wire numeric validation** (`ANS-03`) into the answer path for numeric question types, with
   its known limitations documented.

**Acceptance.** No path can return `answer_status = verified` when any required validator failed
or did not run. False-reject rate on the in-corpus set does not exceed the pre-change rate by
more than the approved margin. Every threshold is in configuration.

**Evidence required.** Before/after false-accept and false-reject rates with intervals and the
sample definition; a test asserting that a failed validator cannot yield `verified`; the config
diff; the client compatibility note (Stage G).

**Owner.** GenAI engineering + QA Automation + education QA.
**Risk.** **High** — over-blocking destroys educational value. This is exactly why the
measurement precedes the enforcement and why Stage E's teacher labels are the real input.

---

## STAGE D — Curriculum scope correctness and content substitution *(owner-gated)*

**Objective.** Ship a corpus that can be honestly called curriculum-scoped.

**Why.** Gaps #3, #7, #10. Stages B gives truthful metadata; this stage supplies content that
*deserves* class-level attribution — i.e. actual student textbooks, or an explicit decision to
remain level-scoped and say so in the product.

**Changes.**
1. **Owner decision (D-1/D-2):** either (a) acquire authorised **student textbooks** per
   class/subject, or (b) keep curriculum documents and change the product's claim to
   level-scoped guidance. V3 §21 forbids claiming textbook coverage otherwise.
2. Record per-source type (`curriculum_document` / `textbook` / `teacher_guide` /
   `question_bank` / `assessment_document` / `reference_material`) and fix the
   `nctb/sources.py:48` docstring contradiction.
3. For any newly acquired source: register rights, checksum, edition, curriculum year, and the
   three permissions — **separately**.
4. Re-run ingestion (Stage B contract) and rebuild the manifest; regenerate the retrieval
   baseline **as its own reviewed change**.

**Acceptance.** Every active source has a stable ID, a source type, a checksum, a known/unknown
edition status, and a rights decision with an evidence reference. No source with unresolved
rights or unknown class enters the student-serving corpus. The coverage matrix is machine-readable.

**Evidence required.** The source registry file; per-source rights evidence references; the
coverage matrix; the regenerated manifest.

**Owner.** Content/rights owner + curriculum owner (human); data engineering implements.
**Risk.** **Critical and non-technical** — this is a rights and product-scope decision, not an
engineering one. Nothing in Stages A–C substitutes for it.

---

## STAGE E — Independent, teacher-reviewed evaluation *(owner-gated; ~4–6 weeks)*

**Objective.** Measure whether answers actually teach correctly.

**Why.** Gaps #22, #23, #14, #1. Today no item has a reference answer, so correctness is
unmeasurable; and the out-of-domain rule rests on n=4.

**Changes.**
1. **Engage a real teacher** (D-4). V3 §3: an agent must not fabricate this.
2. Author `golden-v4`: questions in **real student language**, not copied from source sentences;
   for answerable items a **teacher-approved reference answer**, required concepts, and
   supporting page spans; for unanswerable items the expected behaviour and refusal reason.
3. **Stratify** by class, subject, book/edition, chapter, difficulty, question type, script
   (Bangla / Banglish / English / mixed), answerability and multi-turn status.
4. **Separate author / reviewer / adjudicator** roles; record disagreements and adjudications.
5. **Freeze and hash splits**; never tune thresholds on the held-out test split.
6. **Re-validate the out-of-domain budget** on a proper sample (target ≥200 items), reporting
   per-slice n and Wilson intervals instead of n=4.
7. **Leakage audit** across splits (V3 Phase 4 task 10).
8. Report **teacher-rated correctness, claim support, citation resolution, unsupported-claim
   rate, maths correctness, language quality, refusal accuracy** — each with sample size and
   intervals, with unbalanced slices labelled inconclusive.
9. **Dataset card** updating `docs/rag/golden-set-v3.md`; keep v2/v3 as versioned history (never
   overwrite).

**Acceptance.** Every item has provenance, slice metadata and an adjudicated expected outcome;
the test set has a recorded hash and is independent of tuning data; teacher correctness **is
actually measured** (retrieval-only results cannot satisfy it); thresholds are approved
**before** the held-out run.

**Evidence required.** The dataset file with hash; the reviewer/adjudication log; the metrics
report with intervals; the signed threshold approval.

**Owner.** Education QA (human) + ML evaluation.
**Risk.** Medium — slow and human-bound, but it is the only path to a defensible correctness
number.

---

## STAGE F — Retrieval quality: close the semantic gap *(~3–5 weeks, evidence-gated)*

**Objective.** Improve recall on real student phrasing, or prove it does not need improving.

**Why.** Gaps #25, #24, #38. The shipped lane cannot connect different words for the same idea.

**Changes.**
1. Keep BM25 and the hashing lane as baselines; label the hashing lane explicitly
   **non-semantic**.
2. Define a Bangla/Banglish/English/mixed benchmark with real student queries and hard negatives,
   **on the real corpus, bound per Stage A**.
3. Evaluate candidate multilingual models (e.g. BGE-M3 / multilingual-E5 family) only after
   licence, revision, residency and cost review; compare local vs approved hosted **separately**.
4. Verify query/document prefixes, pooling, truncation, normalisation and dimension — do not
   assume endpoint-compatible models behave identically.
5. Batch embed **offline**; never embed the corpus during worker boot.
6. Bind the vector artefact to corpus digest + model revision + dimension + preprocessing.
7. Compare BM25-only / current hybrid / dense-only / fusion / reranked on the frozen held-out
   set; **shadow mode** before changing user-visible ranking.
8. Define a non-inferiority margin **before** promotion. If nothing clears it, keep the simpler
   lane — that is a legitimate outcome.
9. Separately tune `top_k` / context budget / parent expansion against multi-hop completeness
   (Gap #24, #10) with token measurement and an ablation runner.

**Acceptance.** A reproducible held-out comparison exists; model identity is in the manifest;
corpus↔vector mismatch fails closed; shadow shows no unacceptable regression; privacy/licence/
cost approval recorded for any hosted embedding.

**Evidence required.** The comparison table with intervals; the shadow report; the approval
record; latency/memory/cost measurements.

**Owner.** IR/Search + GenAI engineering + privacy owner.
**Risk.** Medium — and note that `EMBEDDING_MODEL` is already implemented
(`build_embedder` switches to `RemoteEmbedder`), so this is a *decision and measurement* task
more than a build task.

---

## STAGE G — Client contracts and evidence UX *(~1–2 weeks, parallel with A–C)*

**Objective.** Make the contract versioned and the UI honest.

**Why.** Gaps #8, #11, #33. Three clients read `AskResponse`; no inventory exists.

**Changes.**
1. **Client inventory** for web / PWA / Android: which fields each reads (V3 §11.4).
2. **Additive** evolution of `AskResponse`; explicit versioning for anything breaking;
   compatibility tests for the release window.
3. Add `citation_verified` to `ChatMessageOut` so a history-loaded answer shows the same
   verification state as it did live.
4. UI: replace the numeric confidence with a documented descriptive label (Stage C), and make
   `answer_status` visibly distinct — *verified textbook answer* vs *partial* vs *general
   guidance* vs *clarification needed* vs *refused*.
5. Error/refusal states, low-bandwidth, and Bangla glyph shaping re-verified on the new fields.

**Acceptance.** Contract tests pass for all three clients; the answer-status distinction is
visible and screen-reader-announced; no numeric probability is shown.

**Owner.** Backend + frontend/mobile QA.
**Risk.** Low.

---

## STAGE H — Index lifecycle and reliability *(~3–4 weeks, owner-gated architecture)*

**Objective.** Build, verify, activate and roll back corpus/index versions safely.

**Why.** Gaps #26, #27, #28, #29, #37, #38. Today rollout is the only rollback.

**Changes.**
1. Build corpus + index **offline or in a controlled job**; persist an immutable artefact with a
   complete manifest (`corpus_digest`, `source_hashes`, `catalog_version`, `schema_version`,
   `extractor/normalization/chunker_version`, `rights_policy_version`, `embedder name/revision/dim`,
   `vector_normalization`, `BM25_version`, `retrieval_config_version`, `reranker_id`,
   `prompt_version`, `dataset_version`, `evaluation_report_digest`, `build_toolchain`,
   `artifact_checksums`, `approved_status`).
2. **Verify manifest, source hashes, schema compatibility and evaluation status before
   activation**; **activate atomically**; never expose a partially built index.
3. Keep the previous known-good version and **rehearse rollback** (not merely document it).
4. Every answer trace identifies corpus + index + retrieval + prompt + model versions.
5. Move acquisition/OCR/embedding/index building to controlled jobs with idempotency, retry/
   backoff, timeouts, dead-letter and partial-failure recovery.
6. Add distributed tracing across the RAG stages; stop swallowing `_record_trace` failures.
7. Establish **measured** latency/throughput/memory/cost baselines, then propose SLOs for owner
   approval — do not invent targets.

**Acceptance.** Builds and activation are reproducible and atomic; rollback is rehearsed with
evidence; the active artefact identity is checked at activation and monitored; p95/p99 and cost
are tested against an **approved** workload profile.

**Owner.** SRE/operations + architecture.
**Risk.** Medium-high — a startup-path change with availability implications.

---

## STAGE I — Security, privacy and child safety closure *(~2–3 weeks, owner-gated)*

**Objective.** Close the child-safety exposures and the governance gap.

**Why.** Gaps #6, #15, #30, #31.

**Changes.**
1. **DPIA** (D-8) for a children's product processing minors' records — the hard blocker.
2. **Bound the streaming unsafe prefix** (Gap #15): either buffer to sentence boundaries before
   emitting, or cap the emitted prefix and emit a retraction contract the client honours.
3. Stop swallowing the Bijoy-conversion failure (Gap #30) — a skipped screening pass must fail
   loudly or refuse.
4. Make the rate-limit key-derivation failure fail **closed**, not to a weaker scope (Gap #31).
5. Red-team: direct + indirect prompt injection, **corpus injection**, OCR/image-text injection,
   conversation/history poisoning, fake citation IDs, exfiltration — against the **real deployed
   provider path** where authorised.
6. Data classification, access matrix, retention/deletion, provider-transfer review and audit
   for corpus promotion actions.
7. Safeguarding escalation verified with the pinned government helpline values.

**Acceptance.** No unresolved critical privacy, authorization, child-safety or corpus-injection
defect for the pilot scope; consent/retention policies signed by an authorised owner.

**Owner.** Security/privacy/policy owner (human) + AppSec.
**Risk.** High — but this is the gate that decides whether children may use it at all.

---

## STAGE J — Controlled pilot *(final; requires all of A–I)*

**Objective.** Validate one bounded slice, supervised and measurable.

**Changes.** Teacher alpha → limited student pilot with consent and safeguarding approvals;
sampled teacher review across query type / class / script / answer status / validation result;
track wrong-answer reports, citation issues, refusals, retrieval misses, correction rate and
abandonment; track latency, TTFT, error rate, tokens, actual vs estimated cost, per-student
cost; alert on unexpected corpus/index/prompt/model activation; define numerical rollback
triggers; publish a supported-scope matrix and known limitations.

**Acceptance.** V3 §21's per-slice approval table complete for the exact slice. `GO` only then.
`CONDITIONAL GO` may not bypass a source-rights or student-safety blocker.

**Owner.** Product + education + security/privacy + operations, with written sign-off.

---

# PART 6 — WHAT MUST NOT BE CLAIMED TODAY

On this evidence, do not claim: *production-ready*, *enterprise-grade certified*, *100 %
accurate*, *fully NCTB-covered*, *all Classes 6–12 supported*, *textbook-grounded* for any
specific class/book/edition, or *semantically retrieves meaning*. The corpus is curriculum
documentation; its rights status is one sentence; no source has a book-level class; the only
blocking quality gate measures a synthetic sample; and the citation validator does not enforce.

What **can** be claimed, accurately: a modular FastAPI RAG service with hybrid lexical +
orthographic retrieval, RRF fusion, a deterministic reranker, an evidence-sufficiency gate that
refuses rather than fabricates, PII redaction before egress, prompt-injection screening,
per-delta output screening, and 2127 passing tests.

---

# PART 7 — RECOMMENDATION

## 7.1 Verdict

**`NO-GO` for student service.** Not because the engineering is poor — it is the best part of
this system — but because the three things that make a *curriculum-scoped tutor* trustworthy are
absent: the corpus is not textbooks, no source has a class, and the gate that measures quality
does not measure the served corpus. Add the missing DPIA and the answer is unchanged.

## 7.2 The critical path, shortest honest route

```
A Evidence integrity  ──►  B Metadata truthfulness  ──►  C Answer enforcement
   (no decision needed)      (changes scoping)             (after measurement)
        │                          │                             │
        └──────────► D Content & rights (OWNER) ──────────────► E Teacher evaluation (OWNER)
                                                              │
                              F Retrieval quality ◄───────────┘
                                       │
              G Client contracts ──────┤
                                       ▼
                        H Index lifecycle ──► I Security/DPIA (OWNER) ──► J Pilot (OWNER)
```

**Start with Stage A tomorrow.** It needs no human decision, cannot regress anything, and is the
precondition for every other stage being provable. Then run Stage D's decision in parallel,
because it is the longest-lead human item and it is the one no amount of engineering can
substitute for.

## 7.3 Decisions required (unchanged from Phase 0, all human)

`D-1` source rights for storage / indexing / display, separately, and curriculum-vs-textbook ·
`D-2` the supported scope the product may claim · `D-3` the first pilot slice ·
`D-4` a real teacher for the reference-answer set · `D-5` approve the citation-calibration window
· `D-6` embedding model + vector store (licence/cost/residency) · `D-7` index off worker startup ·
`D-8` consent / retention / safeguarding sign-off and the **DPIA**.

## 7.4 What I did not do

No code changed. No threshold, baseline, ratchet or manifest touched. No corpus artefact
regenerated. No dependency added. No migration, deploy, release or tag. No provider call. No
secret read or printed. Nothing committed; `main` remains at `03dfe21` and this review lives on
`feat/rag-v3-phase-0-baseline`.

The single most useful thing you can give me to convert this report into implementation is
**D-5 plus a go-ahead on Stage A** — both are within your authority today and neither requires a
rights or policy decision first.
