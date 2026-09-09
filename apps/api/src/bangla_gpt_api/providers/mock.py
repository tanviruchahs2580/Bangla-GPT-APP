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

    async def generate(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> str:
        # Wave 2: `image` is accepted for protocol parity. The mock provider
        # cannot see images; chat routes refuse vision turns for mock mode
        # BEFORE calling here (services/tutor.VISION_UNSUPPORTED_ANSWER), so
        # an image silently reaching this method never claims understanding.
        # AUD-01: never echo `system` (internal prompt) or raw markup back to users.
        # For grounded prompts, quote the retrieved textbook evidence cleanly in the
        # sectioned layout SYSTEM_PROMPT rule ৬ asks for (golden sample for tests).
        # S2.3: the content-engine contract expects one JSON payload with the
        # seven section keys; answer it deterministically from the evidence.
        from bangla_gpt_api.services.generators.answer_key import (
            ANSWER_KEY_JSON_MARKER,
        )
        from bangla_gpt_api.services.generators.chapter_content import (
            CONTENT_JSON_MARKER,
        )
        from bangla_gpt_api.services.generators.homework import HOMEWORK_JSON_MARKER
        from bangla_gpt_api.services.generators.lesson_plan import (
            LESSON_JSON_MARKER,
        )
        from bangla_gpt_api.services.generators.question_paper import (
            QP_JSON_MARKER,
        )
        from bangla_gpt_api.services.generators.rubric import RUBRIC_JSON_MARKER
        from bangla_gpt_api.services.generators.worksheet import WORKSHEET_JSON_MARKER

        if CONTENT_JSON_MARKER in prompt:
            return self._content_json(prompt)
        if LESSON_JSON_MARKER in prompt:
            return self._lesson_json(prompt)
        if QP_JSON_MARKER in prompt:
            return self._qp_json(prompt)
        # Wave 1 generic teacher generators (existing replies stay untouched).
        if WORKSHEET_JSON_MARKER in prompt:
            return self._worksheet_json(prompt)
        if ANSWER_KEY_JSON_MARKER in prompt:
            return self._answer_key_json(prompt)
        if HOMEWORK_JSON_MARKER in prompt:
            return self._homework_json(prompt)
        if RUBRIC_JSON_MARKER in prompt:
            return self._rubric_json(prompt)
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

    # ── Wave 1 generic teacher generators ────────────────────────────────
    # Every reply echoes the Target line's subject/class_level so the
    # generators' validation gate ("payload echoes the request") holds, and
    # every content string is derived from the <evidence> sentences the
    # prompt already carries (deterministic, corpus-grounded, safe).

    @staticmethod
    def _sentences(prompt: str) -> list[str]:
        evidences = _EVIDENCE_RE.findall(prompt)
        sentences = [s.strip() for e in evidences for s in _SENTENCE_RE.split(e) if s.strip()]
        return sentences or ["মক কনটেন্ট বাক্য।", "দ্বিতীয় মক বাক্য।"]

    @staticmethod
    def _target(prompt: str) -> tuple[int, str, str]:
        m = re.search(r"Target: class_level=(\d+), subject=([^,\n]+), chapter=([^\n]+)", prompt)
        if m is None:
            return 6, "science", "নতুন অধয়ায়"
        return int(m.group(1)), m.group(2).strip(), m.group(3).strip().rstrip(".")

    def _mcq(self, sentences: list[str], i: int, marks: int = 1) -> dict:
        base = sentences[i % len(sentences)]
        return {
            "text": f"{base} — প্রশ্ন {i + 1}?",
            "options": [sentences[(i + k) % len(sentences)] for k in range(4)],
            "answer_index": i % 4,
            "marks": marks,
        }

    def _worksheet_json(self, prompt: str) -> str:
        """Deterministic three-tier worksheet for the wave-1 contract."""
        s = self._sentences(prompt)
        class_level, subject, chapter = self._target(prompt)
        tiers: list[dict] = []
        answer_sheet: list[dict] = []
        q_no = 0
        for tier in ("basic", "intermediate", "advanced"):
            questions = [self._mcq(s, q_no + j) for j in range(2)]
            for j, q in enumerate(questions):
                answer_sheet.append(
                    {
                        "ref": f"{tier}-{j + 1}",
                        "answer_index": q["answer_index"],
                        "answer": q["options"][q["answer_index"]],
                    }
                )
            q_no += 2
            tiers.append({"tier": tier, "questions": questions})
        return json.dumps(
            {
                "subject": subject,
                "class_level": class_level,
                "chapter": chapter,
                "tiers": tiers,
                "answer_sheet": answer_sheet,
            },
            ensure_ascii=False,
        )

    def _answer_key_json(self, prompt: str) -> str:
        """Per-question answers for the wave-1 answer-key contract.

        ``QUESTIONS_N=<n>`` in the prompt fixes how many answers to emit.
        """
        s = self._sentences(prompt)
        class_level, subject, chapter = self._target(prompt)
        m = re.search(r"QUESTIONS_N=(\d+)", prompt)
        n = int(m.group(1)) if m else 3
        answers = [
            {
                "ref": f"q{i + 1}",
                "answer": f"{s[i % len(s)]}",
                "detailed_solution": f"ধাপ ১: {s[i % len(s)]} ধাপ ২: সঠিক উত্তর নির্বাচন ও যাচাই।",
                "marks": 1,
            }
            for i in range(n)
        ]
        return json.dumps(
            {
                "subject": subject,
                "class_level": class_level,
                "chapter": chapter,
                "answers": answers,
                "marking_guide": {
                    "total_marks": n,
                    "per_mark_note": "প্ৰতয়টি ধাপ স্পষ্ট হলে পূর্ণ নম্বর।",
                },
            },
            ensure_ascii=False,
        )

    def _homework_json(self, prompt: str) -> str:
        """Assignment brief for the wave-1 homework contract."""
        s = self._sentences(prompt)
        class_level, subject, chapter = self._target(prompt)
        return json.dumps(
            {
                "subject": subject,
                "class_level": class_level,
                "chapter": chapter,
                "items": [f"অনুশীলন {i + 1}: {s[i % len(s)]}" for i in range(3)],
                "instructions": "খাতা পৰিষ়ার লিখে, নিজের ভাষায় উত্তর দাও।",
                "due_suggestion": "পরের দিনের ক্লাসের আগে জমা দাও।",
                "parent_note": "আজকের হোমওয়ার্কটি শিশু নিজে লিক্বে; আপনাব শুধু দেখবেন সে লিখেছ্যে কি না।",
                "estimated_minutes": 25,
            },
            ensure_ascii=False,
        )

    def _rubric_json(self, prompt: str) -> str:
        """Criteria rubric for the wave-1 rubric contract (total 10 marks)."""
        s = self._sentences(prompt)
        class_level, subject, chapter = self._target(prompt)
        criteria_names = ("ধারণা বোঝা", "উদাহরণ ও প্রয়োগ", "উপস্থাপন")
        marks = (4, 3, 3)
        criteria = [
            {
                "name": name,
                "max_marks": m,
                "levels": {
                    "excellent": f"{name}: পূর্ণ ধারণা ও নিজের ভাষায় ব্যাখ্যা ({m})",
                    "good": f"{name}: আংশিক ধারণা, ছোট ভুল {s[i % len(s)]}",
                    "needs_improvement": f"{name}: ধারণা স্পষ্ট নয়, আবার পড়তে হবে",
                },
            }
            for i, (name, m) in enumerate(zip(criteria_names, marks, strict=True))
        ]
        return json.dumps(
            {
                "subject": subject,
                "class_level": class_level,
                "chapter": chapter,
                "criteria": criteria,
                "total_marks": sum(marks),
            },
            ensure_ascii=False,
        )

    async def stream(
        self, prompt: str, *, system: str | None = None, image: dict | None = None
    ) -> AsyncIterator[str]:
        """Yield the mock answer in small chunks to exercise SSE consumers."""
        answer = await self.generate(prompt, system=system, image=image)
        for i in range(0, len(answer), _CHUNK_SIZE):
            yield answer[i : i + _CHUNK_SIZE]
