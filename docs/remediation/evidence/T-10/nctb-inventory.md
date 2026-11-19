# NCTB inventory — T-10 step 7 `[needs F-02]`

F-02 verified CONFIRMED-metadata-only in `FINDINGS_VERIFIED.md`; this is the per-folder evidence the card requires. Measured 2026-11-19 at `f206ee2`.

| Path | On disk here | Tracked in git | Contents | Classification |
|---|---|---|---|---|
| `data/nctb/manifests/` | 2 files, 20,374 B (`acquisition_manifest.jsonl` 8,501 B; `corpus_manifest.json` 11,873 B) | **yes** | acquisition ledger + corpus manifest (top-level keys: `acquisition_manifest`, `sources`, `pipeline`, `totals`, `built_at`, `cross_source`, `derived`) — 28 Bengali runs ≥4 chars (titles/labels) | manifest / metadata — **provenance, not textbook text** |
| `data/nctb/quality_report.json` | 9,109 B | **yes** | per-source quality keys (`nctb-hsc-…`, `nctb-secondary-…` digests) | metadata |
| `data/nctb/retrieval_ablation.json` | 3,318 B | **yes** | eval ablation summary (schema v2 numbers, no chunk text) | metadata |
| `data/nctb/retrieval_eval.json` | 3,489 B | **yes** | retrieval eval artifact (families A/B, recall/MRR with CIs) | metadata |
| `data/nctb/raw/` | absent | gitignored (`.gitignore:95`) | — | raw PDFs — copyrighted; never tracked |
| `data/nctb/extracted/` | absent | gitignored (`.gitignore:96`) | — | extracted textbook text — copyrighted; never tracked |
| `data/nctb/normalized/` | absent | gitignored (`.gitignore:97`) | — | normalized chunks (the 1,598-chunk serving corpus is local-only) — copyrighted; never tracked |

**Repository visibility** (`gh repo view … --jq .visibility`): **PUBLIC**.

**STOP S-4 check (card step 7):** raw or extracted textbook content is NOT tracked — the five tracked files are manifests/quality/eval metadata (one-line contents verified by key inspection above). → **S-4 not raised for tracking**. The rights/licensing question for the corpus itself remains HO-3 regardless of tracking state; recorded in FINDINGS_VERIFIED F-02 (severity Medium, human-owned).

Evidence for this file: the inline `python` measurement above ran 2026-11-19 in the worktree at `f206ee2`; the tracked-file list came from `git ls-files data/nctb` (also captured in `EV-T01-t01-f02-nctb-inventory.txt`).
