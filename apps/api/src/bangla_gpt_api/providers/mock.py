import json
import re
from collections.abc import AsyncIterator

from bangla_gpt_api.services.answer_structure import (
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)

_CHUNK_SIZE = 48

_EVIDENCE_RE = re.compile(r"<evidence>(.*?)</evidence>", re.DOTALL)
_SENTENCE_RE = re.compile(r"[।\n]+")


class MockLLMProvider:
    name = "mock"

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        # AUD-01: never echo `system` (internal prompt) or raw markup back to users.
        # For grounded prompts, quote the retrieved textbook evidence cleanly in the
        # sectioned layout SYSTEM_PROMPT rule ৬ asks for (golden sample for tests).
        # S2.3: the content-engine contract expects one JSON payload with the
        # seven section keys; answer it deterministically from the evidence.
        from bangla_gpt_api.services.generators.chapter_content import (
            CONTENT_JSON_MARKER,
        )
        from bangla_gpt_api.services.generators.lesson_plan import (
            LESSON_JSON_MARKER,
        )
        from bangla_gpt_api.services.generators.question_paper import (
            QP_JSON_MARKER,
        )

        if CONTENT_JSON_MARKER in prompt:
            return self._content_json(prompt)
        if LESSON_JSON_MARKER in prompt:
            return self._lesson_json(prompt)
        if QP_JSON_MARKER in prompt:
            return self._qp_json(prompt)
        evidences = _EVIDENCE_RE.findall(prompt)
        if evidences:
            blocks = [e.strip() for e in evidences[:2]]
            sentences = [s.strip() for b in blocks for s in _SENTENCE_RE.split(b) if s.strip()]
            simple = sentences[0]
            if SHORT_ANSWER_INSTRUCTION in prompt:
                # S1.13 low-data mode: one short sentence only (measurable payload cut).
                return f"[mock] {SECTION_SIMPLE} {simple}"
            example = sentences[1] if len(sentences) > 1 else sentences[0]
            bullets = "\n".join(f"- {s}" for s in sentences[: min(4, len(sentences))])
            return (
                f"[mock] {SECTION_SIMPLE} {simple}\n"
                f"{SECTION_EXAMPLE} {example}\n"
                f"{SECTION_POINTS}\n{bullets}\n"
                f"{SECTION_CHECK} এই অংশটটা আরও সহজ ভাবো বলবো?"
            )
        return f"[mock] {prompt}"

    def _content_json(self, prompt: str) -> str:
        """Deterministic seven-section payload for the S2.3 content contract."""
        evidences = _EVIDENCE_RE.findall(prompt)
        sentences = [s.strip() for e in evidences for s in _SENTENCE_RE.split(e) if s.strip()]
        if not sentences:
            sentences = [f"mock: {prompt.strip().splitlines()[0][:80]}"]

        def pick(i: int) -> str:
            return sentences[i % len(sentences)]

        payload = {
            "summary": pick(0),
            "notes": " ".join(sentences[:3]),
            "key_points": [pick(i) for i in range(3)],
            "examples": [pick(1)],
            "practice_qs": [f"[mock] {pick(2)}?", f"[mock] {pick(3)}?"],
            "homework": [f"[mock] {pick(4)}"],
            "exam_tips": [f"[mock] {pick(5)}"],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _lesson_json(self, prompt: str) -> str:
        """Deterministic eight-section plan for the S2.6 lesson contract."""
        evidences = _EVIDENCE_RE.findall(prompt)
        sentences = [s.strip() for e in evidences for s in _SENTENCE_RE.split(e) if s.strip()]
        if not sentences:
            sentences = [f"mock: {prompt.strip().splitlines()[0][:80]}"]

        def pick(i: int) -> str:
            return sentences[i % len(sentences)]

        m = re.search(r"minutes=(\d+), level=(\w+)", prompt)
        minutes, level = (m.group(1), m.group(2)) if m else ("35", "average")
        payload = {
            "objective": f"পাঠ্যবস্তু বুঝে বলা (level={level}): {pick(0)}",
            "previous_knowledge": f"আগের পাঠ মনে করানো: {pick(1)}",
            "introduction": f"প্রশ্ন করে সূচনা: {pick(2)}?",
            "main_explanation": "\n".join(pick(i) for i in range(3)),
            "activity": f"দলে করে কাজ: {pick(3)}",
            "questions": f"{pick(4)}?\n{pick(5)}?",
            "assessment": f"মৌখিক প্রশ্ন ও মিলানো ({minutes} মিনিটের পাঠ)",
            "homework": f"পাঠ্যবই থেকে অনুশীলন: {pick(6)}",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _qp_json(self, prompt: str) -> str:
        """Deterministic question set obeying the S2.4 SPEC line (mock provider)."""
        evidences = _EVIDENCE_RE.findall(prompt)
        sentences = [s.strip() for e in evidences for s in _SENTENCE_RE.split(e) if s.strip()]
        if not sentences:
            sentences = [f"mock-prashna {i}" for i in range(4)]
        m = re.search(r"SPEC: easy=(\d+) medium=(\d+) hard=(\d+) chapters=([^\n]+)", prompt)
        if m is None:
            counts, chapters = {"easy": 2, "medium": 2, "hard": 1}, [""]
        else:
            counts = {
                "easy": int(m.group(1)),
                "medium": int(m.group(2)),
                "hard": int(m.group(3)),
            }
            chapters = [c for c in m.group(4).strip().split("|") if c]
        questions: list[dict] = []
        i = 0
        for label in ("easy", "medium", "hard"):
            for _ in range(counts[label]):
                base = sentences[i % len(sentences)]
                questions.append(
                    {
                        "text": f"{base} — প্রশ্ন {i + 1}?",
                        "options": [sentences[(i + k) % len(sentences)] for k in range(4)],
                        "answer_index": i % 4,
                        "difficulty": label,
                        "chapter": chapters[i % len(chapters)] if chapters else "",
                    }
                )
                i += 1
        return json.dumps({"questions": questions}, ensure_ascii=False)

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        """Yield the mock answer in small chunks to exercise SSE consumers."""
        answer = await self.generate(prompt, system=system)
        for i in range(0, len(answer), _CHUNK_SIZE):
            yield answer[i : i + _CHUNK_SIZE]
