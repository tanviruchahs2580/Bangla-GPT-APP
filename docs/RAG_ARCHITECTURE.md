# RAG Architecture — Bangla GPT APP (NCTB subsystem)

> **Read first (2026-10-29):** this document is the *historical* written
> architecture. The verified as-built map is `docs/rag/architecture.md`, and
> the plan is `docs/rag/target-architecture.md`. Several claims below did not
> match the code when audited — they are itemised under "Corrections
> (2026-10-29)" at the end of this file, and the specific paragraphs that
> carried them now point at that section.

Status: **partly verified**. The component map below matches the code for the
retrieval stack (hybrid BM25+vector, query analysis, reranker, gate); the
"Measured baseline" section and the CI-enforcement paragraph did not, and are
corrected below. See the corrections section for the file:line evidence.

## Implemented architecture (hybrid, frequency-aware gate, query understanding)

```text
Student question (Bangla / Banglish / English terms)
        ↓
  POST /tutor/ask  (JWT required)
        ↓
  query normalisation (NFKC + zero-width strip) → safety screen
        ↓
  follow-up resolution (short conversational turn ≤1 content term:
        the previous user turn's content terms are appended, so a
        "আরেকবার বলো" follow-up retrieves the same subject; rich
        questions and deliberate search_query overrides are never
        rewritten — TutorService._conversation_retrieval_query)
        ↓
  Query understanding (retrieval/query_analysis.py)
        │   • content terms: stop-words (BN + romanised + EN) removed
        │   • question-framing words removed (imperatives, class/level context)
        │   • grade-numeric tokens ("৬ষ্ঠ শ্রেণির") treated as framing
        │   • English/Banglish glosses → Bangla curriculum terms (cell → কোষ)
        ↓
  Hybrid retrieval (retrieval/hybrid_index.py)
        │   lane 1  BM25Index.search  (k1=1.5, b=0.75) — curriculum filters
        │            indexes section heading ×2 + chapter + body
        │            query-side lanes: curated synonyms, spelling repair
        │            ("কোশ"→"কোষ"), Banglish romanisation ("kosh"→"কোষ"),
        │            English glossary ("cell"→"কোষ")
        │   lane 2  VectorIndex (hashed char 2–4-gram, dim 384) — phonetic
        │            lane; vector-only candidates gated on shared Bangla
        │            bigrams (anti-hallucination guard)
        │   fuse    reciprocal rank fusion (k=60)
        │   rerank  make_lexical_rerank(term_stats) — IDF-weighted coverage +
        │            matched-term proximity + trigram + lexical-magnitude base
        ↓
  Grounding gate (TutorService._coverage_details)
        │   • IDF-weighted coverage of the question's content terms over
        │     indexed text (heading included), threshold 0.5
        │   • out-of-domain budget: ≥ 2 content terms absent from the corpus
        │     → refuse (cannot verify an answer for absent concepts)
        │     (implemented 2026-10-29; before that only an ALL-terms-absent
        │      question refused — see Corrections #1)
        │   • trigram fuzzy allowed per term (≥ 0.6, e.g. a dropped conjunct)
        │   ├── fail → INSUFFICIENT_EVIDENCE_ANSWER, grounded=false (abstain)
        ↓ pass
  Context assembly (top_k=3; evidence sanitised; question + history
        │   redacted at the egress boundary — metered per PII kind)
        ↓
  LLMProvider.generate(prompt, system=SYSTEM_PROMPT)
        │   provider factory; mock default; real providers behind key
        │   circuit breaker + fallback chain; partial streams discarded
        ↓
  AskResponse{answer, grounded, sources[book/chapter/section/page/score],
              citation_verified (citation-id resolution + per-chunk support,
              see Corrections #4),
              confidence (documented formula)}

Runtime execution notes (2026-10-18 hardening):

* Retrieval is synchronous CPU work, so both `ask` and `ask_stream` run it
  through `asyncio.to_thread` — a 120–250 ms search no longer freezes
  concurrent SSE streams sharing the worker's event loop.
* The reranker memoizes `indexable_text → tokens` per chunk inside
  `make_lexical_rerank` (bounded by the corpus, same lifetime as the BM25
  counters), removing a re-tokenisation of the same candidate sections on
  every turn.
* The hot path is exported to Prometheus: `bgpt_rag_retrieval_latency_seconds`
  (histogram), `bgpt_rag_gate_outcomes_total{gate}` and
  `bgpt_rag_gate_refusals_total{reason}` (every refusal path, safety screen
  included), and `bgpt_rag_citation_checks_total{result}` — a failed
  post-generation citation check is metered AND logged (warn), so ungrounded
  drift under a new provider/corpus is observable in /metrics. The
  `HighRAGRefusalRate` / `RAGCitationCheckFailures` alerts in
  deploy/prometheus/alerts.yml read these series.
* Boot cost is observable too: `bgpt_rag_index_build_seconds{mode}` records
  index construction per worker (plus a `rag_index_built` boot log line) —
  the signal that says when the deferred persistence/pgvector work becomes
  necessary and which mode a slow boot ran.
* Readiness is truthful about this subsystem: `/ready` and `/status` report
  503/degraded when the index is absent, instead of accepting traffic that
  would answer every tutoring turn with 503.
* Streaming and non-streaming share one refusal contract: a refusal (answer
  could not be vetted) carries `citation_verified=None` on both paths.
```

## The retrieval-quality defects this design fixes

Every row below was measured on the live deployment or the real corpus
**before** the rework (2026-10-17 RAG condition review), and re-measured after;
§"Measured baseline" carries the after-numbers.

| Defect (measured) | Fix |
|---|---|
| Section headings were invisible to the lexical lane: the BM25 body never contained "সূচক", "ত্রিকোণমিতিক অনুপাত", "পিথাগোরাস উপপাদ্য" — five golden chapter-title questions pointed at heading-only text | `indexable_text` indexes **section ×2 + chapter + body**; the grounding gate reads the same text, so a heading can satisfy the gate |
| `light_stem` was **inert since introduction**: `_BANGLA_RE` was written unbracketed (`r"\u0980-\u09FF"`), a pattern that matches only the literal "U+0980-dash-U+09FF", never a Bangla word — so no suffix was ever stripped | bracketed pattern `[… U+0980-U+09FF …]`; stemmer verified alive (`ভগ্নাংশটা → ভগ্নাংশ`, `কোষের → কোষ`) |
| The grounding gate measured raw token coverage with no notion of term importance: "সালোকসংশ্লেষণ কী এবং কোথায় ঘটে?" was refused at **0.40** because কোথায়/ঘটে/এবং are function words a textbook cannot contain | gate runs on **content terms** (stop-word planes: Bangla, romanised, English; question-framing plane: imperatives, class/level context; grade-numeric tokens) **weighted by corpus document frequency** `ln(1+N/df)` |
| Misspelled/variant queries ("কোশ", "ভগনংশ", "পাইথাগোরাস"→"পিথাগোরাসের", "ট্রাইকোণমিতি") refused or mis-ranked: no term-level fuzzy match existed at *retrieval* time (the gate's trigram allowance covered gating only) | `CorpusVocabulary.match_spelling` — trigram index for candidates, edit-normalised similarity for ranking, first-grapheme stability rule (excludes meaning-changers like হাইপা/মাপা; abbreviations go through curated expansion: হাইপা → অতিভুজ) |
| Banglish queries (Latin-script Bangla — how a large share of students type) refused outright: "cell ki? cell er bhitore ki thake" abstained | `transliteration.to_roman` (grapheme table, hasanta dropped so clusters concatenate) + `CorpusVocabulary.match_roman` with a **vowel-skeleton second pass** (ভগ্নাংশ is typed bhagnangsho/bhognangsho/bhagnangsh — vowels unstable, consonant frame stable) |
| English terms in code-switched questions ("what is cell?") never reached the Bangla evidence | `ENGLISH_BANGLA_GLOSSARY` (~75 curriculum concepts, class 6–10 + HSC) applied at query time; unmapped tokens expand to nothing — no invented coverage |
| Chapter-title recall@1 **0.2375** and self-sentence recall@1 **0.38** (with recall@5 1.00 — the right chunk was in the candidates but ranked under other sections of the same chapter) | rerank adds **matched-term proximity** (`covered_terms / minimal_token_window`): the chunk whose matches cluster inside one definition sentence outranks scattered matches from neighbouring sections |

## Corpus flow

```text
nctb.gov.bd official pages
  → acquisition (respectful, idempotent, sha256 manifest)
  → raw PDFs (data/nctb/raw, gitignored)
  → pypdf extraction + per-page encoding flags
  → legacy Bijoy→Unicode conversion where detected
  → normalization (NFC, zero-width strip), corruption QC
  → structure-aware chunking (chapter parent → section child, page range)
  → normalized/*.chunks.jsonl (+ quality_report.json)
  → NCTB_CORPUS_DIR wiring → index at app startup
        │
        ├── corpus identity logged + exported (rag_corpus_loaded /
        │   bgpt_rag_index_chunks{corpus}) — an empty or mis-set
        │   NCTB_CORPUS_DIR degrades to the bundled sample corpus (78
        │   chunks, classes 6–10 only) LOUDLY: boot log warning +
        │   metric label, never silently
        └── NCTB text is source material and stays out of git
            (legal: metadata + reports only) — production supplies
            data/nctb through NCTB_CORPUS_DIR
```

## Deliberate deviations from the master target diagram (§6)

| Master component | Status | Justification |
|---|---|---|
| Dense retrieval | partial | the vector lane ships with a deterministic, model-free embedder (`retrieval/embedding.py`: char 2–4-grams, dim 384); a real multilingual embedding model is a staging/infra decision — `EMBEDDING_MODEL` naming one raises `ProviderNotConfigured`. After the 2026-10-17 rework the lexical lanes carry spelling, Banglish and gloss coverage, so the semantic lane is the remaining recall gap, not the only one |
| Hybrid merge | shipped | BM25 + vector lanes fused with reciprocal rank fusion (k=60); the vector lane's candidates are gated on shared Bangla bigrams so hashed-bucket collisions cannot manufacture evidence |
| Reranker | shipped (deterministic) | feature ranker: IDF-weighted content coverage + matched-term proximity + trigram, weights documented in-source; measured chapter-title recall@1 0.2375 → **1.00** on the real corpus. A cross-encoder can replace just this stage |
| Graph retrieval | partial | prerequisite edges are curated pedagogy data and drive the weakness/KG features; graph facts do not enter the retrieval ranking (never hallucinate relations) |
| Query understanding | shipped (lexical) | content-term extraction, framing removal, grade-numeric rule, glossary + spelling + romanisation lanes; an embedding-based query rewriter remains pending until a model is staged |

Per master §76 (no overengineering): what ships is measured and documented
rather than padded with unbenchmarked model-based stages. The staged inputs
that require human/infra decisions remain exactly two: the embedding model +
vector store, and an LLM faithfulness judge (see evaluation/metrics.py,
`mode="local_overlap"` until then).

## Measured baseline (see the corrections section before quoting these)

The committed `data/nctb/retrieval_eval.json` is the record of truth for
these numbers: this table quotes it verbatim. **It was produced by a corpus
build that is not reproducible from the current raw files** (committed
artifact: 2,508 chunks; a rebuild of the raw tree in `.qa-work` yields 2,599
chunks and different family-B/corpus numbers — see Corrections #2). Any
retrieval change regenerates the artifact locally, with the diff reviewed as
retrieval evidence.

| Metric | Before rework | After rework (committed artifact) |
|---|---|---|
| Index build | 0.36 s (lexical only) | 26.5 s (lexical + vector + vocabulary) |
| Family A self-sentence recall@1 / @5 (n=100) | 0.38 / 1.00 | **0.98 / 0.98** |
| Family A MRR | — (not computed) | 0.61 |
| Family B chapter-title recall@1 / @5 (n=80) | 0.225 / 0.525 | **1.00 / 1.00** |
| Family B MRR | — (not computed) | 1.00 |
| Adversarial refusal rate | 1.00 | **1.00** |
| Search latency p50 / p95 (hybrid, real corpus) | — | 120 ms / 253 ms |

Golden-set regression discipline (corrected wording): the 634-item golden
suite and the 23-item red-team set run hermetically under the mock provider
via the `eval-gate.yml` workflow (steps: `python -m bangla_gpt_api.evaluation.cli`,
`python scripts/evaluate_golden.py`, `python -m bangla_gpt_api.evaluation.cli
--redteam`), and `python -m bangla_gpt_api.evaluation.cli --gate` runs all of
them plus the retrieval hit@k floor in one command. Every metric is compared
against the committed baseline (`eval/baseline_v2.json`); any drop > 2
percentage points fails. The earlier text claimed a `ci.yml` golden-eval job
and a 16-item red-team set — neither existed (Corrections #5).

The sample-corpus robustness matrix (`tests/test_bangla_matrix.py`) was
re-measured per its own contract: standard, colloquial, mixed, Banglish,
numeral-framed and paraphrase phrasings of "ভগ্নাংশ কী?" now ground **with
verified citations** from the served section; out-of-domain questions still
refuse. That test file records which expectation flipped and why.

## Known open items (documented, not padded over)

1. **Semantic recall**: the vector lane is still the deterministic phonetic
   lane. A real multilingual embedding model + vector store is the staged
   infra decision (factory change in `retrieval/embedding.py`).
2. **Chunking**: structure-aware section chunking with a word budget
   (220 target / 60 min / 400 max) and chapter-parent boundaries — the earlier
   text here claimed "fixed ~700-char section chunking", which the code does
   not do (`nctb/chunking.py`). Changing the budget invalidates every
   committed eval artifact; it must be its own corpus revision with
   regenerated baselines.
3. **Faithfulness judge**: `mode="local_overlap"` until an LLM provider is
   configured; `_JUDGE_INSTRUCTION` and the scoring contract are ready.
4. **Index lifecycle**: full in-memory rebuild at boot (~26 s on the real
   corpus, hybrid, per worker). Fine at this scale; pgvector + incremental
   updates remain the scaling path (explicitly deferred as infra).
5. **Class coverage of the deployed corpus**: production serves whatever
   `NCTB_CORPUS_DIR` contains; the bundled sample covers classes 6–10 only.
   The boot identity log/metric makes the served corpus observable; supplying
   the real corpus to production is a deployment + licensing step
   (docs/operations/PRODUCTION_DEPLOYMENT.md, DATA-01/LEGAL-02).
6. **Follow-up resolution scope**: the conversational rewrite covers the
   short-follow-up case (≤1 content term → prior user turn's terms appended).
   Full coreference resolution (pronoun substitution mid-sentence, multi-turn
   embedding rewriter) remains an embedding-model-staged decision.
7. **Class attribution of the secondary sources**: the five secondary
   curriculum documents on disk have legacy-font-garbled covers, so their
   class set is the declared level range (6–10), logged as `level-range` at
   load; the four HSC physics/chemistry/biology/higher-mathematics books
   carry a real cover statement ("একাদশ ও দ্বাদশ শ্রেণি") and are detected.
   A source with no class signal at all is refused, not expanded
   (`data/nctb_loader.resolve_class_targets`).

## Corrections (2026-10-29)

Verified against the code during the enterprise QA audit
(`.qa-work/audit/RAG/report.md`) and the fixes landed on this branch. Each row
names the claim that did not hold and the measurement or file that shows the
truth.

1. **"Out-of-domain budget: ≥ 2 content terms absent → refuse"** was documented
   but not implemented: `TutorService._coverage_details` kept only terms with
   `df > 0` and refused only when EVERY content term was absent. Measured
   (`.qa-work/evidence/E-RAG-15`): 3 of the 4 family-C questions were answered
   with unrelated citations at coverage 1.0 (e.g. ক্রিকেট বিশ্বকাপ ফাইনালে কে
   জিতেছিল? grounded on কে, df=183). Fixed: the budget is a named constant
   (`OUT_OF_CORPUS_ABSENT_BUDGET = 2`) applied before the `df > 0` filter;
   re-measured false-answer 3/4 → 0/4 with no change to the in-corpus
   false-refusal rate (5/624, pre-existing).
2. **"Measured baseline … regenerated on this commit against the committed
   retrieval_eval.json"** did not reproduce: the committed artifact says 2,508
   chunks with family-B MRR 1.00, while a rebuild of the raw tree in
   `.qa-work` yields 2,599 chunks with family-B recall@1 0.675 and MRR 1.275
   (`.qa-work/evidence/E-RAG-20/retrieval_eval_run.log`). The MRR above 1.0
   was a defect — `scripts/evaluate_nctb_retrieval.py:133` reciprocated a
   value that the `mrr()` helper reciprocates again; family A had already
   been fixed for exactly this and family B was missed. Fixed (ranks are fed
   to `mrr()`; the report asserts every metric is a fraction); the corrected
   run on the same corpus build gives family-B MRR 0.8052 and family-C
   refusal 1.00.
3. **Class detection**: `nctb/normalize.detect_class_level` returned None for
   every source of the corpus on disk, and `data/nctb_loader` then replicated
   each chunk across the source's whole declared level range (423 chunks per
   secondary class, equal by construction). What the old detector rejected as
   "ambiguous" was the real book-level statement — the HSC covers read
   "পদার্থবিদ্যা একাদশ ও দ্বাদশ শ্রেণি". Fixed: `detect_class_levels` reads
   range cover statements, the loader resolves cover statement → declared
   level range (explicit flag) → refuse, and never invents a class.
4. **`citation_verified` was "stem coverage ≥ 0.25 vs evidence"**: a
   whole-answer overlap over all retrieved chunks concatenated, which a
   fabricated sentence riding on shared stems passed (probe: verified True for
   "কোষ হলো … ক্লোরোপ্লাস্ট থাকে যা সালোকসংশ্লেষণ করে" against কোষ evidence).
   Now `services/safety.citation_check`: citation markers must resolve to a
   retrieved chunk id (or index) and every declarative sentence must be
   supported by ONE chunk over its content terms. The response policy stays
   warn-level: the verdict is honest (`citation_verified`) and metered, but an
   unsupported answer is not yet discarded or regenerated.
5. **"the 634-item golden suite + 16-item red-team set run … as steps of the
   `ci.yml` golden-eval job"** was false in both halves: `ci.yml` had no
   golden-eval job and the red-team set is 23 items. The red-team and the
   golden retrieval gates now run in `eval-gate.yml`, and
   `python -m bangla_gpt_api.evaluation.cli --gate` runs golden + hit@k floor
   + red-team as one command.
6. **"fixed ~700-char section chunking"** in the open items: the chunker is
   structure-aware with a word budget (220/60/400) — corrected in place.
7. **Tutor answers were not output-screened** while teacher documents were:
   the tutor now runs the same `screen_question` on the composed answer (and
   on the accumulated stream buffer) and refuses with reason `output_screen`.
8. **Text inside an uploaded image was never declared untrusted**: the prompt
   now declares the vision part inside `<attached_image>` delimiters and
   `SYSTEM_PROMPT` carries a matching data-only rule.

