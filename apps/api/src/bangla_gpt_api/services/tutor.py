from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index, tokenize
from bangla_gpt_api.schemas import AskResponse, SourceRef

INSUFFICIENT_EVIDENCE_ANSWER = (
    "উত্তরটি পাঠ্যবইয়ের বিষয়বস্তুর ভিত্তিতে দেওয়া সম্ভব নয়। অনুগ্রহ করে পাঠ্যবইয়ের সংশ্লিষ্ট অধ্যায় থেকে প্রশ্ন করুন।"
)

SYSTEM_PROMPT = (
    "তুমি একজন বাংলা মাধ্যমের শিক্ষক। শুধুমাত্র প্রদত্ত পাঠ্যবইয়ের অংশ "
    "থেকে উত্তর দাও। প্রদত্ত অংশে উত্তর না থাকলে স্পষ্ট বলো যে উত্তরটি "
    "পাঠ্যবইয়ে নেই।"
)


class TutorService:
    def __init__(
        self,
        index: BM25Index,
        provider: LLMProvider,
        *,
        min_score: float = 0.0,
        min_coverage: float = 0.5,
        top_k: int = 3,
    ) -> None:
        self.index = index
        self.provider = provider
        # Absolute BM25 floors do NOT transfer across corpus sizes (verified
        # on the real NCTB corpus); the grounding gate therefore requires
        # that a sufficient fraction of query terms appear in the evidence.
        self.min_score = min_score
        self.min_coverage = min_coverage
        self.top_k = top_k

    def _grounded(self, question: str, top_score: float | None, top_text: str) -> bool:
        if top_score is None or top_score <= self.min_score or not top_text:
            return False
        query_terms = {t for t in tokenize(question) if len(t) >= 2}
        if not query_terms:
            return False
        evidence_terms = set(tokenize(top_text))
        coverage = sum(1 for t in query_terms if t in evidence_terms) / len(query_terms)
        return coverage >= self.min_coverage

    async def ask(
        self,
        question: str,
        class_level: int,
        subject: str | None = None,
    ) -> AskResponse:
        hits = self.index.search(
            question,
            class_level=class_level,
            subject=subject,
            top_k=self.top_k,
        )
        top_score = hits[0].score if hits else None
        top_text = hits[0].chunk.text if hits else ""
        if not self._grounded(question, top_score, top_text):
            return AskResponse(
                answer=INSUFFICIENT_EVIDENCE_ANSWER,
                grounded=False,
                sources=[],
            )
        context = "\n---\n".join(hit.chunk.text for hit in hits)
        prompt = f"পাঠ্যবইয়ের অংশ:\n{context}\n\nপ্রশ্ন: {question}"
        answer = await self.provider.generate(prompt, system=SYSTEM_PROMPT)
        sources = [
            SourceRef(
                book=hit.chunk.meta.book,
                chapter=hit.chunk.meta.chapter,
                section=hit.chunk.meta.section,
                page=hit.chunk.meta.page,
                score=hit.score,
            )
            for hit in hits
        ]
        return AskResponse(answer=answer, grounded=True, sources=sources)
