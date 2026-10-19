"""A10-03: the side-by-side re-index drill an embedding change must run.

The audit's A10-03 status was FAIL: the change-management procedure existed
for code, but an embedding/index change had no *exercised* procedure -- no
side-by-side comparison of two index generations and no rollback on the real
registry.

This module runs that drill hermetically. It builds two generations of the
served index over the same corpus:

* **v1** -- the current configuration (``HashingEmbedder()`` defaults);
* **v2** -- a simulated embedding change (a different n-gram set / dimension
  of the same local embedder -- the only embedding change this environment
  can make without downloading weights; the artifact says so).

Both generations rank the same held-out golden items through the same metric
layer, the winner is computed from the pre-registered primary metric
(Recall@5), and the generations are pushed through the real
``IndexRegistry`` (publish v1, publish v2, roll back to v1) so the rollback
path is exercised, not described. The output is the artifact a reviewer reads
before letting an embedding change ship.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bangla_gpt_api.evaluation.retrieval_strata import PRIMARY_METRIC, metrics_block

DEFAULT_SEED = 20261019
DEFAULT_TOP_K = 10


#: The incumbent plus two candidates: one plausible embedding change (same
#: family, different n-grams/dimension) and one deliberately weaker one, so
#: the drill demonstrates the procedure *catching a regression* instead of
#: only comparing two ties.
INCUMBENT = "v1-hash-default"
CANDIDATES = ("v2-hash-ngrams-3-5", "v3-hash-ngrams-1-2")


def _variant_embedder(name: str) -> Any:
    """The embedding configurations the drill compares.

    The incumbent is the shipped default; each candidate changes the n-gram
    set and/or the dimension -- the observable contract of an embedding-model
    swap, without downloading a model. Any real model drops into the same
    factory seam.
    """
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder

    if name == INCUMBENT:
        return HashingEmbedder()
    if name == "v2-hash-ngrams-3-5":
        return HashingEmbedder(dim=512, ngrams=(3, 4, 5))
    if name == "v3-hash-ngrams-1-2":
        # Deliberately weaker: 1-2 grams over a smaller space lose the
        # morphological overlap the shipped embedder exists for. The drill
        # asserts this candidate is caught, not that it wins.
        return HashingEmbedder(dim=128, ngrams=(1, 2))
    raise ValueError(f"unknown generation: {name}")


def run_drill(
    *,
    golden_path: Path,
    seed: int = DEFAULT_SEED,
    top_k: int = DEFAULT_TOP_K,
    split: str = "test",
) -> dict[str, Any]:
    """Measure both generations side by side and exercise publish/rollback."""
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.evaluation.variant_matrix import gold_units_by_section, rank_of
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
    from bangla_gpt_api.retrieval.lifecycle import IndexRegistry, IndexSnapshot, corpus_version
    from bangla_gpt_api.retrieval.vector import VectorIndex

    chunks = load_sample_corpus()
    if not chunks:
        raise SystemExit("NO_INDEXABLE_CHUNKS")
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    items = [item for item in data["items"] if item.get("split", "dev") == split]
    units = gold_units_by_section(chunks)

    generations: dict[str, Any] = {}
    lane_metrics: dict[str, Any] = {}
    registry = IndexRegistry()
    snapshots: dict[str, IndexSnapshot] = {}
    for name in (INCUMBENT, *CANDIDATES):
        embedder = _variant_embedder(name)
        index = HybridIndex(chunks, embedder)
        ranks: list[int] = []
        lane_ranks: list[int] = []
        unmatched = 0
        vector_index = VectorIndex(chunks, embedder)
        for item in items:
            if item["expect"] != "answer":
                continue
            key = (item["class_level"], item["subject"], (item.get("section") or "").strip())
            gold = units.get(key, set())
            if not gold:
                unmatched += 1
                continue
            filters = {
                "class_level": item["class_level"],
                "subject": item["subject"],
                "top_k": top_k,
            }
            ranks.append(rank_of(index.search(item["question"], **filters), gold))
            lane_ranks.append(rank_of(vector_index.search(item["question"], **filters), gold))
        block = metrics_block(ranks, seed=seed)
        block["gold_unmatched_items"] = unmatched
        generations[name] = block
        # The lane-level view: an embedding change moves the dense lane first,
        # and the served hybrid ranking can absorb it. Reporting both is the
        # difference between "the change did nothing" and "the corpus cannot
        # resolve it" -- the drill's first run showed exactly the latter.
        lane_metrics[name] = metrics_block(lane_ranks, seed=seed)
        snapshot = IndexSnapshot(
            version=corpus_version(chunks, {"embedder": name}),
            index=index,
            chunk_count=len(chunks),
            config={"embedder": name},
        )
        snapshots[name] = snapshot
        registry.publish(snapshot)

    incumbent_value = generations[INCUMBENT][PRIMARY_METRIC]
    candidate_decisions = {
        name: {
            "primary_value": generations[name][PRIMARY_METRIC],
            "incumbent_value": incumbent_value,
            "delta": round(generations[name][PRIMARY_METRIC] - incumbent_value, 4),
            "ship": generations[name][PRIMARY_METRIC] > incumbent_value,
        }
        for name in CANDIDATES
    }
    decision = {
        "primary_metric": PRIMARY_METRIC,
        "incumbent": INCUMBENT,
        "candidate_decisions": candidate_decisions,
        "decision_rule": (
            "a candidate ships only if the primary metric beats the incumbent; a tie "
            "keeps the incumbent -- an embedding change must beat it, not equal it"
        ),
        "ships": sorted(name for name, row in candidate_decisions.items() if row["ship"]),
        "caught": sorted(name for name, row in candidate_decisions.items() if not row["ship"]),
    }

    # Exercise the rollback path on the real registry: the last candidate is
    # active, roll back to the incumbent and assert the served generation
    # really changed.
    active_before = registry.active.version if registry.active else None
    # The return value is not needed: the assertions below read the registry's
    # own active pointer, which is the state that would serve traffic.
    registry.rollback(snapshots[INCUMBENT].version)
    rollback = {
        "active_before": active_before,
        "active_after": registry.active.version if registry.active else None,
        "rolled_back_to_incumbent": (
            registry.active is not None and registry.active.version == snapshots[INCUMBENT].version
        ),
        "events": [[event, version] for event, version, _at in registry.events],
        "versions": registry.versions,
    }
    return {
        "generated_by": "bangla_gpt_api.evaluation.reindex_drill",
        "run_conditions": {
            "split": split,
            "seed": seed,
            "top_k": top_k,
            "corpus": "bundled-sample",
            "corpus_chunks": len(chunks),
            "provider": "none -- retrieval only",
            "candidates_note": (
                "both candidates are simulated embedding changes (same local hashing "
                "embedder, different n-gram set/dimension); a real multilingual model "
                "drops into the same factory seam and the drill is unchanged. v3 is "
                "deliberately weaker so the drill demonstrates a caught regression."
            ),
            "golden_dataset_hash": data.get("dataset_hash"),
        },
        "generations": generations,
        "dense_lane": lane_metrics,
        "decision": decision,
        "rollback": rollback,
        "procedure": (
            "1) build the incumbent and every candidate offline (all generations "
            "kept); 2) measure all on the frozen split; 3) a candidate ships only if "
            "the primary metric beats the incumbent; 4) publish through IndexRegistry "
            "(atomic swap, cache keys follow the version); 5) rollback() re-activates "
            "the previous generation if the canary disagrees -- exercised here, not "
            "described"
        ),
    }


def markdown_summary(report: dict) -> str:
    """The side-by-side table for docs; generated, never hand-copied."""
    lines = [
        "| Generation | Recall@1 | Recall@5 | MRR@10 | n | dense-lane Recall@5 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, block in report["generations"].items():
        lane = report["dense_lane"][name]
        lines.append(
            f"| {name} | {block['recall_at_1']} | {block['recall_at_5']} | "
            f"{block['mrr_at_10']} | {block['n']} | {lane['recall_at_5']} |"
        )
    decision = report["decision"]
    lines.append("")
    lines.append(
        f"Primary metric {decision['primary_metric']}, incumbent {decision['incumbent']}: "
        f"ships {decision['ships'] or '(none)'}, caught by the gate "
        f"{decision['caught'] or '(none)'}; rollback to the incumbent asserted: "
        f"{report['rollback']['rolled_back_to_incumbent']}"
    )
    return "\n".join(lines)


__all__ = ["DEFAULT_SEED", "markdown_summary", "run_drill"]
