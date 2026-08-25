from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalQuestion:
    question: str
    class_level: int
    subject: str | None
    expected_grounded: bool
    note: str = ""


@dataclass
class EvalResult:
    total: int
    matched: int
    accuracy: float
    failures: list[dict]


async def evaluate_questions(service, questions: list[EvalQuestion]) -> EvalResult:
    matched = 0
    failures: list[dict] = []
    for item in questions:
        answer = await service.ask(item.question, item.class_level, item.subject)
        ok = answer.grounded is item.expected_grounded
        if ok:
            matched += 1
        else:
            failures.append(
                {
                    "question": item.question,
                    "expected_grounded": item.expected_grounded,
                    "got_grounded": answer.grounded,
                    "note": item.note,
                }
            )
    accuracy = round(matched / len(questions), 4) if questions else 0.0
    return EvalResult(total=len(questions), matched=matched, accuracy=accuracy, failures=failures)
