"""A2-11 / A11-01: review sheets for teacher and native-speaker judgement.

Two review workflows share this module, because both are the same thing: an
operated queue of *machine-produced material* that only a human may certify.

1. **Synthetic golden items (A2-11).** Every item the generator built carries
   ``synthetic: true`` and is never presented as human-verified (A8-02). This
   module exports the review sheet a teacher fills in (verdict, corrected
   question, corrected expectation, comment), reads the filled sheet back with
   strict validation, and records verdicts in a ledger
   (``apps/api/eval/synthetic_review_ledger.json``) that the owner uses to
   decide when the set may be called teacher-reviewed. An item only leaves the
   ``synthetic`` state through that ledger -- there is no code path that marks
   it verified.

2. **Class-appropriateness sampling (A11-01).** A sample of real tutor answers
   (stratified by class level, distinct subjects preferred) exported with a
   teacher-style rubric whose coding rules live in
   ``docs/evaluation/class-appropriateness-rubric.md`` so two teachers code the
   same way. The export is the *input* to human judgement; no rubric score is
   computed here.

CSV is written as UTF-8 with a BOM: teachers open these files in Excel, which
mangles BOM-less UTF-8 Bangla.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

#: Verdicts a reviewer may record for a synthetic item.
VERDICTS = ("approve", "reject", "edit")

#: Answers longer than this are truncated in the appropriateness sheet; the
#: full text stays in the graded response, and a truncated cell is marked.
MAX_CELL_CHARS = 1500

_SYNTHETIC_COLUMNS = (
    "item_id",
    "class_level",
    "subject",
    "stratum",
    "split",
    "chapter",
    "section",
    "question",
    "expected",
    "verdict",
    "corrected_question",
    "corrected_expected",
    "review_comment",
    "reviewer",
    "reviewed_at",
)

_APPROPRIATENESS_COLUMNS = (
    "item_id",
    "class_level",
    "subject",
    "chapter",
    "question",
    "answer",
    "answer_truncated",
    "grade_level_verdict",
    "subject_match",
    "language_quality",
    "safety_ok",
    "notes",
    "reviewer",
    "reviewed_at",
)


def item_id(class_level: int, subject: str | None, question: str) -> str:
    """Stable, short identity for a golden item (same inputs -> same id)."""
    payload = f"{class_level}|{subject or ''}|{question}".encode()
    return hashlib.sha1(payload).hexdigest()[:12]  # noqa: S324 - identity, not security


def build_synthetic_rows(items: Iterable[dict]) -> list[dict[str, str]]:
    """One review row per synthetic item; human columns are deliberately blank."""
    rows: list[dict[str, str]] = []
    for item in items:
        if not item.get("synthetic"):
            continue
        rows.append(
            {
                "item_id": item_id(item["class_level"], item.get("subject"), item["question"]),
                "class_level": str(item["class_level"]),
                "subject": item.get("subject") or "",
                "stratum": item.get("stratum") or "",
                "split": item.get("split") or "",
                "chapter": item.get("chapter") or "",
                "section": item.get("section") or "",
                "question": item["question"],
                "expected": item.get("expect") or "",
                "verdict": "",
                "corrected_question": "",
                "corrected_expected": "",
                "review_comment": "",
                "reviewer": "",
                "reviewed_at": "",
            }
        )
    return rows


def write_sheet(rows: list[dict[str, str]], path: Path, columns: tuple[str, ...]) -> None:
    """Write a review sheet as UTF-8-with-BOM CSV (Excel renders Bangla)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def read_sheet(path: Path) -> list[dict[str, str]]:
    """Read a filled sheet back (accepts the BOM the writer adds)."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def validate_verdicts(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Validate the human columns of a filled sheet; raise on the first defect.

    Blank verdicts are pending, not errors. A recorded verdict must carry a
    reviewer name (an unattributable approval is not a review), must be one of
    :data:`VERDICTS`, and an ``edit`` must actually contain the correction.
    """
    decided: list[dict[str, str]] = []
    for line, row in enumerate(rows, start=2):  # header is line 1
        verdict = (row.get("verdict") or "").strip()
        if not verdict:
            continue
        if verdict not in VERDICTS:
            raise ValueError(f"line {line}: verdict {verdict!r} not in {VERDICTS}")
        if not (row.get("reviewer") or "").strip():
            raise ValueError(f"line {line}: verdict {verdict!r} without a reviewer name")
        if verdict == "edit" and not (
            (row.get("corrected_question") or "").strip()
            or (row.get("corrected_expected") or "").strip()
        ):
            raise ValueError(f"line {line}: verdict 'edit' carries no correction")
        decided.append(row)
    return decided


def apply_review_sheet(rows: list[dict[str, str]], ledger_path: Path) -> dict[str, Any]:
    """Merge a validated sheet into the review ledger; return the new state.

    The ledger is the only record of human review: it keeps every verdict with
    its reviewer and date, and the state counts are derived from it rather
    than maintained by hand.
    """
    decided = validate_verdicts(rows)
    ledger: dict[str, Any] = {"verdicts": {}}
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for row in decided:
        ledger["verdicts"][row["item_id"]] = {
            "verdict": row["verdict"].strip(),
            "reviewer": row["reviewer"].strip(),
            "reviewed_at": (row.get("reviewed_at") or "").strip(),
            "corrected_question": (row.get("corrected_question") or "").strip() or None,
            "corrected_expected": (row.get("corrected_expected") or "").strip() or None,
            "comment": (row.get("review_comment") or "").strip() or None,
        }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return ledger_state(ledger)


def ledger_state(ledger: dict[str, Any]) -> dict[str, int]:
    """Counts by verdict from a ledger payload."""
    counts = {verdict: 0 for verdict in VERDICTS}
    for entry in ledger.get("verdicts", {}).values():
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
    return counts


def queue_priority(items: Iterable[dict]) -> list[dict]:
    """Synthetic items in the order the review queue works them.

    Priority, documented in ``docs/evaluation/synthetic-item-review.md``:
    must-refuse items first (they carry the abstention claims), then section
    glosses (the definition stratum the generator leans on), then contextual
    items; ties keep the golden file's order, so two reviewers get the same
    queue.
    """
    order = {"refuse": 0, "definition": 1, "contextual": 2}

    def sort_key(positioned: tuple[int, dict]) -> tuple[int, int, int]:
        position, item = positioned
        if item.get("expect") == "refuse":
            rank = order["refuse"]
        else:
            rank = order.get(str(item.get("stratum") or ""), 3)
        return (rank, int(item.get("class_level") or 0), position)

    synthetic = [(i, item) for i, item in enumerate(items) if item.get("synthetic")]
    return [item for _position, item in sorted(synthetic, key=sort_key)]


def build_appropriateness_rows(answers: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Rows for the class-appropriateness sheet from real (question, answer) pairs.

    ``answers`` entries: ``{"class_level", "subject", "chapter", "question",
    "answer"}``. The graded columns are left blank -- the sheet is the input to
    a teacher's judgement, and a machine-scored substitute would be exactly the
    fabrication the audit is looking for.
    """
    rows: list[dict[str, str]] = []
    for entry in answers:
        answer = str(entry.get("answer") or "")
        rows.append(
            {
                "item_id": item_id(
                    int(entry["class_level"]), entry.get("subject"), str(entry["question"])
                ),
                "class_level": str(entry["class_level"]),
                "subject": entry.get("subject") or "",
                "chapter": entry.get("chapter") or "",
                "question": str(entry["question"]),
                "answer": answer[:MAX_CELL_CHARS],
                "answer_truncated": "yes" if len(answer) > MAX_CELL_CHARS else "no",
                "grade_level_verdict": "",
                "subject_match": "",
                "language_quality": "",
                "safety_ok": "",
                "notes": "",
                "reviewer": "",
                "reviewed_at": "",
            }
        )
    return rows


def pick_appropriateness_sample(
    items: list[dict], *, per_class: int = 6, classes: tuple[int, ...] = (6, 7, 8, 9, 10)
) -> list[dict]:
    """Deterministic sample: up to ``per_class`` answerable items per class.

    Subjects are round-robined within each class so a 30-answer sample cannot
    be one subject, and items without a section (the must-refuse family) are
    excluded -- this sheet judges answers, and refusals have their own review
    path.
    """
    picked: list[dict] = []
    for class_level in classes:
        pool = [
            item
            for item in items
            if item["expect"] == "answer" and item["class_level"] == class_level
        ]
        by_subject: dict[str, list[dict]] = {}
        for item in pool:
            by_subject.setdefault(item.get("subject") or "", []).append(item)
        subjects = sorted(by_subject)
        cursor = 0
        taken: list[dict] = []
        while len(taken) < per_class:
            progressed = False
            for subject in subjects:
                group = by_subject[subject]
                if cursor < len(group) and len(taken) < per_class:
                    taken.append(group[cursor])
                    progressed = True
            if not progressed:
                break
            cursor += 1
        picked.extend(taken)
    return picked


async def run_appropriateness_sample(
    tutor: Any, items: list[dict], *, per_class: int = 6
) -> list[dict[str, str]]:
    """Ask the tutor the sampled questions and build the sheet rows."""
    answers: list[dict[str, Any]] = []
    for item in pick_appropriateness_sample(items, per_class=per_class):
        response = await tutor.ask(
            item["question"], item["class_level"], item.get("subject") or None
        )
        answers.append(
            {
                "class_level": item["class_level"],
                "subject": item.get("subject"),
                "chapter": item.get("chapter"),
                "question": item["question"],
                "answer": getattr(response, "answer", ""),
            }
        )
    return build_appropriateness_rows(answers)


#: Column names exported for each workflow, so callers do not repeat them.
SYNTHETIC_COLUMNS = _SYNTHETIC_COLUMNS
APPROPRIATENESS_COLUMNS = _APPROPRIATENESS_COLUMNS
