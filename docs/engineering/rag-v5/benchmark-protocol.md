# RAG V5 benchmark protocol — PRE-REGISTERED 2026-11-15 (v1)

Status: `PROPOSED_PENDING_OWNER_APPROVAL` for every tolerance below. This
protocol is registered BEFORE any candidate scoring; changing a threshold
after seeing held-out results requires a versioned amendment reporting old
and new outcomes (V5 §5.2).

## Corpus identity

- Current serving corpus: 9 NCTB curriculum sources, 847 chunks / 1598
  index entries, digest `1396faf2…`, pipeline fingerprint pinned in
  `data/nctb/manifests/corpus_manifest.json`. Class scope: the corpus
  spans the secondary 6–10 payload (per-class metadata empty); the V5
  Class 6-only serving index is `BLOCKED_SOURCE_OR_RIGHTS` until the
  approved Class 6 textbook is ingested (quarantined source; `.docx` route
  documented). All metrics below are therefore corpus-scope-labelled
  `CURRENT_CORPUS`, not `CLASS6_TEXTBOOK`.

## Datasets

| Dataset | n | Provenance | Use |
|---|---|---|---|
| golden_v3 (sample-bound) | 427 | committed, human-authored labels on the 78-chunk bundled sample | CI gate only; never real-corpus evidence |
| retrieval_eval families (real corpus) | 100 + 80 + adversarial 12 | self-sentence / chapter-title / adversarial — weak supervision, no human review | smoke + regression; labelled `MODEL_PROPOSED` |
| Class 6 human-reviewed benchmark | 0 | **does not exist** | `BLOCKED_OWNER_DATA`: qualified Bangla educator review required (V5 §5.1) |

Leakage control: self-sentence queries derive from chunk text — they may
never be used to rank embedding-model candidates for selection; they are
regression monitors only.

## Configurations (pre-registered)

| ID | Configuration |
|---|---|
| B0 | BM25 only |
| B1 | BM25 + HashingEmbedder + RRF (current default) |
| E1 | multilingual-e5-small (query:"/passage:" prefixes) + exact cosine, BM25 lane held |
| H1 | B1 lanes with neural dense lane swapped in, RRF unchanged |

BGE-M3 and a materially different third candidate: listed for the owner
run, not executed this wave (model download + label gate). Hashing is
never a hidden fallback (V5 §8).

## Metrics, k, denominators

- Recall@1/3/5/10, MRR@10 over the family hit definitions; denominators =
  per-family n (100 / 80 / 12) — always reported with the metric.
- Per-stratum: Bangla-script vs Banglish vs English query origin where the
  family metadata allows; per-subject breakdown.
- Bootstrap 95% CI (resampling unit = query, seed 20261115, 1000 draws).
- Exact-vs-ANN agreement: not applicable this wave (ANN deferred; exact
  search is the reference at 847-chunk scale, V5 §6.3).

## Selection rule and tolerances (PROPOSED_PENDING_OWNER_APPROVAL)

- A neural candidate may be RECOMMENDED only when human-reviewed Class 6
  labels exist and show: Recall@5 improvement ≥ +5pp absolute over B1 with
  a bootstrap CI excluding 0; no per-stratum regression beyond 2pp; no
  increase in out-of-corpus false-answer rate; latency within the
  deployment budget measured on the target host.
- With no human-reviewed labels: report results as `MODEL_PROPOSED` /
  `INCONCLUSIVE`; the production default stays BM25 + HashingEmbedder
  (`NO_QUALIFIED_WINNER` until evidence exists).
- Reranker (cross-encoder): same gate; lexical reranking is retained until
  a measured incremental nDCG/MRR gain exists on adjudicated data.
- Semantic verifier enforce mode: prohibited until calibrated false-accept
  evidence on human-reviewed examples exists; shadow mode is
  non-blocking and never displayed as verified.
