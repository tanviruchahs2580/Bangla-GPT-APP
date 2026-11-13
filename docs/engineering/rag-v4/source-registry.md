# Class 6 source registry & corpus integrity (V4 Phase 2)

Verified 2026-11-13 (Document AI workstream). Facts only as measured; no source files were
re-parsed and no corpus text is reproduced here. Full command evidence in the execution log and
`evidence-ledger.jsonl`.

## Approved source registry (as served today)

| source_id | level | subject | edition | chunks | usable pages | Bangla ratio | status |
|---|---|---|---|---|---|---|---|
| nctb-secondary-3ce5065b7a32 | secondary (6–10 curriculum) | বাংলা | প্রকাশকাল ২০১২ | 132 | — | 1.000 | approved (tracked manifest) |
| nctb-secondary-afda21d8556d | secondary | ইংরেজি | প্রকাশকাল ২০১২ | 123 | — | **0.0376** | **excluded from index** (Bangla-ratio gate, silent) |
| nctb-secondary-be50d8aff8d5 | secondary | গণিত ও উচ্চতর গণিত | প্রকাশকাল ২০১২ | 89 | — | 0.9984 | approved |
| nctb-secondary-ca0d6bd886b7 | secondary | আইসিটি ও ক্যারিয়ার এডুকেশন | প্রকাশকাল ২০১২ | 86 | — | 1.000 | approved |
| nctb-secondary-e39c58d35764 | secondary | বিজ্ঞান শাখার বিষয়সমূহ | প্রকাশকাল ২০১২ | 82 | — | 1.000 | approved |
| nctb-hsc-28d03c592c2c | hsc (11–12) | পদার্থবিদ্যা | UNKNOWN | 89 | 52/52 | 0.8446 | approved |
| nctb-hsc-9c44bb8ff649 | hsc | উচ্চতর গণিত | UNKNOWN | 97 | — | 0.7340 | approved |
| nctb-hsc-a513203336f6 | hsc | রসায়ন | UNKNOWN | 69 | — | 0.9316 | approved |
| nctb-hsc-ca39e5957513 | hsc | জীববিজ্ঞান | UNKNOWN | 80 | — | 0.8501 | approved |

Totals: 9 sources, 847 chunks, 555 unique texts (292 cross-source duplicate copies), 1,627,831
characters; extractor pypdf-6.21.2; processing_version v1; chunker {tokens, 220/60/450,
nfkc+zero-width+whitespace}; manifest_version 1.

## Rights / provenance status — the honest reading

- The ingested artifacts are **curriculum documents (শিক্ষাক্রম)** per `docs/NCTB_DATA_PIPELINE.md:36-38`,
  not student textbooks. Storage/processing here is internal research use; **redistribution rights for
  display/export are not established** — owner/legal decision, unchanged from prior V3 findings.
- The **owner-supplied class-6 textbook is not ingested**: it sits outside the repo
  (`Downloads/ICT_compressed.pdf`, 21,360,840 B, zero extractable text at ~92 DPI; a 94 MB
  "decompressed" copy has identical pixel geometry; a 39 MB `.docx` exists and is the known
  unblocking route). No OCR capability exists in the tree (`OcrUnavailable` declared, never
  implemented). **Source status: QUARANTINED — owner-supplied, not ingestible as provided.**
- No class-6-specific content is served: classes 6–10 share one identical 244-chunk secondary payload
  via the level-range fallback (`nctb_loader.py:143-145`); `detected_classes` is empty for all five
  secondary sources (their covers declare no class). This is the Class-6 gap: the product's class-6
  experience rests on curriculum text, not the class-6 textbook.

## Integrity evidence (all commands run today, real outputs)

- `python apps/api/scripts/check_corpus_manifest.py --data-dir data/nctb --corpus-dir data/nctb`
  → `OK: tracked corpus artifacts agree with the manifest` (1598 index chunks; digest `1396faf2…`).
- `python apps/api/scripts/content_qa.py report <each of 9 jsonl>` → all 9 `pass: true`,
  0 flagged chunks per file, 0 duplicates per file. (Caveat: the QA gate does not judge
  script-mismatch — it passed the 0.0376-ratio English book.)
- Determinism: `_stable_id` = sha1(source_id|"chunk"|chapter_seq|first_page|chunk_text)[:16]
  (`chunking.py:148-150`) — content-derived ids; reph/DE-PUA transforms pinned idempotent
  (`test_corpus_integrity_v2.py:93,202,437`). **No committed rebuild artifact exists** for the
  `--rebuild-dir` byte-identity leg → recorded as gap G6, now closed by the new idempotency test
  (`tests/test_nctb_rebuild_idempotence.py`, added in this pass).

## Pipeline map (one line per module)

acquisition (polite, hashed, resumable download) → extract (pypdf + Bijoy at the choke point) →
normalize (NFKC + zero-width + whitespace; class detection) → chunking (structure-aware, SourceSpan
provenance) → corpus (build JSONL + quality_report + manifest) → manifest (acquisition ledger +
verify) → loader (`apps/api/src/bangla_gpt_api/data/nctb_loader.py`: level-range expansion,
`(content_hash, class)` dedupe with
shared-source merge, injection strip) → index (BM25 + vector + RRF + rerank).

## Gaps opened in this pass (severity → disposition)

| # | Gap | Sev | Disposition |
|---|---|---|---|
| G1 | No class-6-specific content; 6–10 share one payload | P1 | OWNER: ingest the supplied class-6 textbook via the .docx route (teacher review + rights decision gate it) |
| G2 | Served corpus is curriculum, not textbooks | P1 | OWNER/legal (rights + scope) |
| G3 | Supplied class-6 PDF not ingestible; no OCR | P1 | Documented; .docx is the unblocking path |
| G4 | Multi-class served despite class-6 product scope | P2 | OWNER scope decision (do not delete — V3 governance); per-class metadata already preserved |
| G5 | English book silently excluded | P2 | This pass: exclusion is now LOGGED loudly with counts (`nctb_loader` change) |
| G6 | No byte-identical re-ingestion test | P2 | CLOSED this pass: `test_nctb_rebuild_idempotence.py` |
| G7 | Parser: no size/page caps, no isolation/timeout | P2 | Partially CLOSED this pass: size cap (64 MB) + default page cap (2000) in the build path, tested; process isolation remains deferred (needs sandboxing design) |
| G8 | Per-page parse failures indistinguishable from blanks | P3 | Deferred (diagnostic field design) |
| G9 | Docs drift (852/1605/169 vs 847/1598/163) | P3 | Fix in the pipeline doc with this change |
| G10 | Chunk JSONL stores text twice (`text` + `original_text`) | P3 | Deferred (schema decision; untracked artifacts) |
| G11 | `sources.py:48` calls curriculum docs "textbooks" | P3 | Comment fix in this pass |

## Exit-gate status (V4 §5.8)

Accounted ✓ · rights known-or-quarantined ✓ (quarantined: the supplied book; curriculum docs
internal-use-only) · extraction measurable ✓ (content_qa + reviews exist) · no synthetic content in
corpus ✓ (verified: sources are the 9 tracked PDFs) · idempotent/reproducible ✓ (new test) ·
manifest+index integrity ✓ · failed ingestion cannot publish partial corpus ✓ (build writes outputs
only on success; `--rebuild-dir` verify exists) · rollback documented — corpus rollback is NOT tested
(tracked artifacts are regenerable from PDFs; owner window needed to rehearse) → residual item ·
future class-6 addition needs no redesign ✓ (registry + pipeline ready).
