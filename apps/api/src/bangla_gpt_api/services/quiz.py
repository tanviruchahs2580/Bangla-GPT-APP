import hashlib
import random
import re
from collections import Counter
from dataclasses import dataclass

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import tokenize

_SENT_SPLIT = re.compile(r"(?<=[।.!?])\s+")
_WORD_RE = re.compile(r"^[\u0980-\u09FFA-Za-z]+$")

STOPWORDS = frozenset(
    {
        "এবং",
        "কিংবা",
        "অথবা",
        "তাই",
        "যে",
        "এই",
        "ঐ",
        "ও",
        "কী",
        "কি",
        "কেন",
        "হয়",
        "হবে",
        "করে",
        "করা",
        "বলে",
        "মানে",
        "প্রতি",
        "একটি",
        "একটা",
        "থেকে",
        "জন্য",
        "সঙ্গে",
        "সাথে",
        "ভাবে",
        "সব",
        "কোনো",
        "যদি",
        "মধ্যে",
    }
)


def _is_candidate(term: str) -> bool:
    if len(term) < 3 or term.isdigit() or term in STOPWORDS:
        return False
    return bool(_WORD_RE.match(term))


@dataclass
class GeneratedQuestion:
    id: str
    question_text: str
    options: list[str]
    answer_index: int
    chapter: str
    book: str

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "question_text": self.question_text,
            "options": list(self.options),
            "answer_index": self.answer_index,
            "chapter": self.chapter,
            "book": self.book,
        }


class ClozeQuizGenerator:
    """Deterministic cloze-question generator over curriculum chunks.

    Baseline quiz generation used until an LLM-backed generator with a
    validation gate is introduced. Questions blank a rare content term in a
    sentence; distractors are sampled deterministically from sibling chunks.
    """

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.chunk_terms: list[set[str]] = []
        self.df: Counter[str] = Counter()
        for chunk in chunks:
            terms = {t for t in tokenize(chunk.text) if _is_candidate(t)}
            self.chunk_terms.append(terms)
            self.df.update(terms)

    def generate(
        self,
        *,
        class_level: int,
        subject: str | None = None,
        chapter: str | None = None,
        num: int = 5,
        seed: int = 0,
    ) -> list[GeneratedQuestion]:
        rng = random.Random(seed)
        doc_indices = [
            i
            for i, chunk in enumerate(self.chunks)
            if chunk.meta.class_level == class_level
            and (subject is None or chunk.meta.subject == subject)
            and (chapter is None or chunk.meta.chapter == chapter)
        ]
        order = list(doc_indices)
        rng.shuffle(order)

        questions: list[GeneratedQuestion] = []
        used_terms: set[tuple[int, str]] = set()
        for i in order:
            if len(questions) >= num:
                break
            picked = self._best_cloze(i, exclude=used_terms)
            if picked is None:
                continue
            sentence, term = picked
            distractors = self._sample_distractors(rng, i, term, doc_indices)
            if distractors is None:
                continue
            used_terms.add((i, term))
            questions.append(self._build_question(i, sentence, term, distractors))

        # Second pass (A4): when one question per chunk cannot satisfy the
        # request, harvest additional distinct clozes from the same chunks so
        # short quizzes only happen when content genuinely runs out.
        if len(questions) < num:
            for i in order:
                if len(questions) >= num:
                    break
                for sentence, term in self._extra_clozes(i, used_terms):
                    if len(questions) >= num:
                        break
                    distractors = self._sample_distractors(rng, i, term, doc_indices)
                    if distractors is None or term in [
                        q.options[q.answer_index] for q in questions
                    ]:
                        continue
                    used_terms.add((i, term))
                    questions.append(self._build_question(i, sentence, term, distractors))
        return questions

    def _build_question(
        self, doc_index: int, sentence: str, term: str, distractors: list[str]
    ) -> GeneratedQuestion:
        chunk = self.chunks[doc_index]
        options = [term, *distractors]
        random.Random(f"{chunk.id}|{term}").shuffle(options)
        return GeneratedQuestion(
            id=hashlib.sha256(f"{chunk.id}|{term}".encode(), usedforsecurity=False).hexdigest()[
                :10
            ],
            question_text=f"রিক্তস্থানে সঠিক শব্দটি বসাও: {sentence.replace(term, '____', 1)}",
            options=options,
            answer_index=options.index(term),
            chapter=chunk.meta.chapter,
            book=chunk.meta.book,
        )

    def _extra_clozes(self, doc_index: int, used: set[tuple[int, str]]):
        """Yield additional (sentence, term) pairs not yet used for a chunk."""
        for sentence in _SENT_SPLIT.split(self.chunks[doc_index].text):
            candidates = [
                t
                for t in dict.fromkeys(tokenize(sentence))
                if t in self.chunk_terms[doc_index] and (doc_index, t) not in used
            ]
            if not candidates:
                continue
            term = min(candidates, key=lambda t: (self.df[t], -len(t)))
            replaced = sentence.replace(term, "____", 1)
            if replaced != sentence:
                yield replaced, term

    def _best_cloze(
        self, doc_index: int, exclude: set[tuple[int, str]] | None = None
    ) -> tuple[str, str] | None:
        best: tuple[float, str, str] | None = None
        for sentence in _SENT_SPLIT.split(self.chunks[doc_index].text):
            candidates = [
                t
                for t in dict.fromkeys(tokenize(sentence))
                if t in self.chunk_terms[doc_index]
                and (exclude is None or (doc_index, t) not in exclude)
            ]
            if not candidates:
                continue
            term = min(candidates, key=lambda t: (self.df[t], -len(t)))
            replaced = sentence.replace(term, "____", 1)
            if replaced == sentence:
                continue
            rank = self.df[term]
            if best is None or (rank, -len(term)) < (best[0], -len(best[2])):
                best = (float(rank), replaced, term)
        if best is None:
            return None
        return best[1], best[2]

    def _sample_distractors(
        self,
        rng: random.Random,
        doc_index: int,
        term: str,
        doc_indices: list[int],
    ) -> list[str] | None:
        pool = {
            t
            for j in doc_indices
            if j != doc_index
            for t in self.chunk_terms[j]
            if t != term and self.df[t] <= self.df[term] + 3
        }
        pool.discard(term)
        if len(pool) < 3:
            return None
        return rng.sample(sorted(pool), 3)


def dump_quiz(questions: list[GeneratedQuestion]) -> list[dict]:
    return [q.to_payload() for q in questions]
