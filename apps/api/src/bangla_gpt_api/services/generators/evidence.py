"""Shared evidence budget for grounded generation (RAG audit F-06).

None of the generation paths capped how much textbook text one prompt may
carry: the tutor tops out at three chunks (~7k chars), but the teacher
generators retrieve ``top_k=6`` and the question-paper loop gathers
``top_k_per_chapter=3`` for EVERY chapter of a paper with no total ceiling
— a 15-chapter paper could pour ~100k chars of evidence into one provider
call. Provider-side truncation then cuts the tail silently and token cost
scales with prompt length.

Every grounded path therefore trims its retrieval through this module
BEFORE prompt assembly. The same trimmed list feeds the citation list, so
the sources a teacher sees are exactly the passages the model saw. The
tutor's ask path is deliberately NOT trimmed: its gate and evidence read
the same three-hit list (budgeting there would change the grounding
verdict), and its ceiling is already fixed by ``top_k=3``.
"""

from bangla_gpt_api.retrieval.bm25 import Hit

# Evidence characters a single generation prompt may carry. Non-binding for
# the bundled sample corpus (three to six chunks straddle ~4k chars), a hard
# guard for the real NCTB corpus and multi-chapter papers.
DEFAULT_MAX_EVIDENCE_CHARS = 9000


def trim_evidence_hits(
    hits: list[Hit],
    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> list[Hit]:
    """Keep top-ranked retrieval hits while sanitized text fits the budget.

    Greedy over the already-ranked list: the strongest hits survive, the
    tail is dropped whole (partial chunks would forge a citation that was
    never shown to the model). The first hit is always kept — an otherwise
    empty list would flip the generators into ``ProviderError`` for corpora
    whose single reachable chunk exceeds the budget.
    """
    kept: list[Hit] = []
    total = 0
    for hit in hits:
        length = len(hit.chunk.text)
        if kept and total + length > max_chars:
            break
        kept.append(hit)
        total += length
    return kept


def trim_evidence_texts(
    texts: list[str],
    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> list[str]:
    """The text-list form (question papers dedupe raw chunk texts first)."""
    kept: list[str] = []
    total = 0
    for text in texts:
        if kept and total + len(text) > max_chars:
            break
        kept.append(text)
        total += len(text)
    return kept
