"""S4.3 RAG v2 -- reciprocal rank fusion over BM25 and vector rankings.

RRF merges 1-based ranked id lists without needing comparable scores across
lanes (BM25 magnitudes and cosine similarities are not comparable). Pure,
deterministic, dependency-free.
"""

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse 1-based ranked id lists into [(id, rrf_score)] sorted desc.

    score(d) = sum over lists of 1/(k + rank). Ties break by first-seen
    order (earlier lane first, then earlier position) so output is stable.
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for ranked in rankings:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            if item_id not in first_seen:
                first_seen[item_id] = order
            order += 1
    return sorted(scores.items(), key=lambda pair: (-pair[1], first_seen[pair[0]]))
