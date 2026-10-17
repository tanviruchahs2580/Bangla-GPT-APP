# RAG Architecture — Bangla GPT APP (NCTB subsystem)

Status: **verified as implemented** (2026-10-17, after the retrieval-quality
rework). Every component below maps to code in `apps/api/src/bangla_gpt_api/`;
the measured numbers in "Measured baseline" were regenerated on this commit
against the committed `data/nctb/retrieval_eval.json` (the script is
`apps/api/scripts/evaluate_nctb_retrieval.py`, run locally over the full 2,508-chunk
corpus — see "Corpus flow" for why the corpus text itself is not in git).

## Implemented architecture (hybrid, frequency-aware gate, query understanding)

```text
Student question (Bangla / Banglish / English terms)
        ↓
  POST /tutor/ask  (JWT required)
        ↓
  query normalisation (NFKC + zero-width strip) → safety screen
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
              citation_verified (stem coverage ≥ 0.25 vs evidence),
              confidence (documented formula)}
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

## Measured baseline (real corpus, 2,508 chunks, this commit)

| Metric | Before rework | After rework |
|---|---|---|
| Index build | 0.36 s (lexical only) | 23.9 s (lexical + vector + vocabulary) |
| Family A self-sentence recall@1 / @5 (n=100) | 0.38 / 1.00 | **0.98 / 0.98** |
| Family A MRR | — (not computed) | 0.61 |
| Family B chapter-title recall@1 / @5 (n=80) | 0.225 / 0.525 | **1.00 / 1.00** |
| Family B MRR | — (not computed) | 1.00 |
| Adversarial refusal rate | 1.00 | **1.00** |
| Search latency p50 / p95 (hybrid, real corpus) | — | 127 ms / 224 ms |

Golden-set regression discipline (unchanged contract, still enforced in CI):
the 634-item golden suite + 16-item red-team set run through the hermetic mock
provider; every metric is compared against the committed baseline
(`eval/baseline_v2.json`); any drop > 2 percentage points fails. After the
rework: grounded_rate 1.00, faithfulness 0.8549 (up from 0.8547), grammar
0.9881, red-team refusal 16/16, zero system-prompt leakage.

The sample-corpus robustness matrix (`tests/test_bangla_matrix.py`) was
re-measured per its own contract: standard, colloquial, mixed, Banglish,
numeral-framed and paraphrase phrasings of "ভগ্নাংশ কী?" now ground **with
verified citations** from the served section; out-of-domain questions still
refuse. That test file records which expectation flipped and why.

## Known open items (documented, not padded over)

1. **Semantic recall**: the vector lane is still the deterministic phonetic
   lane. A real multilingual embedding model + vector store is the staged
   infra decision (factory change in `retrieval/embedding.py`).
2. **Chunking**: fixed ~700-char section chunking, no overlap, character
   units. Changing it invalidates every committed eval artifact; it must be
   its own corpus revision with regenerated baselines.
3. **Faithfulness judge**: `mode="local_overlap"` until an LLM provider is
   configured; `_JUDGE_INSTRUCTION` and the scoring contract are ready.
4. **Index lifecycle**: full in-memory rebuild at boot (~24 s on the real
   corpus, hybrid). Fine at this scale; pgvector + incremental updates remain
   the scaling path (explicitly deferred as infra).
5. **Class coverage of the deployed corpus**: production serves whatever
   `NCTB_CORPUS_DIR` contains; the bundled sample covers classes 6–10 only.
   The boot identity log/metric makes the served corpus observable; supplying
   the real corpus to production is a deployment + licensing step
   (docs/operations/PRODUCTION_DEPLOYMENT.md, DATA-01/LEGAL-02).
