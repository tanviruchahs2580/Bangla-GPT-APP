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

`nctb/acquisition.py` + `scripts/build_nctb_corpus.py`

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

## 4. Quality control (`quality_report.json`, committed)

Per source: total/empty/garbage/usable pages, usable ratio, Bangla ratio on
usable text, page-encoding histogram, chunk count. Verified run:

| Source | usable pages | Bangla ratio (post-conversion) | chunks |
|---|---|---|---|
| বাংলা | 91/93 | 1.00 | 126 |
| ইংরেজি (English book) | 91/93 | 0.04 (correctly low) | 122 |
| গণিত ও উচ্চতর গণিত | 143/146 | 1.00 | 173 |
| বিজ্ঞান শাখার বিষয়সমূহ | 239/241 | 1.00 | 302 |
| আইসিটি ও ক্যারিয়ার এডুকেশন | 109/111 | 1.00 | 147 |
| পদার্থবিদ্যা | 52/52 | 0.84 | 81 |
| রসায়ন | 45/45 | 0.90 | 83 |
| জীববিজ্ঞান | 46/46 | 0.83 | 81 |
| উচ্চতর গণিত | 52/52 | 0.73 | 84 |

Indexing gate: any source below **0.5 Bangla ratio on usable text** never
reaches the tutor index (`data/nctb_loader.py`) — this is what keeps
un- or mis-converted content out of student answers.

## 5. Chunking & class metadata

- Structure-aware: chapter-parent → section-child units, page ranges kept;
  heading patterns cover both textbook ("অধ্যায়: X") and curriculum
  ("প্রথম অধ্যায় : X") formats; running-header gluing is un-wound before
  line matching.
- Class level is DERIVED from front matter only when unambiguous; these
  compilation volumes mention multiple classes, so detection correctly
  returns None and the loader falls back to the declared level range
  (secondary→6–10, hsc→11–12). Nothing is invented (master §75).

## 6. Reproducing from clean environment

```bash
git clone <repo> && cd BanglaGptApp/apps/api
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python scripts/build_nctb_corpus.py --data-dir ../../data/nctb --subset all
.venv/Scripts/python scripts/evaluate_nctb_retrieval.py ../../data/nctb
# then run API with NCTB_CORPUS_DIR=../../data/nctb
```

Acquisition re-runs hit only official URLs and skip already-hashed files.
