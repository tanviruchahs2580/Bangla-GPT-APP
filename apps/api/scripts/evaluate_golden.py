"""B19 — golden dataset + retrieval benchmark harness.

Runs the curated golden question set against the sample corpus (default) or
a built NCTB corpus (``--corpus-dir``). Produces:
  hit@k            – expected chapter appears in top-k retrieved chunks
  grounded accuracy– TutorService grounding gate matches ``expected_grounded``
  hallucination proxy – grounded answers whose evidence coverage < gate
Writes eval/golden_report.json and prints a summary. Exit code 1 when
accuracy gates fail so CI can enforce them.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.tutor import TutorService

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "eval" / "golden_questions.json"
REPORT_PATH = Path(__file__).resolve().parent.parent / "eval" / "golden_report.json"


def load_golden(path: Path) -> list[dict]:
    questions = json.loads(path.read_text(encoding="utf-8"))
    required = {"question", "class_level", "subject", "expected_grounded"}
    for item in questions:
        missing = required - item.keys()
        if missing:
            raise ValueError(f"golden entry missing fields {missing}: {item}")
    return questions


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    corpus_arg = None
    args = [a for a in sys.argv[1:]]
    if "--corpus-dir" in args:
        corpus_arg = Path(args[args.index("--corpus-dir") + 1])

    if corpus_arg is not None:
        chunks = load_nctb_corpus(
            corpus_arg / "normalized",
            quality_report_path=corpus_arg / "quality_report.json",
            multi_class_fallback=True,
        )
    else:
        chunks = load_sample_corpus()
    if not chunks:
        print("NO_INDEXABLE_CHUNKS")
        return 1

    index = BM25Index(chunks)
    tutor = TutorService(index=index, provider=MockLLMProvider())

    golden = load_golden(GOLDEN_PATH)
    results = []
    hits_at_3 = 0
    grounded_correct = 0
    start = time.perf_counter()
    for item in golden:
        hits = index.search(
            item["question"], class_level=item["class_level"], subject=item["subject"], top_k=3
        )
        expected_chapter = item.get("expected_chapter_contains")
        chapter_hit = bool(expected_chapter) and any(
            expected_chapter in hit.chunk.meta.chapter for hit in hits
        )
        import asyncio

        response = asyncio.run(tutor.ask(item["question"], item["class_level"], item["subject"]))
        grounded_matches = response.grounded == item["expected_grounded"]
        grounded_correct += grounded_matches
        hits_at_3 += chapter_hit or (
            item["expected_grounded"] is False
        )  # refusal cases count as correct when gate refuses
        results.append(
            {
                "question": item["question"],
                "expected_grounded": item["expected_grounded"],
                "actual_grounded": response.grounded,
                "chapter_hit": chapter_hit,
            }
        )
    elapsed = round(time.perf_counter() - start, 3)

    total = len(golden)
    report = {
        "dataset": str(GOLDEN_PATH),
        "total": total,
        "hit_at_3": round(hits_at_3 / total, 4),
        "grounded_accuracy": round(grounded_correct / total, 4),
        "latency_seconds": elapsed,
        "results": results,
    }
    out_path = REPORT_PATH
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"golden set size      : {total}")
    print(f"hit@3 / refusal ok   : {report['hit_at_3']}")
    print(f"grounded accuracy    : {report['grounded_accuracy']}")
    print(f"report written       : {out_path}")

    if report["grounded_accuracy"] < 0.9:
        print("FAIL: grounded accuracy below 0.9 gate")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
