"""S4.3 RAG v2 -- vector lane over embedder vectors (in-memory local backend).

The public ``search`` signature mirrors :meth:`BM25Index.search` so the two
lanes are interchangeable ranking sources for the fusion index. Corpus sizes
here (sample NCTB: hundreds of chunks) make brute-force cosine exact and
cheap; the pgvector backend for the real NCTB corpus is infrastructure
(🖐 human input, R8) and will implement the same contract server-side.
"""

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.retrieval.embedding import Embedder


def vector_text(chunk: Chunk) -> str:
    """Section-aware embed input: heading context + chunk body.

    Prefixing chapter/section turns 'who does this belong to' into the
    vector itself, so heading-level queries match paragraph chunks.
    """
    heading = " > ".join(p for p in (chunk.meta.chapter, chunk.meta.section) if p)
    return f"{heading}\n\n{chunk.text}" if heading else chunk.text


class VectorIndex:
    """Brute-force cosine search over L2-normalised embedder vectors."""

    def __init__(self, chunks: list[Chunk], embedder: Embedder) -> None:
        self.chunks = chunks
        self.embedder = embedder
        self.vectors = embedder.embed([vector_text(c) for c in chunks])

    def search(
        self,
        query: str,
        *,
        class_level: int | None = None,
        subject: str | None = None,
        chapter: str | None = None,
        top_k: int = 4,
        min_score: float = 0.0,
    ) -> list[Hit]:
        qv = self.embedder.embed([query])[0]
        hits: list[Hit] = []
        for chunk, vec in zip(self.chunks, self.vectors, strict=True):
            if class_level is not None and chunk.meta.class_level != class_level:
                continue
            if subject is not None and chunk.meta.subject != subject:
                continue
            if chapter is not None and chunk.meta.chapter != chapter:
                continue
            score = sum(a * b for a, b in zip(qv, vec, strict=True))
            if score > min_score:
                hits.append(Hit(chunk=chunk, score=round(score, 4)))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.id))
        return hits[:top_k]
