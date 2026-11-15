"""Compare the pgvector dense lane against the in-process hybrid lane.

Offline experiment harness (import-linter contract 5) for the V5.5
retrieval report. It loads the corpus exactly the way serving does
(``load_nctb_corpus``), builds the in-process ``HybridIndex`` exactly the
way boot does, and scores three lanes on the same query set:

* ``dense``  — PgVectorStore exact cosine against the ACTIVE staging
  generation (the V5 store, real Postgres + pgvector);
* ``bm25``   — the in-process lexical lane alone;
* ``hybrid`` — the full serving fusion (BM25 ∥ vector, RRF, lexical rerank).

Query sets, both labelled PROVISIONAL (not gate-grade — no human-reviewed
labels exist yet):

* ``heading`` — self-retrieval probes: the first words of a sampled chunk
  must bring that chunk back in top-k. Measures index sanity.
* ``topic``   — assistant-authored Bangla questions per corpus subject;
  success = a chunk of the expected subject in top-k. Measures subject
  routing, not passage-level correctness.

Usage:
    python scripts/compare_dense_lane.py \
        --database-url postgresql+psycopg://... \
        --data-dir ../../data/nctb [--sample 60]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

import sqlalchemy  # noqa: E402

from bangla_gpt_api.config import get_settings  # noqa: E402
from bangla_gpt_api.data.nctb_loader import load_nctb_corpus  # noqa: E402
from bangla_gpt_api.retrieval.embedding import build_embedder  # noqa: E402
from bangla_gpt_api.retrieval.generation import PgVectorStore  # noqa: E402
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex  # noqa: E402

TOPIC_QUERIES: list[tuple[str, str]] = [
    # (query, expected subject_bn) — assistant-authored, PROVISIONAL.
    ("মহাকর্ষ সূত্র ব্যাখ্যা কর", "পদার্থবিদ্যা"),
    ("নিউটনের গতিসূত্র কী", "পদার্থবিদ্যা"),
    ("অভিকর্ষজ ত্বরণের মান কত", "পদার্থবিদ্যা"),
    ("সমান্তরাল বর্তনীর তুল্যরোধ নির্ণয়", "পদার্থবিদ্যা"),
    ("অন্তঃপ্রজোষ্ঠ সংযোজন বিক্রিয়া কী", "রসায়ন"),
    ("পরমাণুর ইলেকট্রন বিন্যাস কীভাবে লেখে", "রসায়ন"),
    ("সালোকসংশ্লেষণ প্রক্রিয়া ব্যাখ্যা কর", "জীববিজ্ঞান"),
    ("কোষ বিভাজন কত প্রকার ও কী কী", "জীববিজ্ঞান"),
    ("অন্তরীকরণ কী", "উচ্চতর গণিত"),
    ("অবকল সমীকরণের ক্রম নির্ণয়", "উচ্চতর গণিত"),
    ("সমানুপাতের ধর্ম ব্যবহার করে সমস্যা সমাধান", "গণিত ও উচ্চতর গণিত"),
    ("বীজগাণিতিক রাশির গুণন কীভাবে করে", "গণিত ও উচ্চতর গণিত"),
    ("পদ প্রকারভেদ কত প্রকার", "বাংলা"),
    ("সমাসের সংজ্ঞা ও প্রকারভেদ", "বাংলা"),
    # The English-for-today source is excluded by the loader's non-Bangla
    # gate (bangla_char_ratio < 0.5), so no English query can hit — omitted
    # from the scored set rather than scored as a failure it cannot avoid.
    ("কম্পিউটারের মূল উপাদান কী কী", "আইসিটি ও ক্যারিয়ার এডুকেশন"),
    ("ইন্টারনেট কী এবং এর ব্যবহার", "আইসিটি ও ক্যারিয়ার এডুকেশন"),
    ("কোষের প্রধান অঙ্গাণুগুলোর কাজ", "বিজ্ঞান শাখার বিষয়সমূহ"),
    ("আলোর প্রতিসরণ কী", "বিজ্ঞান শাখার বিষয়সমূহ"),
]


def _first_words(text: str, n: int = 8) -> str:
    words = text.split()
    return " ".join(words[:n])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "nctb")
    parser.add_argument("--sample", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20261115)
    args = parser.parse_args(argv)
    if not args.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        print("::error::PostgreSQL URL required", file=sys.stderr)
        return 2

    settings = get_settings()
    chunks = load_nctb_corpus(
        args.data_dir / "normalized",
        quality_report_path=args.data_dir / "quality_report.json",
    )
    if not chunks:
        print("::error::no chunks loaded", file=sys.stderr)
        return 2
    embedder = build_embedder(settings)
    index = HybridIndex(chunks, embedder)

    engine = sqlalchemy.create_engine(args.database_url)
    with engine.connect() as conn:
        row = conn.execute(
            sqlalchemy.text("SELECT generation_id FROM rag_active_generation LIMIT 1")
        ).first()
    if row is None:
        print("::error::no active generation in the staging database", file=sys.stderr)
        return 2
    store = PgVectorStore(engine, str(row[0]))
    print(f"active generation: {row[0]}  corpus chunks: {len(chunks)}")

    rng = random.Random(args.seed)
    probed = rng.sample(chunks, min(args.sample, len(chunks)))
    heading_queries = [(c.id, _first_words(c.text)) for c in probed]

    def score(
        lane: str,
        queries: Sequence[tuple[str | None, str]],
        target_of,
        k: int,
    ) -> tuple[float, float, float]:
        hits1 = hitsk = 0
        total_ms = 0.0
        for target, query in queries:
            started = time.perf_counter()
            if lane == "dense":
                out = store.search(embedder.embed([query])[0], top_k=k)
                got = [cid for cid, _ in out]
            elif lane == "bm25":
                got = [h.chunk.id for h in index.bm25.search(query, top_k=k)]
            else:
                got = [h.chunk.id for h in index.search(query, top_k=k)]
            total_ms += (time.perf_counter() - started) * 1000
            want = target_of(target)
            if want and got and got[0] == want:
                hits1 += 1
            if want and want in got:
                hitsk += 1
        n = len(queries)
        return hits1 / n, hitsk / n, total_ms / n

    print(f"\n== heading probes (self-retrieval, n={len(heading_queries)}) ==")
    for lane in ("dense", "bm25", "hybrid"):
        r1, rk, ms = score(lane, heading_queries, lambda t: t, 3)
        print(f"{lane:7s} hit@1={r1:.3f} hit@3={rk:.3f} avg={ms:.1f}ms")

    print(f"\n== topic queries (subject routing, n={len(TOPIC_QUERIES)}) ==")
    chunk_subject = {c.id: c.meta.subject for c in chunks}
    topic = [(None, q) for q, _ in TOPIC_QUERIES]
    expected = [s for _, s in TOPIC_QUERIES]

    # meta.subject carries the loader's English slug, the manifest carries
    # the Bangla name — score against the slug.
    subject_slugs = {
        "পদার্থবিদ্যা": "physics",
        "রসায়ন": "chemistry",
        "জীববিজ্ঞান": "biology",
        "উচ্চতর গণিত": "higher-mathematics",
        "গণিত ও উচ্চতর গণিত": "mathematics",
        "বাংলা": "bangla",
        "আইসিটি ও ক্যারিয়ার এডুকেশন": "ict",
        "বিজ্ঞান শাখার বিষয়সমূহ": "science",
    }

    def subject_hit(lane: str, k: int) -> float:
        ok = 0
        for (query, want_subject), (_, _) in zip(TOPIC_QUERIES, topic, strict=True):
            want_subject = subject_slugs[want_subject]
            if lane == "dense":
                got = [cid for cid, _ in store.search(embedder.embed([query])[0], top_k=k)]
            elif lane == "bm25":
                got = [h.chunk.id for h in index.bm25.search(query, top_k=k)]
            else:
                got = [h.chunk.id for h in index.search(query, top_k=k)]
            if any(chunk_subject.get(cid) == want_subject for cid in got):
                ok += 1
        return ok / len(TOPIC_QUERIES)

    for lane in ("dense", "bm25", "hybrid"):
        print(f"{lane:7s} subject-hit@3={subject_hit(lane, 3):.3f}")
    print(f"\nexpected subjects: {sorted(set(expected))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
