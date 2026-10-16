"""question-paper generator -- gates, HIL review, FINAL, PDF export."""

import io
import json
import logging
import re

import pypdf
import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers import ProviderError
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.services.generators.question_paper import (
    allocate_marks,
    plan_counts,
    validate_paper,
)
from bangla_gpt_api.services.qp_pdf import render_qp_html

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

# Chapter title 'kosh' from the sample NCTB class-6 science corpus.
CHAPTER = "কোষ"


def _pdf_text(content: bytes) -> str:
    """Extract PDF text with fpdf2's shaping control bytes removed.

    With complex-script shaping enabled (AUD-0045) fpdf2 2.8.9 shapes the glyphs
    correctly but emits stray C0 control characters into the ToUnicode map, so
    "কোষ" extracts as "ক\\x02োষ". Those bytes are a shaper artefact, not content,
    so strip them before comparing. The assertion that Bengali survived the font
    pipeline is unchanged -- only its noise is removed.
    """
    raw = "".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(content)).pages)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)


DRAFT_BODY = {
    "class_level": 6,
    "subject": "science",
    "chapters": [CHAPTER],
    "exam_type": "Exam 2026",
    "marks": 10,
    "duration_min": 10,
}


class _RewritingProvider:
    """Wraps the mock provider and mutates its QP JSON (gate-failure paths)."""

    name = "rewriting"

    def __init__(self, mutate) -> None:
        self.mutate = mutate
        self.inner = MockLLMProvider()
        self.calls = 0

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls += 1
        raw = await self.inner.generate(prompt, system=system)
        data = json.loads(raw)
        self.mutate(data["questions"])
        return json.dumps(data, ensure_ascii=False)


class _StubProvider:
    name = "stub"

    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return self.reply


def _client_for(monkeypatch, provider, tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/qpfake.db",
        jwt_secret=SECRET,
    )
    monkeypatch.setattr("bangla_gpt_api.main.get_provider", lambda s: provider)
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/qp.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _headers(client: TestClient, email: str, role: str = "teacher") -> dict[str, str]:
    client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teacher", "role": role},
    )
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def teacher_headers(client: TestClient) -> dict[str, str]:
    return _headers(client, "teach@example.com")


def _draft(client: TestClient, headers: dict) -> dict:
    res = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _review_all(client: TestClient, headers: dict, qp: dict) -> dict:
    decisions = [{"ref": q["ref"], "action": "accept"} for q in qp["questions"]]
    res = client.post(
        f"/teacher/qpapers/{qp['id']}/review",
        json={"decisions": decisions},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_draft_created_unreviewed_and_fast(client, teacher_headers, caplog) -> None:
    caplog.set_level(logging.INFO)
    qp = _draft(client, teacher_headers)
    assert qp["status"] == "draft"
    assert qp["reviewed_at"] is None and qp["finalized_at"] is None
    assert len(qp["questions"]) == 5  # marks//2 for marks=10
    assert all(q["reviewed"] is False for q in qp["questions"])
    assert all(len(q["options"]) == 4 for q in qp["questions"])
    assert qp["meta"]["alignment_min"] >= 0.3
    draft_logs = [r for r in caplog.records if "qp_draft" in r.getMessage()]
    assert draft_logs, "draft must log qp_draft with elapsed_ms"
    logged = json.loads(draft_logs[-1].getMessage())
    assert logged["elapsed_ms"] < 60_000  # PASS-WHEN: draft <60s


def test_draft_difficulty_percentages_must_sum_100(client, teacher_headers) -> None:
    body = dict(DRAFT_BODY, difficulty={"easy": 40, "medium": 50, "hard": 20})
    res = client.post("/teacher/qpapers", json=body, headers=teacher_headers)
    assert res.status_code == 422


@pytest.mark.parametrize("marks", [10, 14])
def test_declared_total_marks_are_allocated_across_questions(
    client, teacher_headers, marks: int
) -> None:
    """A paper requested as N marks must contain questions summing to N.

    Totals above the mock provider's distinct-sentence supply (and the large
    100-mark case) are covered by ``test_allocate_marks_sums_to_the_declared_total``
    -- the duplicate gate is a separate, pre-existing constraint.
    """
    res = client.post(
        "/teacher/qpapers", json=dict(DRAFT_BODY, marks=marks), headers=teacher_headers
    )
    assert res.status_code == 201, res.text
    questions = res.json()["questions"]
    assert sum(int(q["marks"]) for q in questions) == marks
    assert all(int(q["marks"]) >= 1 for q in questions)


@pytest.mark.parametrize(
    "difficulty",
    [
        {"easy": 0, "medium": 0, "hard": 100},
        {"easy": 100, "medium": 0, "hard": 0},
        {"easy": 50, "medium": 50, "hard": 0},
    ],
)
def test_explicit_zero_difficulty_bucket_generates_successfully(
    client, teacher_headers, difficulty: dict[str, int]
) -> None:
    """A legal 0% bucket must not be rescued to 1 and then rejected.

    Before the fix marks=10 with easy=0/medium=0/hard=100 produced counts
    {easy:1, medium:1, hard:3} and validate_paper rejected the resulting 20%
    share against the 0% target: a deterministic 502 after the AI call was
    already paid for.
    """
    res = client.post(
        "/teacher/qpapers", json=dict(DRAFT_BODY, difficulty=difficulty), headers=teacher_headers
    )
    assert res.status_code == 201, res.text
    body = res.json()
    planned = body["meta"]["counts_planned"]
    for label, pct in difficulty.items():
        if pct == 0:
            assert planned[label] == 0
    assert sum(planned.values()) == len(body["questions"])
    assert body["meta"]["difficulty_actual"] == planned
    assert sum(int(q["marks"]) for q in body["questions"]) == DRAFT_BODY["marks"]


def test_plan_counts_keeps_explicit_zero_buckets_empty() -> None:
    assert plan_counts(10, 0, 0, 100) == {"easy": 0, "medium": 0, "hard": 5}
    assert plan_counts(10, 50, 50, 0) == {"easy": 3, "medium": 2, "hard": 0}
    assert sum(plan_counts(23, 30, 50, 20).values()) == 11


def test_allocate_marks_sums_to_the_declared_total() -> None:
    for total, count in ((5, 5), (10, 5), (23, 11), (100, 20)):
        plan = allocate_marks(total, count)
        assert len(plan) == count and sum(plan) == total and min(plan) >= 1


def test_validate_paper_rejects_marks_that_do_not_match_declared_total() -> None:
    """The gate between the printed header and the labels is explicit."""
    evidence = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠন ও কার্যমূলক একক"
    options = ["কোষ", "জীবদেহের", "গঠন", "একক"]
    questions = [
        {
            "ref": f"q{i + 1}",
            "text": token,
            "options": list(options),
            "answer_index": 0,
            "marks": 2,
            "difficulty": "easy",
            "chapter": "কোষ",
        }
        for i, token in enumerate(("কোষ", "জীবদেহের", "গঠন"))
    ]
    with pytest.raises(
        ProviderError, match=r"marks validation failed: questions sum to 6, declared 10"
    ):
        validate_paper(questions, {"easy": 3, "medium": 0, "hard": 0}, [evidence], total_marks=10)


def test_garbage_provider_reply_502_nothing_persisted(tmp_path, monkeypatch) -> None:
    client = _client_for(monkeypatch, _StubProvider("not json at all"), tmp_path)
    headers = _headers(client, "teach@example.com")
    res = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=headers)
    assert res.status_code == 502
    assert client.get("/teacher/qpapers", headers=headers).json() == []


class _VaryingProvider:
    """Mock that changes its questions on repeat calls, like a real LLM."""

    name = "varying"

    def __init__(self) -> None:
        self.inner = MockLLMProvider()
        self.calls = 0

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls += 1
        raw = await self.inner.generate(prompt, system=system)
        data = json.loads(raw)
        for i, q in enumerate(data["questions"]):
            q["text"] = f"{q['text']} variant{self.calls}-{i}"
        return json.dumps(data, ensure_ascii=False)


def test_alignment_gate_rejects_off_topic_questions(tmp_path, monkeypatch) -> None:
    def mutate(questions):
        questions[0]["text"] = "qqzzww xxyy vvuu"
        questions[0]["options"] = ["aabb", "ccdd", "eeff", "gghh"]

    client = _client_for(monkeypatch, _RewritingProvider(mutate), tmp_path)
    headers = _headers(client, "teach@example.com")
    res = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=headers)
    assert res.status_code == 502


def test_duplicate_gate_rejects_near_identical_questions(tmp_path, monkeypatch) -> None:
    def mutate(questions):
        questions[1]["text"] = questions[0]["text"]
        questions[1]["options"] = list(questions[0]["options"])

    client = _client_for(monkeypatch, _RewritingProvider(mutate), tmp_path)
    headers = _headers(client, "teach@example.com")
    res = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=headers)
    assert res.status_code == 502


def test_difficulty_gate_rejects_wrong_mix(tmp_path, monkeypatch) -> None:
    def mutate(questions):
        for q in questions:
            q["difficulty"] = "easy"

    client = _client_for(monkeypatch, _RewritingProvider(mutate), tmp_path)
    headers = _headers(client, "teach@example.com")
    res = client.post("/teacher/qpapers", json=DRAFT_BODY, headers=headers)
    assert res.status_code == 502


def test_finalize_blocked_until_every_question_reviewed(client, teacher_headers) -> None:
    qp = _draft(client, teacher_headers)
    blocked = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=teacher_headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "review_required"
    assert set(blocked.json()["detail"]["unreviewed"]) == {q["ref"] for q in qp["questions"]}
    partial = client.post(
        f"/teacher/qpapers/{qp['id']}/review",
        json={"decisions": [{"ref": qp["questions"][0]["ref"], "action": "accept"}]},
        headers=teacher_headers,
    )
    assert partial.status_code == 200
    assert partial.json()["reviewed_at"] is None
    still = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=teacher_headers)
    assert still.status_code == 409

    reviewed = _review_all(client, teacher_headers, qp)
    assert reviewed["reviewed_at"] is not None
    done = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=teacher_headers)
    assert done.status_code == 200 and done.json()["status"] == "final"
    assert done.json()["finalized_at"] is not None
    again = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=teacher_headers)
    assert again.status_code == 409
    edit_after_final = client.post(
        f"/teacher/qpapers/{qp['id']}/review",
        json={"decisions": [{"ref": qp["questions"][0]["ref"], "action": "accept"}]},
        headers=teacher_headers,
    )
    assert edit_after_final.status_code == 409


def test_review_edit_persists_and_accept_marks_reviewed(client, teacher_headers) -> None:
    qp = _draft(client, teacher_headers)
    first, second = qp["questions"][0]["ref"], qp["questions"][1]["ref"]
    res = client.post(
        f"/teacher/qpapers/{qp['id']}/review",
        json={
            "decisions": [
                {"ref": first, "action": "accept"},
                {
                    "ref": second,
                    "action": "edit",
                    "text": "EDITED-QUESTION-TEXT",
                    "options": ["p", "q", "r", "s"],
                    "answer_index": 2,
                },
            ]
        },
        headers=teacher_headers,
    )
    assert res.status_code == 200
    by_ref = {q["ref"]: q for q in res.json()["questions"]}
    assert by_ref[first]["reviewed"] is True
    assert by_ref[second]["text"] == "EDITED-QUESTION-TEXT"
    assert by_ref[second]["options"] == ["p", "q", "r", "s"]
    assert by_ref[second]["answer_index"] == 2
    assert by_ref[second]["reviewed"] is True


def test_edit_without_text_is_rejected(client, teacher_headers) -> None:
    qp = _draft(client, teacher_headers)
    res = client.post(
        f"/teacher/qpapers/{qp['id']}/review",
        json={"decisions": [{"ref": qp["questions"][0]["ref"], "action": "edit"}]},
        headers=teacher_headers,
    )
    assert res.status_code == 422


def test_shuffle_reorders_and_resets_review(client, teacher_headers) -> None:
    qp = _draft(client, teacher_headers)
    _review_all(client, teacher_headers, qp)
    before = [q["ref"] for q in qp["questions"]]
    res = client.post(f"/teacher/qpapers/{qp['id']}/shuffle", headers=teacher_headers)
    assert res.status_code == 200
    after = res.json()
    assert [q["ref"] for q in after["questions"]] != before
    assert sorted(q["ref"] for q in after["questions"]) == sorted(before)
    assert all(q["reviewed"] is False for q in after["questions"])
    assert after["reviewed_at"] is None


def test_replace_swaps_one_question_keeps_ref(tmp_path, monkeypatch) -> None:
    # A varying provider stands in for a real LLM producing different output per call.
    client = _client_for(monkeypatch, _VaryingProvider(), tmp_path)
    headers = _headers(client, "teach@example.com")
    qp = _draft(client, headers)
    target = qp["questions"][0]
    res = client.post(
        f"/teacher/qpapers/{qp['id']}/replace",
        json={"ref": target["ref"]},
        headers=headers,
    )
    assert res.status_code == 200
    replaced = {q["ref"]: q for q in res.json()["questions"]}[target["ref"]]
    assert replaced["text"] != target["text"]
    assert replaced["reviewed"] is False
    assert replaced["difficulty"] == target["difficulty"]
    assert replaced["chapter"] == target["chapter"]


def test_regenerate_makes_fresh_draft_resetting_review(client, teacher_headers) -> None:
    qp = _draft(client, teacher_headers)
    _review_all(client, teacher_headers, qp)
    res = client.post(f"/teacher/qpapers/{qp['id']}/regenerate", headers=teacher_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "draft"
    assert body["reviewed_at"] is None
    assert all(q["reviewed"] is False for q in body["questions"])


def test_other_teacher_cannot_touch_paper(client, teacher_headers) -> None:
    qp = _draft(client, teacher_headers)
    other = _headers(client, "other@example.com")
    assert client.get(f"/teacher/qpapers/{qp['id']}", headers=other).status_code == 404
    assert client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=other).status_code == 404
    assert client.get("/teacher/qpapers", headers=other).json() == []


def _finalized(client, headers) -> dict:
    qp = _draft(client, headers)
    reviewed = _review_all(client, headers, qp)
    res = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=headers)
    assert res.status_code == 200
    return reviewed


def _pdf_marks(text: str) -> list[int]:
    """Per-question marks labels: question lines end with "(n)"."""
    return [int(m) for m in re.findall(r"\((\d+)\)\s*$", text, re.M)]


def test_pdf_marks_labels_sum_to_the_declared_total(client, teacher_headers) -> None:
    res = client.post("/teacher/qpapers", json=dict(DRAFT_BODY, marks=14), headers=teacher_headers)
    assert res.status_code == 201, res.text
    qp = res.json()
    _review_all(client, teacher_headers, qp)
    finalized = client.post(f"/teacher/qpapers/{qp['id']}/finalize", headers=teacher_headers)
    assert finalized.status_code == 200

    paper = client.get(f"/teacher/qpapers/{qp['id']}/pdf", headers=teacher_headers)
    assert paper.status_code == 200
    text = _pdf_text(paper.content)
    declared = 14
    labels = _pdf_marks(text)
    assert len(labels) == len(qp["questions"])
    assert sum(labels) == declared == sum(int(q["marks"]) for q in qp["questions"])
    # The header that carries the declared total is Bangla now. It is checked in
    # the HTML render rather than in extracted PDF text: text shaping reorders
    # the reph in "নম্বর", so the extracted byte sequence is not stable.
    html = render_qp_html(
        {
            "exam_type": qp["exam_type"],
            "class_level": qp["class_level"],
            "subject": qp["subject"],
            "marks": qp["marks"],
            "duration_min": qp["duration_min"],
            "chapters": list(qp["chapters"]),
            "questions": [dict(q) for q in qp["questions"]],
        },
        "paper",
    )
    assert f"{declared} নম্বর" in html

    answer = client.get(
        f"/teacher/qpapers/{qp['id']}/pdf", params={"kind": "answer"}, headers=teacher_headers
    )
    answer_labels = _pdf_marks(_pdf_text(answer.content))
    assert answer_labels == labels


def test_pdf_export_renders_bengali_and_answer_key(client, teacher_headers) -> None:
    qp = _finalized(client, teacher_headers)
    paper = client.get(f"/teacher/qpapers/{qp['id']}/pdf", headers=teacher_headers)
    assert paper.status_code == 200
    assert paper.headers["content-type"].startswith("application/pdf")
    assert paper.content[:5] == b"%PDF-"
    paper_text = _pdf_text(paper.content)
    assert CHAPTER in paper_text  # Bengali survives the font pipeline
    assert "উত্তরমালা" not in paper_text

    answer = client.get(
        f"/teacher/qpapers/{qp['id']}/pdf", params={"kind": "answer"}, headers=teacher_headers
    )
    assert answer.status_code == 200 and answer.content[:5] == b"%PDF-"
    answer_text = _pdf_text(answer.content)
    assert "উত্তরমালা" in answer_text
    assert " <--" in answer_text

    bad = client.get(
        f"/teacher/qpapers/{qp['id']}/pdf", params={"kind": "bogus"}, headers=teacher_headers
    )
    assert bad.status_code == 400
