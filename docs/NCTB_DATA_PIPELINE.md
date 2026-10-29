# NCTB Data Pipeline

Status: pipeline verified end-to-end; the derived artifacts committed under
`data/nctb/` are reproducible from the raw PDFs, the recorded tool version and
the recorded pipeline fingerprint (§7). Provenance artifacts are committed;
copyrighted content is not.

## 0. What is tracked and what is rebuilt

| Path | Tracked? | Role |
|---|---|---|
| `data/nctb/raw/*.pdf` | no (gitignored) | official NCTB downloads, verified by sha256 |
| `data/nctb/extracted/*.pages.json` | no | per-page extraction output |
| `data/nctb/normalized/*.chunks.jsonl` | no | retrieval chunks with provenance and source spans |
| `data/nctb/manifests/acquisition_manifest.jsonl` | yes | provenance ledger (URLs, hashes, dates, edition) |
| `data/nctb/manifests/corpus_manifest.json` | yes | derived-artifact manifest: tool fingerprint, source hashes, artifact digests, totals |
| `data/nctb/quality_report.json` | yes | per-source extraction/chunking QC (includes the cross-source duplicate section) |
| `data/nctb/retrieval_eval.json` | yes | retrieval metrics of the built corpus, with per-item ranks |
| `data/nctb/retrieval_ablation.json` | yes | the four-configuration retrieval ablation on this corpus |

The PDFs and the extracted/normalized text stay out of the repository
(licence); the reports and the two manifests are the tracked record of what
the pipeline produced.

## 1. Official sources (verified)

| Page | URL | Artifacts |
|---|---|---|
| Landing (master primary) | `https://nctb.gov.bd/pages/static-pages/695b98afc4774958d7b7044c` | 6 links: প্রবিধানমালা, প্রাক-প্রাথমিক ২০১১, প্রাথমিক ২০১১, **মাধ্যমিক**, **উচ্চ মাধ্যমিক**, প্রাথমিক শিক্ষাক্রম মূল্যায়ন |
| Secondary listing | `https://nctb.gov.bd/pages/files/6922db5b933eb65569e09a2c` — heading "মাধ্যমিক স্তরের শিক্ষাক্রম(প্রকাশকাল -২০১২)" | 16 subject PDFs (classes 6–10 range) |
| Higher-secondary listing | `https://nctb.gov.bd/pages/files/6922dbc6933eb65569e0c702` — heading "উচ্চ মাধ্যমিক স্তরের শিক্ষাক্রম" | 32 subject PDFs (classes 11–12 range) |

All PDFs are hosted on the ministry bucket `objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/.../office-nctb/2024/12/`.
Full inventory with provenance: `apps/api/src/bangla_gpt_api/nctb/sources.py`.

**Important scope note:** these official artifacts are the national
*curriculum* documents (শিক্ষাক্রম) — learning objectives, chapter layouts,
assessment design per subject/class. Student *textbooks* (পাঠ্যপুস্তক) are
not exposed as static downloads on this site section and remain an explicit
data gap; no third-party copies were substituted.

### Edition and year statement

The secondary listing heading prints the edition `প্রকাশকাল -২০১২`; its five
sources therefore carry `curriculum_year = "2012"` and `edition =
"প্রকাশকাল ২০১২"` in the acquisition manifest. The higher-secondary listing
prints **no year**: those four sources stay `curriculum_year = "UNKNOWN"`,
`edition = "UNKNOWN"` — the pipeline never borrows the secondary year for
them. Chunk metadata requires an integer year
(`CurriculumMeta.curriculum_year`), so the loader substitutes the *acquisition
year* (2026) as a versioning bucket for the UNKNOWN rows, documented in
`data/nctb_loader._resolve_year`; that value is a bucket, not a publication
year, and both the acquisition ledger and the corpus manifest keep the
truthful UNKNOWN.

## 2. Acquisition (idempotent, respectful)

`nctb/acquisition.py` + `apps/api/scripts/build_nctb_corpus.py`

- politeness delay between requests (default 2 s), identifying User-Agent
- retries with exponential backoff; content-type must be `application/pdf`
- sha256 + size recorded per artifact; hash-duplicate detection
- resume: manifest-checked skip of already-acquired artifacts
- append-only JSONL ledger: `data/nctb/manifests/acquisition_manifest.jsonl`
  (committed — facts only: URLs, hashes, timestamps, edition headings). The
  corpus manifest records the ledger's digest, so the derived artifacts can be
  tied to the exact provenance record they were built from.

Verified acquisition run (subset `ssc-science` + `hsc-science`, 9 artifacts):

| Subject (official link title) | Level | Size | sha256 prefix |
|---|---|---|---|
| বাংলা | secondary | ~1.1 MB | see manifest |
| ইংরেজি | secondary | ~0.7 MB | " |
| গণিত ও উচ্চতর গণিত | secondary | ~0.8 MB | " |
| বিজ্ঞান শাখার বিষয়সমূহ | secondary | ~1.5 MB | " |
| আইসিটি ও ক্যারিয়ার এডুকেশন | secondary | ~0.9 MB | " |
| পদার্থবিদ্যা | hsc | ~0.5 MB | " |
| রসায়ন | hsc | ~0.5 MB | " |
| জীববিজ্ঞান | hsc | ~0.5 MB | " |
| উচ্চতর গণিত | hsc | ~0.5 MB | " |

## 3. Extraction & the Bijoy discovery

pypdf extracts cleanly (98%+ pages non-empty), but every verified artifact
uses **legacy Bijoy/SutonnyMJ ANSI font encoding**, not Unicode:

```text
raw extraction:    "RvZxq wkÿvµg 2012"
converted (UTF-8): "জাতীয় শিক্ষাক্রম ২০১২"
```

`nctb/bijoy.py` detects legacy encoding via signature tokens and converts
with `bijoy2unicode` plus targeted post-fixes (`ÿ→ক্ষ`) validated on real
pages. Per-page robustness: one failing page never kills a book (flagged
`unusable` instead). Known residual artifacts (documented, not hidden):
rare conjunct reorderings such as `কার্যক্রম` surfacing as `কাযর্ক্রম`;
affected content stays retrievable at reduced lexical precision.

The extractor version is recorded per source (`extractor`, currently
`pypdf-6.21.2`) and in the corpus manifest, because `total_chars_on_usable`
drifted between pypdf releases on the same PDF (108 827 committed vs 108 822
re-measured, F-080): a report without the version cannot be compared across
environments.

## 4. Quality control (`quality_report.json`, committed)

Per source: total/empty/garbage/usable pages, usable ratio, Bangla ratio on
usable text, page-encoding histogram, chunk count, chapter coverage, the
extractor version, and the number of chunks whose text is shared with another
source. The table below is a snapshot of the committed report; it is derived,
not maintained by hand — re-read the JSON before trusting a number:

```bash
# from the repository root
python -c "import json; r=json.load(open('data/nctb/quality_report.json', encoding='utf-8')); [print(k, v['usable_pages'], '/', v['total_pages'], v['bangla_char_ratio_on_usable'], v['chunks'], v.get('chapter_coverage')) for k, v in r.items() if k != '_cross_source']"
```

| Source | usable pages | Bangla ratio (post-conversion) | chunks | chapter coverage |
|---|---|---|---|---|
| বাংলা | 91/93 | 1.00 | 131 | see report |
| ইংরেজি (English book) | 91/93 | 0.04 (correctly low) | 122 | see report |
| গণিত ও উচ্চতর গণিত | 143/146 | 1.00 | 89 | see report |
| বিজ্ঞান শাখার বিষয়সমূহ | 239/241 | 1.00 | 83 | see report |
| আইসিটি ও ক্যারিয়ার এডুকেশন | 109/111 | 1.00 | 86 | see report |
| পদার্থবিদ্যা | 52/52 | 0.84 | 78 | see report |
| রসায়ন | 45/45 | 0.90 | 67 | see report |
| জীববিজ্ঞান | 46/46 | 0.83 | 69 | see report |
| উচ্চতর গণিত | 52/52 | 0.73 | 80 | see report |

Indexing gate: only pages that pass the corruption heuristic are chunked —
`PageText.usable` (non-empty text that `looks_like_garbage()` does not flag,
`nctb/extract.py`) is the filter `nctb/chunking.py` applies before a page
becomes chunks, so unusable or mis-extracted pages never reach the tutor
index. The report keeps a row for every page either way; nothing is silently
dropped.

### Cross-source duplicates (`_cross_source`)

`duplicates_removed` on a source row is a *per-file* number: dedupe inside
`nctb/chunking.dedupe_chunks` only sees one book, so a curriculum preamble
reprinted in every volume never appeared there. The build writes a
corpus-level section as well (`_cross_source`: total chunks, unique texts,
duplicate chunks/texts, the cross-source groups and their sources, and
per-source shared counts) and stamps every source row with
`shared_text_chunks_with_other_sources`. The duplicates are removed where
they would otherwise multiply: at index build
(`data/nctb_loader.load_nctb_corpus` deduplicates on (normalized-text hash,
class level), F-012), so the same passage is still served to every class
level that needs it but is paid for once per level. Numbers for this corpus
are in the committed report and in `retrieval_eval.json`
(`dedupe_cross_source`, `corpus_chunks`).

### Chapter coverage

`chunks_with_chapter` / `chapter_coverage` are recorded per source because
chapter metadata is *not* uniformly available: the two curriculum documents
(বাংলা, ইংরেজি) print numbered sections ("১. সূচনা"), not chapter headings, so
they carry none, and the build prints a warning naming them. Chapter-scoped
filters and metrics are therefore blind on those two documents; the other
seven books carry chapter parents on part of their chunks (front matter,
tables of contents and exercise sections belong to no single chapter). The
measured per-source coverage is in the report's `chapter_coverage` field.

## 5. Chunking & class metadata

- Structure-aware: chapter-parent → section-child units, page ranges kept;
  heading patterns cover both textbook ("অধ্যায়: X") and curriculum
  ("প্রথম অধ্যায়: X") formats; running-header gluing is un-wound before
  line matching.
- **Sizes are counted in the tokens of the tokenizer the index actually uses**
  (`retrieval.hybrid.tokenize`, F-134), not whitespace words. The budgets are
  constants in `nctb/chunking.py` (target 220, minimum 60, maximum 450
  tokens, line buffer flushed at target + 120), anchored on the measured
  distribution of this corpus; re-measure with
  `python scripts/evaluate_nctb_retrieval.py <corpus> --chunk-stats`.
- **Every chunk carries a span map back to the extracted page text**
  (`source_spans`: ordered runs of `text[text_start:text_end]` ↔
  `page[page_start:page_end]`, F-133). Runs merge only while text and source
  characters advance 1:1, so each run is individually round-trip exact
  (`normalize(page_slice) == normalize(text_slice)`), while a collapsed
  whitespace run and a compatibility expansion stay single runs.
  `original_text` is the exact source slice the runs cover, not a truncated
  guess.
- **Parent-child expansion does not exist**: `parent_id` links every chunk to
  its chapter unit and is stored, but retrieval returns child chunks only.
  Expanding a hit to its chapter was left off because nothing in this
  repository can measure the generation-level effect: the golden suite runs
  on the bundled sample corpus, not on NCTB, and has no live LLM judge. The
  ablation that is runnable (lexical / vector / hybrid / hybrid+rerank) is
  recorded in `data/nctb/retrieval_ablation.json` and
  `docs/rag/architecture.md` §6.
- Class level is DERIVED from front matter only when unambiguous; these
  compilation volumes mention multiple classes, so detection correctly
  returns UNKNOWN for all nine covers and the loader falls back to the
  declared level range (secondary→6–10, hsc→11–12), logged as `level-range`.
  Nothing is invented (master §75).

## 6. Reproducing from clean environment

```bash
git clone https://github.com/tanviruchahs2580/Bangla-GPT-APP.git
cd Bangla-GPT-APP/apps/api
python -m venv .venv
# Linux / macOS:
.venv/bin/pip install --require-hashes -r constraints.txt
.venv/bin/pip install --no-deps -e ".[dev]"
.venv/bin/python scripts/build_nctb_corpus.py --data-dir ../../data/nctb --subset all
.venv/bin/python scripts/evaluate_nctb_retrieval.py ../../data/nctb
.venv/bin/python scripts/check_corpus_manifest.py --data-dir ../../data/nctb
# Windows PowerShell: .venv\Scripts\pip / .venv\Scripts\python with the same arguments
# then run the API with NCTB_CORPUS_DIR=../../data/nctb
```

Acquisition re-runs hit only official URLs and skip already-hashed files. A
second build over the same raw files produces byte-identical chunk files: the
manifest's per-source `normalized_sha256` values are the reproducibility
claim, and the double-build check is a plain digest comparison
(`--rebuild-dir`).

## 7. The corpus manifest and the build/swap procedure

`manifests/corpus_manifest.json` is the derived-artifact record:

| Field | Meaning |
|---|---|
| `pipeline.code_fingerprint` | sha256 over the artifact-shaping modules (`nctb/{bijoy,chunking,corpus,extract,normalize}.py`, `data/nctb_loader.py`) |
| `pipeline.extractor`, `pipeline.python`, `pipeline.chunker` | pypdf version, interpreter, and the token budgets/normalizer the build used |
| `edition.*` | the edition/year policy of §1 (including the HSC UNKNOWN) |
| `acquisition_manifest.sha256` | digest of the provenance ledger the build read |
| `sources[]` | per source: raw content hash, size, curated years, extractor, chunk counts and chapter coverage, `extracted_sha256`, `normalized_sha256` |
| `totals`, `cross_source` | corpus totals and the duplicate statistics of §4 |
| `derived` | digests of `quality_report.json` and `retrieval_eval.json`, the served index chunk count and id hash, and the embedder the retrieval numbers were measured with |

Build and swap procedure:

1. `build_nctb_corpus.py` (acquires if needed, processes, writes the report
   and the manifest with `derived` still empty);
2. `evaluate_nctb_retrieval.py` (measures, writes `retrieval_eval.json`, fills
   `derived`);
3. `check_corpus_manifest.py --data-dir ../../data/nctb --rebuild-dir <tmp>`
   (compares the tracked metadata with a fresh build; exit 1 on any drift);
4. copy the build's `extracted/`, `normalized/`, `quality_report.json`,
   `retrieval_eval.json` and `manifests/corpus_manifest.json` over the corpus
   directory a deployment mounts, then restart the API workers (the index is
   rebuilt per worker at boot);
5. `check_corpus_manifest.py --data-dir ../../data/nctb --corpus-dir <mount>`
   verifies that the mounted corpus is exactly the manifest's build. The same
   comparison runs inside `load_nctb_corpus` at boot: a mismatch is logged at
   ERROR naming each difference (a missing manifest is a warning), and the
   embedder recorded in `derived.embedder` is enforced — a corpus measured
   with one embedder refuses to start under another
   (`retrieval/embedding.build_embedder`).

Rollback is the same procedure with the previous manifest and corpus
directory: the chunk files and both reports are the whole state.
