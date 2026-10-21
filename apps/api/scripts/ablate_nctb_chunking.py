"""Chunk-size / overlap / diversity ablation on the real NCTB pages (A3-02).

The chunker's constants (TARGET_WORDS=220, MIN_WORDS=60, MAX_WORDS=400) and
``top_k`` were fixed by fiat with no comparison table anywhere. This script
re-chunks the SAME extracted pages under several configurations, loads each
one through the real corpus loader (same dedupe, class expansion and metadata
path), builds the served hybrid index per configuration and measures the
same family A (self-sentence) / family B (chapter-title) metrics as
``evaluate_nctb_retrieval.py``:

* three size targets (160 / 220 / 320 words) — the size effect;
* 220 words with a 40-word overlap — the overlap effect;
* the served index again with retrieval-time MMR diversity on
  (``diversify=True``) — the duplicate-suppression effect, no extra build;
* the lexical lane of the served configuration — the attributable baseline;
* recall@1/3/5/10 per row — the top-k effect (no separate run needed).

Writes ``data/nctb/chunk_ablation.json``; the numbers are quoted verbatim in
docs/RAG_ARCHITECTURE.md. Extraction output is reused (no PDF re-read): the
pages are the same for every configuration, which is what makes the
comparison a comparison.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

CONFIGS: tuple[dict[str, Any], ...] = (
    {"name": "target-160", "target_words": 160, "overlap_words": 0},
    {"name": "target-220-served-words", "target_words": 220, "overlap_words": 0},
    {"name": "target-320", "target_words": 320, "overlap_words": 0},
    {"name": "target-220-overlap-40", "target_words": 220, "overlap_words": 40},
    # A3-01: the served configuration is token-sized. "tokens-served" is the
    # default (TARGET_TOKENS = 612 = 220 words at the measured 2.7812
    # tokens/word); the neighbours measure the size effect in the served unit.
    {"name": "tokens-served-612", "target_tokens": 612, "overlap_words": 0},
    {"name": "tokens-420", "target_tokens": 420, "overlap_words": 0},
    {"name": "tokens-820", "target_tokens": 820, "overlap_words": 0},
    {"name": "tokens-served-overlap-40", "target_tokens": 612, "overlap_words": 40},
)
SEED = 20260825
MAX_QUERIES = 60
#: Config whose diversified/lexical variants are measured (the served one).
SERVED_CONFIG = "tokens-served-612"
#: Historical word-sized baseline the token rows are compared against.
WORD_BASELINE_CONFIG = "target-220-served-words"


def _ranks(index: Any, queries: list[tuple[str, str, int]], *, top_k: int = 10) -> list[int]:
    found: list[int] = []
    for query, unit, class_level in queries:
        hits = index.search(query, class_level=class_level, top_k=top_k)
        rank = 0
        for position, hit in enumerate(hits, start=1):
            if hit.chunk.id.rsplit("-c", 1)[0] == unit:
                rank = position
                break
        found.append(rank)
    return found


def _block(ranks: list[int]) -> dict[str, float | int]:
    def recall(k: int) -> float:
        return round(sum(1 for rank in ranks if 0 < rank <= k) / len(ranks), 4) if ranks else 0.0

    return {
        "n": len(ranks),
        "recall_at_1": recall(1),
        "recall_at_3": recall(3),
        "recall_at_5": recall(5),
        "recall_at_10": recall(10),
        "mrr": (
            round(sum(1.0 / rank for rank in ranks if rank > 0) / len(ranks), 4) if ranks else 0.0
        ),
    }


def _build_corpus(pages_dir: Path, report_src: Path, config: dict, dest: Path) -> Path:
    """Re-chunk every extracted source into ``dest`` in the pipeline layout.

    The config's sizing key decides the unit: ``target_words`` selects the
    historical word sizing, ``target_tokens`` the served token sizing measured
    with the configured TokenCounter (A3-01). Exactly one of them is passed —
    the first run of this wave passed both, and ``_resolve_sizing`` then read
    the token number as a WORD target (434 raw chunks instead of 832).
    """
    from bangla_gpt_api.nctb.chunking import chunk_pages
    from bangla_gpt_api.nctb.extract import PageText
    from bangla_gpt_api.nctb.normalize import detect_class_level

    word_target = config.get("target_words")
    token_target = config.get("target_tokens")
    overlap = int(config.get("overlap_words", 0))

    normalized = dest / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    for pages_path in sorted(pages_dir.glob("*.pages.json")):
        source_id = pages_path.name.removesuffix(".pages.json")
        payload = json.loads(pages_path.read_text(encoding="utf-8"))
        raw_pages = payload["pages"]
        pages = [PageText(**page) for page in raw_pages]
        # The pages artifact stores dicts; reading `.text` off them crashed the
        # first run of this script (AUD-A1 coverage would have been "an
        # ablation exists" with no artifact behind it).
        front_matter = "\n".join(str(page["text"]) for page in raw_pages[:12])
        detected = detect_class_level(front_matter)
        stats: dict = {}
        chunks = chunk_pages(
            pages,
            source_id=source_id,
            target_words=word_target,
            target_tokens=token_target,
            overlap_words=overlap,
            stats=stats,
        )
        with (normalized / f"{source_id}.chunks.jsonl").open("w", encoding="utf-8") as fh:
            from dataclasses import asdict

            for chunk in chunks:
                row = asdict(chunk)
                row["detected_class"] = detected
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    shutil.copy(report_src, dest / "quality_report.json")
    return dest


def _queries(
    chunks: list, rng: random.Random
) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    """Family A (self-sentence) and family B (chapter-title) query samples."""
    sample = rng.sample(chunks, min(MAX_QUERIES, len(chunks)))
    family_a = []
    for chunk in sample:
        query = " ".join(chunk.text.split()[:12])
        if len(query.split()) >= 4:
            family_a.append((query, chunk.id.rsplit("-c", 1)[0], chunk.meta.class_level))
    chapters: dict[tuple[int, str], list[str]] = {}
    for chunk in chunks:
        if chunk.meta.chapter:
            chapters.setdefault((chunk.meta.class_level, chunk.meta.chapter.strip()), []).append(
                chunk.id.rsplit("-c", 1)[0]
            )
    keys = sorted(chapters)
    rng.shuffle(keys)
    family_b = [
        (title, chapters[(class_level, title)][0], class_level) for class_level, title in keys[:40]
    ]
    return family_a, family_b


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    corpus_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../../data/nctb")
    pages_dir = corpus_root / "extracted"
    if not pages_dir.is_dir():
        print("NO_EXTRACTED_PAGES — run build_nctb_corpus.py first")
        return 1

    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="nctb-ablation-") as tmp:
        for config in CONFIGS:
            dest = Path(tmp) / config["name"]
            _build_corpus(pages_dir, corpus_root / "quality_report.json", config, dest)
            chunks = load_nctb_corpus(dest / "normalized", dest / "quality_report.json")
            if not chunks:
                print(f"{config['name']}: no indexable chunks")
                continue
            build_start = time.perf_counter()
            index = HybridIndex(chunks, HashingEmbedder())
            build_seconds = round(time.perf_counter() - build_start, 3)
            family_a, family_b = _queries(chunks, random.Random(SEED))
            row: dict[str, Any] = {
                "config": config,
                "served_chunks": len(chunks),
                "index_build_seconds": build_seconds,
                "family_A_self_sentence": _block(_ranks(index, family_a)),
                "family_B_chapter_title": _block(_ranks(index, family_b)),
            }
            if config["name"] in (SERVED_CONFIG, WORD_BASELINE_CONFIG):
                row["family_A_self_sentence_diversified"] = _block(
                    _ranks(_DiversifyWrapper(index), family_a)
                )
                row["family_B_chapter_title_diversified"] = _block(
                    _ranks(_DiversifyWrapper(index), family_b)
                )
                row["family_A_self_sentence_lexical"] = _block(_ranks(index.bm25, family_a))
                row["family_B_chapter_title_lexical"] = _block(_ranks(index.bm25, family_b))
            results[config["name"]] = row
            print(json.dumps({config["name"]: row}, ensure_ascii=False))
            del index

    report = {
        "seed": SEED,
        "corpus_source": str(pages_dir),
        "served_config": SERVED_CONFIG,
        "word_baseline_config": WORD_BASELINE_CONFIG,
        "configs": list(CONFIGS),
        "results": results,
        "deltas_vs_word_baseline": _deltas(results, WORD_BASELINE_CONFIG, SERVED_CONFIG),
    }
    out = corpus_root / "chunk_ablation.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(f"wrote {out}")
    # The Markdown the docs quote is printed from the artifact, so the table
    # is pasted verbatim instead of re-typed (and cannot drift from the JSON).
    print("\nMarkdown for docs/RAG_ARCHITECTURE.md:\n")
    print(_markdown_table(report))
    return 0


def _deltas(results: dict, baseline: str, served: str) -> dict:
    """Deltas of the served (token-sized) config against the word baseline.

    A3-01: the unit changed, so the artifact must say whether size and quality
    moved. Recall deltas are absolute (served - baseline, percentage points).
    """
    if baseline not in results or served not in results:
        return {}
    base, new = results[baseline], results[served]
    deltas: dict[str, Any] = {
        "baseline": baseline,
        "served": served,
        "served_chunks_delta": new["served_chunks"] - base["served_chunks"],
    }
    for family in ("family_A_self_sentence", "family_B_chapter_title"):
        for metric in ("recall_at_1", "recall_at_3", "recall_at_5", "recall_at_10", "mrr"):
            deltas[f"{family}.{metric}"] = round(new[family][metric] - base[family][metric], 4)
    return deltas


def _markdown_table(report: dict) -> str:
    header = (
        "| Configuration | served chunks | build s | A recall@1 | A recall@3 | A recall@5 | "
        "A recall@10 | A MRR | B recall@1 | B recall@5 |\n"
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    lines = [header]
    for name, row in report["results"].items():
        family_a = row["family_A_self_sentence"]
        family_b = row["family_B_chapter_title"]
        lines.append(
            f"| {name} | {row['served_chunks']} | {row['index_build_seconds']} | "
            f"{family_a['recall_at_1']} | {family_a['recall_at_3']} | {family_a['recall_at_5']} | "
            f"{family_a['recall_at_10']} | {family_a['mrr']} | {family_b['recall_at_1']} | "
            f"{family_b['recall_at_5']} |"
        )
        for suffix, label in (
            ("_diversified", " (MMR diversity on)"),
            ("_lexical", " (lexical lane)"),
        ):
            if f"family_A_self_sentence{suffix}" not in row:
                continue
            alt_a = row[f"family_A_self_sentence{suffix}"]
            alt_b = row[f"family_B_chapter_title{suffix}"]
            lines.append(
                f"| {name}{label} | {row['served_chunks']} | {row['index_build_seconds']} | "
                f"{alt_a['recall_at_1']} | {alt_a['recall_at_3']} | {alt_a['recall_at_5']} | "
                f"{alt_a['recall_at_10']} | {alt_a['mrr']} | {alt_b['recall_at_1']} | "
                f"{alt_b['recall_at_5']} |"
            )
    return "\n".join(lines)


class _DiversifyWrapper:
    """The served index with the MMR diversity stage enabled (opt-in)."""

    def __init__(self, index: Any) -> None:
        self.index = index

    def search(self, query: str, **kwargs: Any) -> list[Any]:
        kwargs.pop("top_k", None)
        return self.index.search(query, top_k=10, diversify=True, **kwargs)


if __name__ == "__main__":
    sys.exit(main())
