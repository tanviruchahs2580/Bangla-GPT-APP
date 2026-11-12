# Stage D Blocker — Source Availability Finding

**Date:** 2026-11-12 · **Branch:** `feat/rag-v3-phase-0-baseline` · **Authorisation:** repo owner
directed acquisition of real class-6 textbooks ("you can get class 6 book from internet if you
dont have").

**Outcome: the acquisition was attempted, the official source is reachable, the artifact was
retrieved — and it is not a textbook.** Option B is blocked on **source availability**, not on
permission, effort, or effort-to-be-spent. No corpus change was made.

---

## 1. What was executed

| Step | Result |
|---|---|
| Checked whether a class-6 artifact is already held | **Not held.** `data/nctb/raw/` contains only the 5 `ssc-science` + 4 `hsc-science` artifacts |
| Located the official source in the project's own registry | `apps/api/src/bangla_gpt_api/nctb/sources.py` declares **16** `SECONDARY_ARTIFACTS` and **32** `HSC_ARTIFACTS`; the build only ever acquires 5 + 4 (`SUBSETS` in `scripts/build_nctb_corpus.py:43-57`) |
| Identified the one artifact named for class 6 | `bba604a37ec641d79c15a18dace2be5c` — `"আইসিটি (ষষ্ঠ শ্রেণি)"` |
| HEAD request to the official ministry bucket (no download) | `HTTP/1.1 200 OK`, `Content-Type: application/pdf`, `Content-Length: 105636` |
| Downloaded to a **staging directory outside the corpus** | `%TEMP%/nctb-class6-stage/cls6.pdf` — **105,636 bytes**, magic `%PDF-1.6` |
| SHA-256 of the retrieved file | `dd6df36a10cc78829d89f6f97a0288a6ac3b16575ab0d4742671ff9613888610` |
| Inspected structure (11 pages, text extraction) | see §2 |

The artifact was **not** placed in `data/nctb/raw/` and **no corpus build was run.** Reasons in §4.

## 2. What the artifact actually is

| Signal | Measurement | Interpretation |
|---|---|---|
| Page count | **11** | A textbook would be 100+ pages; the held secondary sources are 93–241 pages |
| Size | 105,636 B | ~1/10th of the smallest held source (744 KB) |
| Bangla Unicode glyphs | **0 on all 11 pages** | 100% legacy Bijoy/SutonnyMJ encoding — needs conversion before any Bangla Unicode work |
| Structure | pages 2–6 hold **85–106 lines each** of tabular content | Not narrative prose |
| Page 1 header | `RvZxq wk v╡g 2012` | **জাতীয় শিক্ষাক্রম ২০১২** — *National Curriculum 2012* |
| Page 2 content | `c╓_g Aa¿vq: Z_¿ I åhvMvçhvM c╓hyw│ cwiwPwZ (10 wcwiqW)` then `wkLbdj welqe»æ wkLb-åkLvçbv wbç`⌐kbv weçkl g~j¿vqb wbç`⌐kbv` | "প্রথম অধ্যায়: তথ্য ও যোগাযোগ প্রযুক্তি পরিচিতি **(10 পিরিয়ড)**" followed by the column set **শিখনফল · বিষয়বস্তু · শিখন-শেখানো পদ্ধতি · নির্দেশনা · মূল্যায়ন নির্দেশনা** = *learning outcomes · content · teaching-learning method · instructions · assessment instructions* |

**Conclusion: this is an extract of the National Curriculum 2012 syllabus for class 6 ICT —
a curriculum document, not a student textbook.** It contains learning outcomes and assessment
guidance. It contains **no explanatory content a student could learn from**, which is precisely
what a textbook provides and what a grounded answer must cite.

### 2.1 The project's own code corroborates this

```
apps/api/src/bangla_gpt_api/nctb/bijoy.py:76
    _CONVERTER_TAIL = "  RvZxq wk\xffv\xb5g 2012  "
```

The legacy-Bijoy converter's tail constant **is this document's header text**. The project has
already handled this document family and knows it as জাতীয় শিক্ষাক্রম ২০১২ — the curriculum,
not a textbook.

### 2.2 Every listing heading says শিক্ষাক্রম

`sources.py` records the section headings of the two pages it verified:

| Page | Recorded heading | Meaning |
|---|---|---|
| Secondary | `মাধ্যমিক স্তরের শিক্ষাক্রম(প্রকাশকাল -২০১২)` | *Secondary-level **curriculum*** |
| HSC | `উচ্চ মাধ্যমিক স্তরের শিক্ষাক্রম` | *Higher-secondary-level **curriculum*** |

The `sources.py` docstring describes them as "16 textbook PDFs" / "32 textbook PDFs" — that
description is **wrong**, and this measurement is the proof. It is the same
`curriculum_document` vs `textbook` conflation recorded as gap `SRC-03`, now confirmed at the
source-listing level rather than only in prose.

## 3. Why this blocks Option B — and why it is not a dead end

**What the verified pages do provide:** artifacts **scoped by class and subject**. So genuine
`detected_classes=[6]` attribution *is* achievable — which fixes the class-attribution half of
gaps `META-01`/`META-05`.

**What they do not provide:** teachable content. A curriculum extract lists what must be
taught, not an explanation of it.

**Why that matters concretely.** If the class-6 curriculum extract were added to the corpus, the
retriever would index learning-outcome tables. A class-6 student asking *"তথ্য ও যোগাযোগ
প্রযুক্তি কী?"* would be grounded on a row reading `শিখনফল / মূল্যায়ন নির্দেশনা` and the answer
would be built from syllabus metadata. **The answer would get worse, not better**, while the
scope badge read "class 6". That is the specific mistake the instruction "make no mistake"
warns against, so the artifact was deliberately **not** added.

## 4. Why no corpus change was made

1. **It would degrade answer quality** (§3) — the artifact carries no content to ground on.
2. **A corpus rebuild is a corpus revision.** Adding a source changes the corpus digest, which
   invalidates `data/nctb/manifests/corpus_manifest.json`, `data/nctb/retrieval_eval.json` and
   `data/nctb/quality_report.json`. `AGENTS.md` §11 makes the manifest **AI-Engineer-owned** and
   requires `check_corpus_manifest.py` + `content_qa.py` to pass on a corpus change.
3. **The full build re-extracts and re-chunks all 9 existing sources.** The English source has
   **89 of 93 pages unusable**, so the build's content gate may fail, and it may shift existing
   chunk counts (the committed artifact is already documented as non-reproducible: 847 on disk
   vs a rebuild that yields different numbers). Triggering that inside this session — with no
   budget left to verify the outcome — is exactly how an existing feature gets broken.
4. **`AGENTS.md` §11 / V3 §12:** a baseline must never be regenerated in the same change as the
   retrieval change it would mask. The corpus revision needs its own reviewed change, after
   Stage A binds the evidence so the impact is measurable.

## 5. What is actually required to obtain real class-6 textbooks

The project has only ever verified the two **`শিক্ষাক্রম` (curriculum)** listing pages. Real NCTB
textbooks (`পাঠ্যবই`) are published on a **different** listing that this repository has never
catalogued. To proceed with Option B properly:

1. **Locate the official textbook listing** on `nctb.gov.bd` (the textbook/পাঠ্যবই section, or the
   ministry portal's textbook page) — an official NCTB or ministry domain only. V3 §4.2 and
   Phase 1 task 6 forbid ingesting unapproved third-party mirrors.
2. **Extend `nctb/sources.py`** with a `TEXTBOOK_ARTIFACTS` registry recording:
   `file_id`, `subject_bn`, `level`, **`class_level`**, `edition`, `parent_page`, `storage_url`
   — plus the `source_type` field V3 Phase 1 requires (`textbook` vs `curriculum_document`).
3. **Add an acquisition subset** (e.g. `class6-textbooks`) so the acquisition is reproducible
   from the tracked registry, never a one-off download.
4. **Record provenance**: sha256, `retrieved_at`, file size, rights note.
5. **Record the three permissions separately** — `storage_allowed`, `indexing_allowed`,
   `excerpt_display_allowed` (V3 Phase 1 task 5). The owner directed acquisition; that direction
   is recorded as the authorisation for **storage**, while **display to students** remains
   `PENDING` because it is the permission the evidence modal depends on.
6. **Then** run the ingestion → extraction → normalization → chunking pipeline as its **own
   reviewed corpus revision**, with the manifest regenerated and the retrieval baseline
   regenerated *separately*.

## 6. Status

| Item | Status |
|---|---|
| Official source reachable | **VERIFIED** (HTTP 200) |
| Class-6 artifact located in the project's registry | **CONFIRMED** (`bba604a3…`, "আইসিটি (ষষ্ঠ শ্রেণি)") |
| Artifact retrieved to staging | **DONE** — `%TEMP%/nctb-class6-stage/cls6.pdf`, sha256 `dd6df36a…` |
| Artifact is a textbook | **FALSE** — 11 pp, 100% legacy Bijoy, curriculum/assessment tables |
| Option B (real class-6 textbooks) | **BLOCKED — source availability.** Needs the NCTB পাঠ্যবই listing, which this repo has never catalogued |
| Corpus modified | **No** |
| Existing feature broken | **No** |
| Class-6 attribution achievable via curriculum extracts | **Yes** — but that fixes `META-01` (scope truthfulness), not teachable content |

**Recommended next action.** Treat the class-6 curriculum extracts as what they are: a **scope
and provenance** asset for Stage B, and keep hunting for the textbook listing for Stage D. The
two are complementary, not alternatives — and neither substitutes for the other.

**Cleanup note.** The staged PDF sits outside the repository in `%TEMP%`. It is a copyrighted
NCTB document; say the word and I will delete it, or leave it as evidence for the acquisition
attempt. Nothing was written into `data/nctb/`.
