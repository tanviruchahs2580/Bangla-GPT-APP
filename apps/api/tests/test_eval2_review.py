"""A2-11 / A11-01: review-sheet export, validation and the documented queue.

The sheet is the only route from "machine-produced" to "human-reviewed" for
synthetic items, and the class-appropriateness sheet is the input to a
teacher's judgement -- so the tests here are about the queue's integrity: no
verdict without a reviewer, no unattributed approval, no lost Bangla, and a
sample that cannot be one class or one subject.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation import review_sheet
from bangla_gpt_api.evaluation.cli import _export_synthetic_sheet
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService

API_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = API_ROOT / "eval" / "golden_v2.json"
RUBRIC_DOC = API_ROOT.parent.parent / "docs" / "evaluation" / "class-appropriateness-rubric.md"


def _items() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["items"]


def test_synthetic_rows_cover_every_synthetic_item_with_blank_human_columns() -> None:
    items = _items()
    rows = review_sheet.build_synthetic_rows(items)
    # the count is the artifact's, not a constant: the golden set is
    # versioned and a revision changes it (A8-08, 2026-10-21: 646 -> 643)
    assert len(rows) == sum(1 for item in items if item["synthetic"])
    ids = [row["item_id"] for row in rows]
    assert len(set(ids)) == len(ids), "item ids must be unique"
    for row in rows:
        assert row["question"]
        assert row["expected"] in {"answer", "refuse"}
        for human in ("verdict", "reviewer", "reviewed_at", "review_comment"):
            assert row[human] == "", "the machine must not pre-fill human columns"


def test_sheet_round_trips_bangla_through_excel_compatible_csv(tmp_path: Path) -> None:
    rows = review_sheet.build_synthetic_rows(_items()[:3])
    path = tmp_path / "sheet.csv"
    review_sheet.write_sheet(rows, path, review_sheet.SYNTHETIC_COLUMNS)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Excel needs the BOM to read Bangla"
    back = review_sheet.read_sheet(path)
    assert back[0]["question"] == rows[0]["question"]
    assert back[0]["chapter"] == rows[0]["chapter"]


def test_verdict_validation_rejects_unattributable_and_incomplete_rows() -> None:
    rows = review_sheet.build_synthetic_rows(_items()[:2])
    assert review_sheet.validate_verdicts(rows) == [], "blank verdicts are pending, not errors"
    rows[0].update({"verdict": "maybe", "reviewer": "teacher"})
    with pytest.raises(ValueError, match="not in"):
        review_sheet.validate_verdicts(rows)
    rows[0].update({"verdict": "approve", "reviewer": "  "})
    with pytest.raises(ValueError, match="without a reviewer name"):
        review_sheet.validate_verdicts(rows)
    rows[0].update({"verdict": "edit", "reviewer": "teacher"})
    with pytest.raises(ValueError, match="no correction"):
        review_sheet.validate_verdicts(rows)
    rows[0].update({"corrected_question": "নতুন প্রশ্ন?"})
    decided = review_sheet.validate_verdicts(rows)
    assert len(decided) == 1


def test_applying_a_sheet_merges_into_a_ledger_without_losing_history(tmp_path: Path) -> None:
    rows = review_sheet.build_synthetic_rows(_items()[:3])
    ledger_path = tmp_path / "ledger.json"
    rows[0].update({"verdict": "approve", "reviewer": "শিক্ষক আরিফ", "reviewed_at": "2026-10-20"})
    rows[1].update({"verdict": "reject", "reviewer": "শিক্ষক আরিফ", "review_comment": "duplicate"})
    state = review_sheet.apply_review_sheet(rows, ledger_path)
    assert state == {"approve": 1, "reject": 1, "edit": 0}
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["verdicts"][rows[0]["item_id"]]["reviewer"] == "শিক্ষক আরিফ"
    # a second, later verdict on the same item replaces it (the ledger is current
    # state; the sheet remains the audit trail of what was submitted)
    rows[1].update({"verdict": "approve", "reviewer": "another reviewer"})
    state = review_sheet.apply_review_sheet(rows, ledger_path)
    assert state == {"approve": 2, "reject": 0, "edit": 0}


def test_export_queue_skips_decided_items_and_orders_by_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = _items()
    ledger_path = tmp_path / "ledger.json"
    sheet = tmp_path / "decided.csv"
    rows = review_sheet.build_synthetic_rows(items[:2])
    rows[0].update({"verdict": "approve", "reviewer": "t"})
    review_sheet.apply_review_sheet(rows, ledger_path)

    from bangla_gpt_api.evaluation import cli as eval_cli

    monkeypatch.setattr(
        eval_cli,
        "defaults",
        lambda: {"synthetic_sheet": sheet, "review_ledger": ledger_path},
    )
    assert (
        _export_synthetic_sheet(argparse.Namespace(export_synthetic_sheet=str(sheet)), API_ROOT)
        == 0
    )
    exported = review_sheet.read_sheet(sheet)
    assert len(exported) == len(items) - 1, "the one reviewed item must leave the queue"
    assert rows[0]["item_id"] not in {row["item_id"] for row in exported}
    assert exported[0]["expected"] == "refuse", "must-refuse items are worked first"


def test_queue_priority_is_stable_and_documented() -> None:
    ordered = review_sheet.queue_priority(_items())
    ranks = [
        (
            0
            if item["expect"] == "refuse"
            else {"definition": 1, "contextual": 2}.get(item["stratum"], 3)
        )
        for item in ordered
    ]
    assert ranks == sorted(ranks)
    assert len(ordered) == len(_items())


def test_appropriateness_sample_is_stratified_and_deterministic() -> None:
    items = _items()
    picked = review_sheet.pick_appropriateness_sample(items)
    assert len(picked) == 30, "the spec's 30-answer sample"
    by_class: dict[int, list[dict]] = {}
    for item in picked:
        by_class.setdefault(item["class_level"], []).append(item)
    assert set(by_class) == {6, 7, 8, 9, 10}
    for class_level, group in by_class.items():
        assert len(group) == 6, f"class {class_level} must contribute 6"
        available = {
            item["subject"]
            for item in items
            if item["expect"] == "answer" and item["class_level"] == class_level
        }
        assert {item["subject"] for item in group} == available, (
            f"class {class_level} must cover every subject it has"
        )
    assert review_sheet.pick_appropriateness_sample(items) == picked
    assert all(item["expect"] == "answer" for item in picked)


def test_appropriateness_rows_mark_truncation_and_leave_grades_blank() -> None:
    rows = review_sheet.build_appropriateness_rows(
        [
            {
                "class_level": 6,
                "subject": "science",
                "chapter": "কোষ",
                "question": "?",
                "answer": "ক" * 2000,
            },
            {"class_level": 7, "subject": "math", "chapter": None, "question": "?", "answer": "খ"},
        ]
    )
    assert rows[0]["answer_truncated"] == "yes"
    assert len(rows[0]["answer"]) == review_sheet.MAX_CELL_CHARS
    assert rows[1]["answer_truncated"] == "no"
    for row in rows:
        for graded in ("grade_level_verdict", "subject_match", "language_quality", "safety_ok"):
            assert row[graded] == ""


async def test_end_to_end_appropriateness_sheet_uses_real_answers() -> None:
    from bangla_gpt_api.config import Settings

    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    tutor = TutorService(index=index, provider=MockLLMProvider(), fast_provider=None)
    rows = await review_sheet.run_appropriateness_sample(tutor, _items(), per_class=2)
    assert len(rows) == 10
    assert all(row["answer"].strip() for row in rows), "every row is a real answer"
    assert all(row["reviewer"] == "" for row in rows), "nobody has judged these yet"


def test_rubric_document_states_every_graded_column() -> None:
    text = RUBRIC_DOC.read_text(encoding="utf-8")
    for column in ("grade_level_verdict", "subject_match", "language_quality", "safety_ok"):
        assert f"`{column}`" in text, f"the rubric must define {column}"
