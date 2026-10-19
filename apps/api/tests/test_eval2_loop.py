"""A8-09: the online loop -- feedback joined to a trace becomes an eval item.

The end-to-end case is the audit's required demonstration: a real tutor turn in
a real (throwaway) database, thumbs-down feedback, a captured trace line, and
a candidate eval item whose joined trace is asserted field by field. The rest
pin the triage validation and the privacy property of the gap backlog.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from types import ModuleType

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.evaluation import online_loop as logic

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_loop.py"
SECRET = "-".join(("eval2", "loop", "fixture") * 3)
PASSWORD = "StrongPass123!"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_loop", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _TraceCapture(logging.Handler):
    """Capture trace records exactly as an operator's log sink would."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record) -> None:  # noqa: ANN001
        self.lines.append(record.getMessage())


def test_trace_reader_ignores_noise_and_keeps_trace_records(tmp_path: Path) -> None:
    module = logic
    log = tmp_path / "trace.log"
    log.write_text(
        "\n".join(
            [
                "gunicorn starting",
                '{"event": "access", "status": 200}',
                "not json at all",
                '{"event": "trace", "stage": "retrieval", "retrieved_ids": ["a"]}',
                '{"event": "trace", "stage": "generation", "prompt_tokens": 5}',
            ]
        ),
        encoding="utf-8",
    )
    records = module.load_trace_log(log)
    assert [record["stage"] for record in records] == ["retrieval", "generation"]
    assert module.load_trace_log(tmp_path / "absent.log") == []


def test_fingerprint_and_split_are_deterministic() -> None:
    module = logic
    question = "সালোকসংশ্লেষণ কী?"
    assert module.question_fingerprint(question) == module.question_fingerprint(question + " ")
    assert module.split_of(question) in {"dev", "test"}
    assert module.split_of(question) == module.split_of(question)


def test_gap_backlog_is_privacy_safe_and_grouped() -> None:
    module = logic
    traces = [
        {"stage": "retrieval", "coverage": 0.2, "class_level": 6, "retrieved_ids": ["c1"]},
        {"stage": "retrieval", "coverage": 0.1, "class_level": 6, "retrieved_ids": ["c2"]},
        {"stage": "retrieval", "coverage": 0.9, "class_level": 6, "retrieved_ids": ["c1"]},
        {"stage": "generation", "coverage": 0.1, "class_level": 6},
    ]
    backlog = module.gap_backlog(
        traces, {"c1": ("কোষ", "কোষ কী", 1), "c2": ("বল", "বল কাকে বলে", 2)}
    )
    assert backlog["low_coverage_traces"] == 2
    # sorted by (class_level, chapter) -- code-point order, so কোষ precedes বল
    assert backlog["rows"] == [
        {"class_level": 6, "chapter": "কোষ", "count": 1, "mean_coverage": 0.2},
        {"class_level": 6, "chapter": "বল", "count": 1, "mean_coverage": 0.1},
    ]
    for row in backlog["rows"]:
        assert set(row) == {"class_level", "chapter", "count", "mean_coverage"}
    serialized = json.dumps(backlog, ensure_ascii=False)
    assert "সালোকসংশ্লেষণ" not in serialized, "no question text in the backlog"


def test_triage_turns_decided_candidates_into_golden_shaped_items() -> None:
    module = logic
    candidates = [
        {
            "candidate_id": "fb1",
            "question": "কোষ কী?",
            "class_level": 6,
            "subject": None,
            "chapter": "কোষ",
            "provenance": {"kind": "student_feedback", "feedback_id": 1},
        },
        {
            "candidate_id": "fb2",
            "question": "ক্রিকেট কত বল?",
            "class_level": 7,
            "subject": None,
            "chapter": None,
            "provenance": {"kind": "student_feedback", "feedback_id": 2},
        },
    ]
    decisions = {
        "candidates": [
            {
                "candidate_id": "fb1",
                "verdict": "accept",
                "answerability": "in_corpus",
                "reviewer": "teacher",
            },
            {
                "candidate_id": "fb2",
                "verdict": "reject",
                "answerability": "out_of_corpus",
                "reviewer": "teacher",
            },
        ]
    }
    approved, rejected, problems = module.triage_candidates(candidates, decisions)
    assert problems == []
    assert len(approved) == 1 and len(rejected) == 1
    item = approved[0]
    assert item["expect"] == "answer" and item["answerability"] == "in_corpus"
    assert item["stratum"] == "feedback" and item["synthetic"] is False
    assert item["provenance"]["feedback_id"] == 1
    assert item["split"] in {"dev", "test"}


def test_triage_rejects_bad_decisions_loudly() -> None:
    module = logic
    candidates = [
        {
            "candidate_id": "fb1",
            "question": "কোষ কী?",
            "class_level": 6,
            "subject": None,
            "chapter": "কোষ",
            "provenance": {},
        }
    ]
    cases = {
        "no such candidate": {"candidate_id": "fb9", "verdict": "accept", "reviewer": "t"},
        "bad verdict": {"candidate_id": "fb1", "verdict": "maybe", "reviewer": "t"},
        "no reviewer": {"candidate_id": "fb1", "verdict": "accept", "reviewer": ""},
        "no answerability": {"candidate_id": "fb1", "verdict": "accept", "reviewer": "t"},
    }
    for expected, decision in cases.items():
        approved, _rejected, problems = module.triage_candidates(
            candidates, {"candidates": [decision]}
        )
        assert problems, expected
        assert not approved


def test_end_to_end_feedback_becomes_a_traced_candidate(tmp_path: Path) -> None:
    """The audit's required trace: tutor turn -> thumbs down -> candidate item."""
    from fastapi.testclient import TestClient

    from bangla_gpt_api.main import create_app

    module = logic
    script = _load_script()  # the DB/corpus half lives with the CLI
    db_path = tmp_path / "loop.db"
    settings = Settings(
        env="test",
        llm_provider="mock",
        database_url=f"sqlite:///{db_path.as_posix()}",
        jwt_secret=SECRET,
        tracing_enabled=True,
    )
    capture = _TraceCapture()
    logging.getLogger("bangla_gpt_api.trace").addHandler(capture)
    logging.getLogger("bangla_gpt_api.trace").setLevel(logging.INFO)
    try:
        client = TestClient(create_app(settings))
        register = client.post(
            "/auth/register",
            json={
                "email": "loop@example.com",
                "password": PASSWORD,
                "name": "Loop Student",
                "role": "student",
                "class_level": 6,
                "guardian_consent": True,
            },
        )
        assert register.status_code == 201, register.text
        login = client.post("/auth/login", json={"email": "loop@example.com", "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        conversation = client.post("/tutor/conversations", json={"title": "loop"}, headers=headers)
        conversation_id = conversation.json()["id"]
        question = "সালোকসংশ্লেষণ কী?"
        answer = client.post(
            f"/tutor/conversations/{conversation_id}/messages",
            json={"message": question, "class_level": 6, "subject": "science"},
            headers=headers,
        )
        assert answer.status_code == 200, answer.text
        message_id = answer.json()["id"]
        feedback = client.post(
            "/feedback",
            json={"message_id": message_id, "rating": -1, "comment": "ভুল উত্তর"},
            headers=headers,
        )
        assert feedback.status_code == 201, feedback.text
    finally:
        logging.getLogger("bangla_gpt_api.trace").removeHandler(capture)

    trace_log = tmp_path / "trace.log"
    trace_log.write_text("\n".join(capture.lines), encoding="utf-8")
    traces = module.load_trace_log(trace_log)
    assert any(record.get("stage") == "retrieval" for record in traces)

    engine = make_engine(Settings(env="test", database_url=f"sqlite:///{db_path.as_posix()}"))
    session_factory = make_session_factory(engine)
    from datetime import UTC, datetime, timedelta

    with session_factory() as db:
        ratings = script._ratings(db, datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
        assert len(ratings) == 1
        assert ratings[0]["question"] == question
        assert ratings[0]["class_level"] == 6
        assert ratings[0]["sources"], "the mock answer cites its evidence"
        chunk_meta = script._chapter_lookup(None)
        candidates, notes = module.build_candidates(ratings, traces, chunk_meta)

    assert notes == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["question"] == question
    assert candidate["trace_join"] == "citations", "the join is exact, not a guess"
    assert candidate["trace"]["trace_id"], "the joined trace carries its correlation id"
    assert candidate["trace"]["coverage"] is not None
    assert candidate["trace"]["retrieved_ids"]
    assert candidate["provenance"]["feedback_id"] == 1
    assert candidate["provenance"]["comment_present"] is True
    assert candidate["needs_teacher_review"] is True
    assert candidate["answerability"] == "unknown_pending_triage"

    # and it triages into a golden-shaped item, closing the loop
    triage = {
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "verdict": "accept",
                "answerability": "in_corpus",
                "reviewer": "teacher",
            }
        ]
    }
    approved, rejected, problems = module.triage_candidates(candidates, triage)
    assert problems == [] and rejected == []
    assert approved[0]["question"] == question
    assert approved[0]["provenance"]["feedback_id"] == 1
