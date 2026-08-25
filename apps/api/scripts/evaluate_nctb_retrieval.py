"""Retrieval evaluation over the built NCTB corpus (no LLM required).

Query families (all derived from actual ingested content — nothing invented):
  A self-sentence : first words of a chunk must retrieve that chunk
  B chapter-title : a real chapter name should surface its own chunks
  C adversarial   : out-of-curriculum questions must score below the
                    TutorService grounding gate (refusal = correct)

Outputs data/nctb/retrieval_eval.json with Recall@K per family plus the
grounding-gate confusion counts for family C.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.retrieval.bm25 import tokenize


def _distinctive_terms(text: str, k: int = 6) -> list[str]:
    tokens = [t for t in tokenize(text) if len(t) > 2]
    seen: dict[str, int] = {}
    for token in tokens:
        seen[token] = seen.get(token, 0) + 1
    return [t for t, _ in sorted(seen.items(), key=lambda kv: -len(kv[0]))[:k]]


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

    build_start = time.perf_counter()
    index = BM25Index(chunks)
    build_seconds = round(time.perf_counter() - build_start, 3)
    print(f"index built: {len(chunks)} chunks in {build_seconds}s")

    rng = random.Random(20260825)
    sample = rng.sample(chunks, min(100, len(chunks)))

    # Family A: self-sentence retrieval
    recalls_a = {1: [], 5: []}
    latencies: list[float] = []
    for chunk in sample:
        query = " ".join(chunk.text.split()[:12])
        if len(query.split()) < 4:
            continue
        start = time.perf_counter()
        hits = index.search(query, class_level=chunk.meta.class_level, top_k=5)
        latencies.append(time.perf_counter() - start)

        def evidence_unit(hit_id: str) -> str:
            return hit_id.rsplit("-c", 1)[0]

        # same source+chapter+page_start counts as the target evidence unit
        base = evidence_unit(chunk.id)
        recalls_a[1].append(
            1.0 if any(evidence_unit(h.chunk.id) == base for h in hits[:1]) else 0.0
        )
        recalls_a[5].append(1.0 if any(evidence_unit(h.chunk.id) == base for h in hits) else 0.0)

    # Family B: chapter-title retrieval
    chapters: dict[tuple[int, str], set[str]] = {}
    for chunk in chunks:
        if chunk.meta.chapter:
            key = (chunk.meta.class_level, chunk.meta.chapter.strip())
            chapters.setdefault(key, set()).add(chunk.id.rsplit("-c", 1)[0])
    chapter_keys = list(chapters)
    rng.shuffle(chapter_keys)
    recalls_b = {1: [], 5: []}
    for class_level, title in chapter_keys[:80]:
        hits = index.search(title, class_level=class_level, top_k=5)
        got = {h.chunk.id.rsplit("-c", 1)[0] for h in hits}
        wanted = chapters[(class_level, title)]
        top1 = {h.chunk.id.rsplit("-c", 1)[0] for h in hits[:1]}
        recalls_b[1].append(1.0 if top1 & wanted else 0.0)
        recalls_b[5].append(1.0 if got & wanted else 0.0)

    # Family C: adversarial / out-of-corpus questions must fail the
    # TutorService grounding gate (coverage + floor), i.e., be refused.
    from bangla_gpt_api.providers.mock import MockLLMProvider
    from bangla_gpt_api.services.tutor import TutorService

    tutor = TutorService(index=index, provider=MockLLMProvider())
    adversarial = [
        "ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?",
        "ঢাকার সেরা বিরিয়ানির দোকান কোথায়?",
        "ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর",  # not in these books
        "গত সপ্তাহের ডলারের দাম কত?",
    ]
    gate_pass = 0
    for question in adversarial:
        hits = index.search(question, class_level=6, top_k=1)
        top_score = hits[0].score if hits else None
        top_text = hits[0].chunk.text if hits else ""
        refused = not tutor._grounded(question, top_score, top_text)
        gate_pass += refused
        print(f"  adversarial '{question[:30]}…' top={top_score} refused={refused}")

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    latencies.sort()
    p50 = latencies[len(latencies) // 2] * 1000 if latencies else None
    p95 = (latencies[int(len(latencies) * 0.95) - 1] * 1000) if latencies else None

    report = {
        "corpus_chunks": len(chunks),
        "index_build_seconds": build_seconds,
        "family_A_self_sentence": {
            "n": len(recalls_a[1]),
            "recall_at_1": mean(recalls_a[1]),
            "recall_at_5": mean(recalls_a[5]),
        },
        "family_B_chapter_title": {
            "n": len(recalls_b[1]),
            "recall_at_1": mean(recalls_b[1]),
            "recall_at_5": mean(recalls_b[5]),
        },
        "family_C_adversarial_refusal_rate": round(gate_pass / len(adversarial), 4),
        "search_latency_p50_ms": round(p50, 2) if p50 else None,
        "search_latency_p95_ms": round(p95, 2) if p95 else None,
    }
    out = corpus_root / "retrieval_eval.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
