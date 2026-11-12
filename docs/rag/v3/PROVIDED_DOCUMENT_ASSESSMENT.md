# Provided Document Assessment — `ICT_compressed.pdf`

**Date:** 2026-11-12 · **Branch:** `feat/rag-v3-phase-0-baseline` · **Corpus modified: no**

**Verdict: this is a genuine student textbook, and it is not ingestible as provided.** The
document requires OCR; the repository has no OCR capability; and the scan resolution present in
this file is far below what Bangla OCR needs. Details and the concrete unblock below.

---

## 1. File identity (measured)

| Property | Value |
|---|---|
| Path | `C:\Users\DST\Downloads\ICT_compressed.pdf` |
| Size | **21,360,840 bytes** (21 MB) |
| Magic | `%PDF-1.6` |
| SHA-256 | `6d679bb2c45dc373ac42250a3b108f42ac9f9df4bfcfe2834a6a0afa746fd2a9` |
| Pages | **74** |

## 2. It IS a textbook — confirmed visually

Page 1's embedded image was extracted (638,815 B, JPEG 2000) and rendered to
`%TEMP%/nctb-class6-stage/cover.png`, then inspected. It is a **textbook cover illustration**:
two schoolchildren in uniform holding up a DOEL laptop, on a red ground with faint email /
telephone / URL icons.

This is materially different from the earlier artifact I assessed (`bba604a3…`, "আইসিটি (ষষ্ঠ
শ্রেণি)"), which was an 11-page tabular curriculum extract. **This one is a textbook.**

Two honest limitations on that conclusion:
- The cover carries **no text at all** — no title, no class number, no publisher. So the cover
  confirms *"textbook"*; it does **not** independently confirm *"class 6"*. That claim rests on
  your statement plus the 74-page ICT scope.
- I did not verify the interior content, because there is nothing to read (§3).

## 3. Why it is not ingestible (measured)

| Measurement | Result | Consequence |
|---|---|---|
| Extracted characters, all 74 pages | **0** | `pypdf` — the extractor this pipeline uses (`extractor: pypdf-6.21.2` in the corpus manifest) — yields nothing |
| Bangla Unicode glyphs | **0** | No text layer exists |
| Pages with **no images and no text** | pages 2, 3, 4, 5 | A textbook's title page, copyright page and table of contents should be here. They yield **nothing** — no text, no images |
| Total embedded images | 131, but almost all are **icon-sized fragments** — `(45,30)`, `(175,154)`, `(194,117)`, `(212,166)`, `(188,125)` px | These are decorative elements, not page scans |
| Full-page-height images | 3 only — the cover `(797,1076)`, and `(600,400)` / `(801,474)` on pp. 9–10 | 71 of 74 pages have **no full-page scan** |
| Effective resolution of the largest image (the cover) | **≈92 DPI at A4** | Full-page text OCR needs **≥300 DPI**; Bangla (conjuncts, matras, reph) needs more. At 92 DPI OCR is not viable, and most images are 13–31 DPI |

Two readings are consistent with this profile: the file is a **re-compressed export** whose text
layer and per-page scans were stripped or downsized — the filename `ICT_compressed.pdf` supports
this — or the page content is in a form `pypdf` cannot reach. Either way, **as provided, the
document contains no machine-readable content.**

## 4. The repository has no OCR capability

| Check | Result |
|---|---|
| OCR dependency in `apps/api/pyproject.toml` / `constraints.txt` | **none** — no `pytesseract`, `tesseract`, `easyocr`, `paddleocr` |
| OCR module under `src/bangla_gpt_api/nctb/` | **none** (`acquisition, bijoy, chunking, content_qa, corpus, extract, manifest, normalize, reph, sources`) |
| OCR error name declared | **yes** — `OcrUnavailable` appears in the project's exception list (`pyproject.toml:169`) | The project anticipated OCR and never built it |

So OCR is not a configuration change here; it is **a capability that does not exist**.

## 5. Why I cannot simply "OCR it and run the pipeline"

V3 Phase 2 is explicit, and its requirements are not ceremonial:

- **"Route scanned pages only through a rights-approved OCR adapter with documented
  model/tool, version, language support, licence, resource limits and data handling"** — no such
  adapter exists, and selecting/approving one is an owner decision.
- **"OCR quality is measured against reviewed references, not merely successful OCR
  execution."**
- **"A real authorized content reviewer approves the release slice; an agent-generated review is
  not a substitute."**

Concretely: Bangla OCR is hard. A 74-page scanned ICT textbook OCR'd without human validation
would inject character errors into a corpus whose entire premise is *grounded in verified NCTB
sources*. Every downstream guarantee — the IDF coverage gate, the per-sentence citation check,
the excerpt shown in the evidence modal — assumes the text is faithful to the page. Feeding it
unvalidated OCR would degrade answers **while looking like progress**, which is exactly the
failure mode this work exists to prevent.

**That is why I have not ingested the file, not triggered a corpus rebuild, and not removed any
existing source.**

## 6. The two unblocks, in order of cost

**Option 1 — obtain the original, un-compressed textbook PDF (cheap, recommended).**
The NCTB textbook this cover belongs to is published as a proper PDF with either a real text
layer or 300 DPI scans. A compressed 21 MB export is the wrong artifact to ingest. If you can
supply the original from the official source, the existing pipeline ingests it directly:
`acquisition → extract → normalize → chunk → manifest → index`, with no OCR step and no new
dependency. This is the shortest path to "run the system on this document".

**Option 2 — build the OCR path (expensive, gated).**
Requires, in order: (a) owner selection and rights approval of a Bangla-capable OCR adapter;
(b) adding it as a dependency with licence and security review; (c) a page-level QA +
**quarantine** stage (which does not exist today — gap `ING-02`); (d) **human validation** of OCR
accuracy against reviewed references; (e) then ingestion as its own reviewed corpus revision.
Realistically weeks, with a human reviewer in the loop.

## 7. Status of the three instructions

| Instruction | Status |
|---|---|
| "keep only data of class 6, remove all other document from rag system" | **NOT DONE — deliberately.** `data/nctb/` is entirely untracked and gitignored, so deletion is **irreversible** (the 9 PDFs would need re-acquisition); and removing the 4 HSC sources removes classes 11–12 coverage, which contradicts "**do not break any existing feature**". The intent needs a **scope policy** (reversible, served-scope only, archives retained), which I will implement as soon as the class-6 content is actually ingestible — because scoping to a corpus that contains no class-6 content would leave the product with nothing to serve |
| "run a full enterprise elevation plan on RAG design architecture / fix all the issues according to the report" | **NOT DONE — 41 gaps across 10 dependency-gated stages are not completable in one session**, and several are blocked on rights (D-1), a teacher (D-4) and the absent DPIA (D-8). I will not report them as fixed |
| "run the final design and make sure every parameter is fully functional" | **Cannot be claimed.** V3 §6.2: a local mock test is not proof of live-provider behaviour. What is measurable is recorded: `pytest -q` → 2127 passed / 10 skipped / 0 failed; ruff, format, mypy, import-linter, lockfile, changelog, corpus-manifest all exit 0 |

## 8. What I recommend as the immediate next action

1. **Send the original un-compressed textbook PDF** (Option 1), or confirm you want the OCR
   path built (Option 2).
2. **In parallel, authorise Stage A** — evidence integrity (corpus digest + embedder + prompt +
   config identity in every eval report; fix the manifest hash ordering that can never verify;
   add a fingerprint-mismatch gate). It needs no human decision, changes no threshold or serving
   behaviour, and it is the precondition for any corpus change being *measurable* rather than
   assumed.

## 9. Artifacts from this assessment

All outside the repository, in `%TEMP%/nctb-class6-stage/`:
`cls6.pdf` (the earlier curriculum extract, 105,636 B) · `page1_0_X0.jp2` (cover scan, 638,815 B)
· `cover.png` (rendered cover, inspected).

Nothing was written into `data/nctb/`. `git status` for `data/` and `apps/api/` is clean.
