# NCTB Data Pipeline

Status: verified end-to-end on 2026-08-25 against the official source named
in the master prompt. Provenance artifacts are committed; copyrighted
content is not.

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

## 2. Acquisition (idempotent, respectful)

`nctb/acquisition.py` + `apps/api/scripts/build_nctb_corpus.py`

- politeness delay between requests (default 2 s), identifying User-Agent
- retries with exponential backoff; content-type must be `application/pdf`
- sha256 + size recorded per artifact; hash-duplicate detection
- resume: manifest-checked skip of already-acquired artifacts
- append-only JSONL ledger: `data/nctb/manifests/acquisition_manifest.jsonl`
  (committed — facts only: URLs, hashes, timestamps, edition headings)

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

## 3b. Extraction-fidelity audit (A2-02, 2026-10-20)

`apps/api/scripts/extraction_audit.py` draws a deterministic stratified sample
of source pages — strata are subject × class × **content_type** (the served
chunk classes, read from the chunk artifacts over each page range) — reads
every sampled page twice (the pipeline artifact `extracted/*.pages.json` and
the raw PDF through an independent reader) and writes the error-class table
to `data/nctb/extraction_audit.json`. Reproduce:

```bash
# from apps/api
python scripts/extraction_audit.py --data-dir ../../data/nctb \
    --out ../../data/nctb/extraction_audit.json --sample-size 40
```

Run of 2026-10-20 (seed 20261020): **40 pages sampled from a frame of 868
usable pages, 14 strata, all 9 sources and 9 subjects** (explanation 26,
exercise 12, table 2). Every row below is **machine-classified**; the human
read of the sample is the remaining owner step, so no row claims more than a
pattern count.

| Error class | Pages affected | Rate | Example page refs |
|---|---|---|---|
| legacy-encoding gibberish (served text still legacy) | 0 / 40 | 0.0% | — |
| page unusable although the source carries text | 0 / 40 | 0.0% | — |
| dropped formula/table (math chars lost, column geometry lost) | 0 / 40 | 0.0% | — |
| header/footer noise (running header retained in the text) | 36 / 40 | 90.0% | `nctb-secondary-ca0d6bd886b7`:p82, `nctb-hsc-28d03c592c2c`:p50, `nctb-secondary-afda21d8556d`:p86 |
| broken conjuncts (documented reorder artifacts, curated list) | 14 / 40 | 35.0% | `nctb-secondary-ca0d6bd886b7`:p82, `nctb-hsc-28d03c592c2c`:p50, `nctb-secondary-3ce5065b7a32`:p57 |
| vowel-sign misorder (`্ি`-shaped, no Bangla word has it) | 0 / 40 | 0.0% | — |
| hyphenation (source line-break hyphen kept in a word) | 4 / 40 | 10.0% | `nctb-hsc-a513203336f6`:p30, `nctb-secondary-e39c58d35764`:p131 |
| ink without text (rendered page carries content the text does not) | 0 / 40 | — | — |

Reading it honestly:

- **What is clean:** no sampled page serves legacy gibberish or an unusable
  artifact, and no page lost formula/table content relative to the source
  (the two engines read the same text layer, so this measures the conversion
  and filtering steps, not viewer differences).
- **What is not clean:** the running header/footer (volume title + page
  number) stays inside the page text — 90% of sampled pages start with it —
  and it is indexed with the content. Documented conjunct-reorder artifacts
  survive on 35% of sampled pages (the curated list under-counts: the class is
  real but only enumerated patterns are counted). Line-break hyphenation
  survives on 10%.
- **Independent reader:** `pypdfium2` (PDFium). **pymupdf is not installed on
  this host**, so no MuPDF claim is made; both engines read the same embedded
  text layer, which is why the raw-PDF side of the sample is legacy Bijoy
  (the pipeline's conversion is a *gain* over the source layer, visible in the
  side-by-side dump `R5-wsa-a2-02-manual-spotcheck.txt` in the audit evidence
  bundle).
- **Known artifact families the machine table under-counts** (seen in the
  spot-check, from the same conversion): `শ্র`→`স্ন` substitutions
  ("বিশ্লেষণ" → "বিশেস্নষণ"), `র্থ`→`থর্` swaps ("শিক্ষার্থীদের" →
  "শিক্ষাথীের্দর") and vowel-length substitutions ("অণুজীব" → "অণূজীব"). The
  served text keeps them at reduced lexical precision; the machine classes
  above count only the enumerated shapes, so treat 35% as a lower bound.

## 4. Quality control (`quality_report.json`, committed)

Per source: total/empty/garbage/usable pages, usable ratio, Bangla ratio on
usable text, page-encoding histogram, chunk count. The table below is a
snapshot of the committed report (built 2026-10-05); it is derived, not
maintained by hand — re-read it from the JSON before trusting a number:

```bash
# from the repository root
python -c "import json; r=json.load(open('data/nctb/quality_report.json', encoding='utf-8')); [print(v['subject_bn'], f\"{v['usable_pages']}/{v['total_pages']}\", v['bangla_char_ratio_on_usable'], v['chunks']) for v in r.values()]"
```

The table is deliberately not repeated here as numbers: the report is the
source of truth and its `chunks`/`built_at`/`content_version` keys change
whenever the pipeline changes. Read it with the command above. Each row also
carries `curriculum_year` and `edition` from the acquisition ledger (the
loader serves the published edition year, e.g. 2012 for the secondary set,
instead of the build year for sources whose edition is published) and a
per-document `rights` block (`official-public-download`, `redistribution:
not-granted-in-writing`) — see §7.

Indexing gate: only pages that pass the corruption heuristic are chunked —
`PageText.usable` (non-empty text that `looks_like_garbage()` does not flag,
`nctb/extract.py`) is the filter `nctb/chunking.py` applies before a page
becomes chunks. Pages that fail are reported per page; nothing is silently
dropped. Blocks below `MIN_WORDS` are merged into a neighbouring chunk rather
than dropped, and the count (`short_blocks_merged`) is on the report.

**Per-chunk content QA gate (build time).** `nctb/content_qa.py` checks every
chunk for `not_nfc`, `zero_width`, `math_mojibake`, `replacement_char`,
`pua_char`, `legacy_bijoy` and — for sources the report rates Bangla
(`bangla_char_ratio_on_usable ≥ 0.5`) — `latin_residue`, an ASCII-Latin-
dominant passage that is an unconverted legacy line rather than English
prose. `build_nctb_corpus.py` writes `<data-dir>/qa_report.json` and exits
non-zero when any source exceeds the `DEFAULT_FLAGGED_THRESHOLD` of 2%
flagged chunks. At load time `apps/api/src/bangla_gpt_api/data/nctb_loader.py` strips private-use glyph
residue to spaces, drops chunks that are detectably legacy (signature or
latin-residue verdict) and deduplicates identical `(class_level, text)`
pairs, each with a warning/log count — QA-flagged artifacts reach neither the
index nor a served answer.

Two more build outputs belong to the corpus:

- `<data-dir>/coverage_report.json` — class × subject × chapter counts and
  chunk counts actually served, plus sources whose level could not be
  assigned (`coverage_report()` in `nctb/corpus.py`). This is the artifact a
  coverage claim is read against; gaps are listed rather than inferred from
  the absence of failures.

  **What the current artifact states (2026-10-20 rebuild, token-sized
  chunks) — the sentence any coverage claim must match:** 9 subjects across
  classes 6–12, 33 class × subject cells serving chunks: the NCTB secondary
  range (bangla 133, english 167, ict 90, mathematics 100, science 100 chunks
  per class 6–10) plus the HSC science group (biology 57, chemistry 63,
  higher-mathematics 60, physics 62 per class 11–12). Chapter headings are
  extracted for 23 of the 33 cells; the 10 cells without chapter headings
  (Bangla and English across the classes — those volumes carry no Bangla
  chapter headings at all) are listed in the artifact itself — a coverage
  claim quotes those numbers and the gaps, not a range in prose.
- `<data-dir>/chunk_ablation.json` — the chunk-size/overlap/diversity
  comparison produced by `apps/api/scripts/ablate_nctb_chunking.py` (see
  docs/RAG_ARCHITECTURE.md for the table).

**Stale outputs are pruned.** The build iterates only the manifest's
currently `acquired` sources; `prune_outputs()` deletes the
`normalized/*.chunks.jsonl`, `extracted/*.pages.json` and
`quality_report.json` rows of sources that are no longer acquired, and a
source whose raw PDF is missing or unreadable has its previous derived
artifacts deleted (AUD-A1-07). A deleted or renamed source therefore cannot
stay indexable.

**Deletion propagates to SERVING too (A2-06, 2026-10-19).** The serving load
path (`data/nctb_loader.load_nctb_corpus`, the call the app makes at boot)
now takes the acquisition manifest as the ledger: a chunk file whose source
has no manifest row — or whose last row is not `acquired` — is skipped and
counted in `load_stats["stale_sources_skipped"]`, so a source deleted (or
re-acquired as failed) after the last build stops serving even without a
rebuild. The build's own prune removes the artifacts; the loader check
covers a serving process restarted on a half-pruned data dir. Pinned by
`tests/test_r4_deletion_propagation.py` (fixture: flip/delete a manifest
row, prune, reload — the chunk does not survive a rebuild).

## 5. Chunking & class metadata

- Structure-aware: chapter-parent → section-child units, page ranges kept.
  **Chapter headings (A2-04a, 2026-10-20):** the real shape in these volumes is
  `<ordinal> অধ্যায় [number] [:：] <name>` ("প্রথম অধ্যায়: ভৌতজগত ও পরিমাপ",
  "দ্বিতীয় অধ্যায় ভেক্টর", "চতুথর্ অধ্যায় ৪ : নিউটনিয়ান বলবিদ্যা") — not the
  bare "অধ্যায়: X" the first implementation looked for. `CHAPTER_ORDINALS`
  now carries the twelve Bangla ordinals plus the two documented
  conjunct-reorder artifacts of চতুর্থ/চতুর্দশ, the heading break fires with
  or without a colon, and the emitted label repairs ONLY the ordinal
  ("চতুথর্ অধ্যায় ৪ : নিউটনিয়ান বলবিদ্যা" -> "চতুর্থ অধ্যায়: নিউটনিয়ান
  বলবিদ্যা") while title words stay verbatim. The matcher is deliberately
  conservative — a wrong chapter label is worse than an empty one:
  - a candidate whose title starts a prose sentence ("প্রথম অধ্যায় থেকে কী কী
    জ্ঞান …") is rejected;
  - a chapter REFERENCE cell of the curriculum's class-wise tables
    ("ষষ্ঠ শ্রেণি প্রথম অধ্যায় অষ্টম শ্রেণি প্রান্ত্মিক শিখনফল …", where the text
    after the citation belongs to the next column) is rejected when its title
    starts with a table-column word;
  - the title is cut at the parenthetical gloss, at the sentence end, at the
    first standalone number (the period count of the chapter tables) and at a
    later "অধ্যায়"; a title that would carry prose verbs or a stray
    combining mark is rejected.
  Measured on the extracted pages: 522 heading matches, 299 distinct clean
  labels (0 with prose pollution); chapter-carrying raw chunks went 98 → 128
  of 828 (served: 375 → 548 of 1 565), against 98 chapter-carrying raw chunks
  before the widening (`chapter` is empty on the volumes that legitimately
  have no Bangla chapter headings — the বাংলা and ইংরেজি language volumes carry
  0 "অধ্যায়" headings at all). Coverage is honest, not complete: the
  curriculum's chapter TABLES are row-dense, so a short row after a new
  heading still merges into its neighbouring chunk (the long-standing
  sub-minimum merge), and the chapter label follows the merged chunk.
- **Sentence-aware packing**: the size target is met by packing whole
  sentences at Bangla danda/`?`/`!`; only a sentence longer than the maximum
  is split, and on word boundaries. The old behaviour cut the buffer at a
  fixed word count regardless of punctuation (audit E-A1-006).
  A 0-word default overlap is available (`overlap_words`) and measured in
  the ablation; the served configuration does not use it.
- **Size is measured in tokens (A3-01, 2026-10-20)**: `TARGET_TOKENS = 612`,
  `MIN_TOKENS = 167`, `MAX_TOKENS = 1112`, derived from the historical word
  defaults (220/60/400) at the measured 2.7812 tokens/word of the served
  artifact and counted with the configured `services.context.TokenCounter`
  (the calibrated heuristic upper bound by default; a vendor counter can be
  registered). The word-based minimum is kept as an additional floor so a
  page of short words cannot silently change behaviour, and word sizing
  remains the documented fallback (`target_words=…`, used by the ablation's
  historical configurations). The report now carries `chunk_token_lengths`
  and a `chunk_sizing` block ({unit, token_counter, target/min/max tokens})
  next to the word histogram. Measured trade (docs/evaluation/
  retrieval-variants.md): the derived default keeps chunk SIZE close to the
  word baseline (828 vs 816 raw chunks) but not the retrieval outcome —
  family A recall@1 −8.3 pp, family B recall@1 +12.5 pp; the larger targets
  (≈300 words / 820 tokens) measure better and are left as a pre-registered
  size decision, not flipped here.
- **Faithful tables and formulas (A2-04e)**: a table row is preserved as a
  pipe-joined unit on its own line inside the chunk text instead of collapsing
  into one prose sentence, and a formula/symbol-dominant line stays one spaced
  unit. Two detectors, both measured against false positives on this corpus:
  - a row with column geometry (two gaps of 4+ spaces: "Reading || 40") —
    justified prose uses 2-space gaps and is deliberately NOT treated as a
    table;
  - a number row (>= 5 of 5–14 tokens numeric: "1. Bangla 150 5 87 174",
    the marks/weight tables);
  - a formula/symbol line (formula characters dominate, at least two
    operators, not a number row) — the English volume's IPA lists qualify.
  Rows and formulas are never split by the size target: pieces break BETWEEN
  units, and an oversized unit stays whole. The report counts both
  (`table_rows_preserved`, `formula_units_preserved`). Honest limit: this
  corpus's PDFs give the extractor no column geometry for most tables (the
  curriculum chapter tables arrive as single-space text), so the preserved
  population is small and enumerated in the quality report.
- Section metadata: `অনুশীলনী`/`সংক্ষিপ্ত প্রশ্ন` markers and short numbered
  curriculum headings ("৪.১ …") start a section and are recorded on the
  chunk's `section` field.
- **content_type vocabulary (A2-04b)**: every served chunk is typed in the
  catalog's vocabulary — `explanation` (explanatory body prose, including the
  English volume), `example`, `exercise`, `table` (marker opening, a preserved
  table row), `formula` (marker or symbol density), `caption` (চিত্র/ছবি/
  লেখচিত্র openings) — with the legacy `nctb` label surviving only for text
  that is neither prose nor a detected structure (proved by unit tests; the
  pre-wave-5 constant was `nctb` for every chunk).
- **page_end (A2-04c)**: `CurriculumMeta.page_end` carries the last physical
  page of the chunk's text; the loader populates it from the raw chunk
  (`page_end == page` for single-page chunks) and a passage continued across a
  page break serves its whole range. It was dropped before, so a chunk
  spanning pages 12–13 served "12" only.
- Class level is DERIVED from front matter only when unambiguous; these
  compilation volumes mention multiple classes, so detection correctly
  returns None and the loader falls back to the declared level range
  (secondary→6–10, hsc→11–12). Nothing is invented (master §75).
- Curriculum year (A2-04d): per source from the acquisition ledger's published
  edition (2012 for the secondary listing, stamped into the report row), the
  artifact's build year only as the documented fallback for sources whose
  edition is published as UNKNOWN (the HSC listing carries no প্রকাশকাল).
- Chunk ids hash the full chunk text plus chapter sequence and page; a
  rebuild from the same pages is deterministic (verified: two in-process
  builds byte-identical). The normative artifact record is the committed
  `quality_report.json` + `retrieval_eval.json`, not a remembered chunk
  count.

## 6. Reproducing from clean environment

```bash
git clone <repo> && cd BanglaGptApp/apps/api
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python scripts/build_nctb_corpus.py --data-dir ../../data/nctb --subset all
.venv/Scripts/python scripts/evaluate_nctb_retrieval.py ../../data/nctb
.venv/Scripts/python scripts/ablate_nctb_chunking.py ../../data/nctb
# then run API with NCTB_CORPUS_DIR=../../data/nctb
```

Acquisition re-runs hit only official URLs and skip already-hashed files.
Extraction can dominate a full rebuild on the HSC volumes (their PDFs fall
back to pypdf's slow symbol-set decoding); the page artifacts are reusable
for re-chunking experiments via `apps/api/scripts/ablate_nctb_chunking.py` (run from `apps/api`).

## 7. Rights / permission ledger

`data/nctb/manifests/acquisition_manifest.jsonl` records, per artifact, the
public download URL, the parent listing page, sha256, size and the licence
note exactly as published. `SourceRecord` additionally carries
`permission_status` (`official-public-download`) and `redistribution`
(`not-granted-in-writing`) — the facts this project can establish from the
official pages — and the build copies them into each source's `rights` block
in `quality_report.json`. **Per-chunk content hashes (A2-05, 2026-10-19):**
every chunk record in `normalized/*.chunks.jsonl` carries `content_hash`
(sha256 of the normalized text), stamped by `dedupe_chunks`, and each
source's report row carries `chunk_hashes_sha256` — the per-chunk analogue
of the per-document checksum, verified per run by the retrieval eval
(`serve_stats.content_hash_verification`). Derived artifacts
(`data/nctb/raw|extracted|normalized`) are gitignored, so no NCTB text is
redistributed in the repository; only metadata, reports and measured
artifacts are committed. Written permission for redistribution, if the owner
obtains it, replaces the `redistribution` value — it is an owner decision,
not an inference.
