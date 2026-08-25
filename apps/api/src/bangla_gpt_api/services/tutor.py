from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
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
        min_score: float = 1.5,
        top_k: int = 3,
    ) -> None:
        self.index = index
        self.provider = provider
        self.min_score = min_score
        self.top_k = top_k

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
        if not hits or hits[0].score < self.min_score:
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
