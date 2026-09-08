"""S2.9: question bank -- duplicate detection, storing reviewed questions, reuse.

PASS-WHEN coverage: duplicate-detection unit tests (pure + service level) and
the reuse metric observed in logs (qp_draft bank fields, qp_replace
reuse_source=bank with the bank row's times_reused bumped).
"""

import json
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db import models  # noqa: F401  -- registers tables on Base.metadata
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.question_bank import (
    dedupe_key,
    is_duplicate,
    normalize_text,
    store_reviewed,
)

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

# Chapter title 'kosh' from the sample NCTB class-6 science corpus.
CHAPTER = "কোষ"
CUSTOM_TEXT = "BANK REUSE MARKER question?"

DRAFT_BODY = {
    "class_level": 6,
    "subject": "science",
    "chapters": [CHAPTER],
    "exam_type": "Exam 2026",
    "marks": 10,
    "duration_min": 10,
}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "qb.db"


@pytest.fixture
def client(db_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _headers(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": "teacher"},
    )
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def teacher_headers(client: TestClient) -> dict[str, str]:
    return _headers(client, "bank@example.com")


def _draft(client: TestClient, headers: dict) -> dict:
    res = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _review(client: TestClient, headers: dict, qp: dict, decisions: list[dict]) -> dict:
    res = client.post(
        f"/teacher/qpapers/{qp['id']}/review", json={"decisions": decisions}, headers=headers
    )
    assert res.status_code == 200, res.text
    return res.json()


def _accept_all(qp: dict) -> list[dict]:
    return [{"ref": q["ref"], "action": "accept"} for q in qp["questions"]]


def _events(caplog, event: str) -> list[dict]:
    out = []
    for record in caplog.records:
        message = record.getMessage()
        if f'"event": "{event}"' in message:
            out.append(json.loads(message))
    return out


# --------------------------- duplicate detection (unit) ---------------------


def test_normalize_and_dedupe_key_unit() -> None:
    # whitespace collapse + casefold for Latin
    assert normalize_text("  Q One?\t\ttwo ") == "q one? two"
    assert dedupe_key("কোষ   প্রশ্ন") == dedupe_key("কোষ প্রশ্ন")
    assert dedupe_key("কোষ প্রশ্ন") != dedupe_key("কোষ প্রশ্ন ২")
    # NFKC folds compatibility variants (fullwidth latin here)
    assert dedupe_key("ｑuestion") == dedupe_key("question")
    # different content -> different key
    assert dedupe_key("What is a cell?") != dedupe_key("What is a tissue?")


def test_service_store_dedupes_across_teachers() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row, created = store_reviewed(
            db,
            teacher_id=1,
            text="What is  a cell?",
            options=["a", "b", "c", "d"],
            answer_index=1,
            subject="science",
            chapter="kosh",
            class_level=6,
        )
        assert created is True
        # same content, different casing/spacing, different teacher -> one row
        row2, created2 = store_reviewed(
            db,
            teacher_id=2,
            text="  WHAT IS  a CELL? ",
            options=["a", "b", "c", "d"],
            answer_index=1,
            subject="science",
            chapter="kosh",
            class_level=6,
        )
        assert created2 is False and row2.id == row.id
        assert is_duplicate(db, "what is a cell?") is True
        assert is_duplicate(db, "what is a tissue?") is False
        db.commit()


# --------------------------- endpoint behaviour -----------------------------


def test_reviewed_questions_land_in_bank_deduped(
    client: TestClient, teacher_headers, caplog, db_path
) -> None:
    caplog.set_level(logging.INFO)
    qp = _draft(client, teacher_headers)
    _review(client, teacher_headers, qp, _accept_all(qp))
    stored = _events(caplog, "question_bank_reviewed")
    assert stored and stored[-1]["bank_added"] == len(qp["questions"])
    with sqlite3.connect(db_path) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()
    assert count == len(qp["questions"])

    # re-reviewing identical content adds nothing new (dedupe field works)
    caplog.clear()
    _review(client, teacher_headers, qp, _accept_all(qp))
    again = _events(caplog, "question_bank_reviewed")
    assert again and again[-1]["bank_added"] == 0
    with sqlite3.connect(db_path) as conn:
        (count2,) = conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()
    assert count2 == count


def test_draft_logs_reuse_metric(client: TestClient, teacher_headers, caplog) -> None:
    caplog.set_level(logging.INFO)
    qp = _draft(client, teacher_headers)
    _review(client, teacher_headers, qp, _accept_all(qp))
    caplog.clear()
    # Mock provider is deterministic, so the second draft replays the SAME
    # five questions -- the whole draft must show as already banked.
    _draft(client, teacher_headers)
    drafts = _events(caplog, "qp_draft")
    assert drafts, "qp_draft log with reuse metric expected"
    metric = drafts[-1]
    assert metric["bank_size"] == 5
    assert metric["bank_matches"] == 5
    assert metric["reuse_pct"] == 100


def test_replace_reuses_bank_question(client: TestClient, teacher_headers, caplog, db_path) -> None:
    caplog.set_level(logging.INFO)
    qp = _draft(client, teacher_headers)
    decisions = _accept_all(qp)
    decisions[0] = {
        "ref": qp["questions"][0]["ref"],
        "action": "edit",
        "text": CUSTOM_TEXT,
        "options": qp["questions"][0]["options"],
        "answer_index": qp["questions"][0]["answer_index"],
    }
    _review(client, teacher_headers, qp, decisions)

    # Fresh draft: identical AI questions, none carrying the edited text.
    target = _draft(client, teacher_headers)
    ref = target["questions"][0]["ref"]
    marks_before = target["questions"][0]["marks"]
    caplog.clear()
    res = client.post(
        f"/teacher/qpapers/{target['id']}/replace",
        json={"ref": ref, "chapter": CHAPTER},
        headers=teacher_headers,
    )
    assert res.status_code == 200, res.text
    out_q = next(q for q in res.json()["questions"] if q["ref"] == ref)
    assert out_q["text"] == CUSTOM_TEXT
    assert out_q["reviewed"] is False
    # marks are the paper's, not invented: inherited from the replaced slot
    assert out_q["marks"] == marks_before

    replays = _events(caplog, "qp_replace")
    assert replays and replays[-1]["reuse_source"] == "bank"
    with sqlite3.connect(db_path) as conn:
        (used,) = conn.execute(
            "SELECT times_reused FROM question_bank WHERE question_text = ?", (CUSTOM_TEXT,)
        ).fetchone()
    assert used == 1
