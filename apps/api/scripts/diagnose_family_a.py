"""R@1 investigation diagnostic: classify family-A rank-1 misses (V4 Phase 1).

For each sampled family-A query on the CURRENT corpus, find the rank-1
evidence unit and classify misses as:
  twin-shadow   : the rank-1 hit's text contains the query words (the query
                  text lives in a different unit than the target's — the
                  unit identity is finer than the text identity)
  other-winner  : a different unit won outright
  absent        : target unit not in top-5 at all
Counts only; no text printed beyond the query's own first words (which are
corpus-derived; kept out of stdout except the first 3 ids).
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

spec = importlib.util.spec_from_file_location(
    "evr", os.path.join(os.path.dirname(__file__), "evaluate_nctb_retrieval.py")
)
evr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evr)

corpus = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/nctb")
chunks = load_nctb_corpus(
    corpus / "normalized", corpus / "quality_report.json", multi_class_fallback=True
)
indexes = evr._build_indexes(chunks)
served = indexes["served"]
queries = evr._sample_queries(chunks)
print("family-A queries:", len(queries))
cls = {"rank1": 0, "twin-shadow": 0, "other-winner": 0, "absent": 0}
examples = []
for query, class_level, unit in queries:
    hits = served.search(query, class_level=class_level, top_k=5)
    rank = evr._rank_of(hits, {unit})
    if rank == 1:
        cls["rank1"] += 1
        continue
    if rank == 0:
        cls["absent"] += 1
        cat = "absent"
    else:
        top_text = " ".join(hits[0].chunk.text.split())
        q_words = " ".join(query.split()[:8])
        cat = "twin-shadow" if q_words in top_text else "other-winner"
        cls[cat] += 1
    if len(examples) < 3:
        examples.append(
            {
                "unit": unit,
                "class": class_level,
                "rank": rank,
                "cat": cat,
                "top_unit": evr.evidence_unit(hits[0].chunk.id) if hits else None,
            }
        )
print(json.dumps(cls, ensure_ascii=True))
print(json.dumps(examples, ensure_ascii=True))
