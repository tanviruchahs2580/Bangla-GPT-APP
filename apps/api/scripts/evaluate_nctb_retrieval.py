"""Retrieval evaluation over the built NCTB corpus (no LLM required).

Measures the index production actually serves — the hybrid lane, matching
``retrieval_mode="hybrid"`` — against every query family, with the plain
lexical lane alongside as an attributable baseline:

  A self-sentence: first words of a chunk must retrieve that chunk
  B chapter-title: a real chapter name should surface its own chunks
  C adversarial: out-of-curriculum questions must score below the
                    TutorService grounding gate (refusal = correct)

Outputs data/nctb/retrieval_eval.json with Recall@K and MRR per family and
the grounding-gate confusion counts for family C.

The corpus text itself is NCTB source material and stays out of the
repository (data/nctb/raw|extracted|normalized are gitignored — see
docs/NCTB_DATA_PIPELINE.md), so the committed retrieval_eval.json IS this
script's regression baseline: regenerate it locally after any retrieval
change and read the diff.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus


def mean(values: list[float]) -> float:
    """Arithmetic mean at report precision; empty inputs are 0, not NaN."""
    return round(sum(values) / len(values), 4) if values else 0.0


def mrr(ranks: list[int]) -> float:
    """Mean reciprocal rank; rank 0 means "not in top-k" and contributes 0."""
    return round(sum(1.0 / rank for rank in ranks if rank > 0) / len(ranks), 4) if ranks else 0.0


def evidence_unit(hit_id: str) -> str:
    """Chunk ids of one page range share an evidence unit."""
    return hit_id.rsplit("-c", 1)[0]


def _rank_of(hits, wanted_units: set[str]) -> int:
    """1-based best rank of the wanted evidence unit; 0 when absent."""
    for position, hit in enumerate(hits, start=1):
        if evidence_unit(hit.chunk.id) in wanted_units:
            return position
    return 0


def _recall_at_1(matched_ranks: list[int]) -> float:
    """1.0 only when the wanted evidence unit sits at rank 1.

    ``matched_ranks`` holds the 1-based positions where the evidence unit
    occurred in the top-k; membership alone is Recall@k, not Recall@1.
    """
    return 1.0 if matched_ranks and matched_ranks[0] == 1 else 0.0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    corpus_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../../data/nctb")
    chunks = load_nctb_corpus(
        corpus_root / "normalized",
        quality_report_path=corpus_root / "quality_report.json",
        multi_class_fallback=True,
    )
    if not chunks:
        print("NO_INDEXABLE_CHUNKS — run build_nctb_corpus.py first")
        return 1

    from bangla_gpt_api.retrieval.bm25 import BM25Index
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    build_start = time.perf_counter()
    lexical = BM25Index(chunks)
    served = HybridIndex(chunks, HashingEmbedder())
    build_seconds = round(time.perf_counter() - build_start, 3)
    print(f"index built: {len(chunks)} chunks in {build_seconds}s")

    indexes = {"lexical": lexical, "served": served}
    rng = random.Random(20260825)

    # --- Family A: self-sentence retrieval ---------------------------------
    #
    # The first words of a chunk are the question; the same chunk (its
    # evidence unit) is the only correct answer.
    stats_a: dict[str, dict[str, list[float]]] = {
        name: {"recall_at_1": [], "recall_at_5": [], "mrr": []} for name in indexes
    }
    latencies: dict[str, list[float]] = {"lexical": [], "served": []}
    for chunk in rng.sample(chunks, min(100, len(chunks))):
        query = " ".join(chunk.text.split()[:12])
        if len(query.split()) < 4:
            continue
        base = evidence_unit(chunk.id)
        for name, index in indexes.items():
            start = time.perf_counter()
            hits = index.search(query, class_level=chunk.meta.class_level, top_k=5)
            latencies[name].append(time.perf_counter() - start)
            matched = [
                position
                for position, hit in enumerate(hits, start=1)
                if evidence_unit(hit.chunk.id) == base
            ]
            stats_a[name]["recall_at_1"].append(_recall_at_1(matched))
            stats_a[name]["recall_at_5"].append(1.0 if matched else 0.0)
            # The RANK (1-based) feeds the MRR helper — it computes the
            # reciprocal itself; feeding the reciprocal here would
            # double-invert the mean (an earlier draft reported MRR 2.08,
            # which is impossible by construction).
            stats_a[name]["mrr"].append(matched[0] if matched else 0)

    # --- Family B: chapter-title retrieval ---------------------------------
    #
    # A real chapter name should surface the chunks of that chapter.
    chapters: dict[tuple[int, str], set[str]] = {}
    for chunk in chunks:
        if chunk.meta.chapter:
            key = (chunk.meta.class_level, chunk.meta.chapter.strip())
            chapters.setdefault(key, set()).add(chunk.id.rsplit("-c", 1)[0])
    chapter_keys = list(chapters)
    rng.shuffle(chapter_keys)
    stats_b: dict[str, dict[str, list[float]]] = {
        name: {"recall_at_1": [], "recall_at_5": [], "mrr": []} for name in indexes
    }
    for class_level, title in chapter_keys[:80]:
        wanted = chapters[(class_level, title)]
        for name, index in indexes.items():
            hits = index.search(title, class_level=class_level, top_k=5)
            rank = _rank_of(hits, wanted)
            stats_b[name]["recall_at_1"].append(1.0 if rank == 1 else 0.0)
            stats_b[name]["recall_at_5"].append(1.0 if 0 < rank <= 5 else 0.0)
            stats_b[name]["mrr"].append(1.0 / rank if rank > 0 else 0.0)

    # --- Family C: adversarial / out-of-corpus refusals ---------------------
    from bangla_gpt_api.providers.mock import MockLLMProvider
    from bangla_gpt_api.services.tutor import TutorService

    tutor = TutorService(index=served, provider=MockLLMProvider(), term_stats=served.term_stats)
    adversarial = [
        "ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?",
        "ঢাকার সেরা বিরিয়ানির দোকান কোথায়?",
        "ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর",  # not in these books
        "গত সপ্তাহের ডলারের দাম কত?",
    ]
    gate_pass = 0
    for question in adversarial:
        # exactly the ask() decision: retrieve, then the coverage gate.
        hits = tutor._retrieve(question, class_level=6, subject=None)
        top_score = hits[0].score if hits else None
        refused = not tutor._gate(question, hits)
        gate_pass += refused
        print(f"  adversarial '{question[:30]}…' top={top_score} refused={refused}")

    def block(stats: dict[str, list[float]]) -> dict[str, float]:
        return {
            "n": len(stats["recall_at_1"]),
            "recall_at_1": mean(stats["recall_at_1"]),
            "recall_at_5": mean(stats["recall_at_5"]),
            "mrr": mrr(stats["mrr"]),
        }

    latencies_served = sorted(latencies["served"])
    p50 = latencies_served[len(latencies_served) // 2] * 1000 if latencies_served else None
    p95 = (
        latencies_served[int(len(latencies_served) * 0.95) - 1] * 1000 if latencies_served else None
    )

    report = {
        "corpus_chunks": len(chunks),
        "index_build_seconds": build_seconds,
        "served_index": "hybrid",
        "family_A_self_sentence": block(stats_a["served"]),
        "family_B_chapter_title": block(stats_b["served"]),
        "family_C_adversarial_refusal_rate": round(gate_pass / len(adversarial), 4),
        "search_latency_p50_ms": round(p50, 2) if p50 else None,
        "search_latency_p95_ms": round(p95, 2) if p95 else None,
        "baseline_lexical": {
            "family_A_self_sentence": block(stats_a["lexical"]),
            "family_B_chapter_title": block(stats_b["lexical"]),
        },
    }
    out = corpus_root / "retrieval_eval.json"
    # trailing newline: the pre-commit end-of-file-fixer requires it, and a
    # Windows text-mode write will not add one on its own.
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
