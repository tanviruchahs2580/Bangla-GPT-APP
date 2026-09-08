"""S2.4: question-paper generator -- gates, HIL review, FINAL, PDF export."""

import io
import json
import logging

import pypdf
import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

# Chapter title 'kosh' from the sample NCTB class-6 science corpus.
CHAPTER = "কোষ"

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


def test_pdf_export_renders_bengali_and_answer_key(client, teacher_headers) -> None:
    qp = _finalized(client, teacher_headers)
    paper = client.get(f"/teacher/qpapers/{qp['id']}/pdf", headers=teacher_headers)
    assert paper.status_code == 200
    assert paper.headers["content-type"].startswith("application/pdf")
    assert paper.content[:5] == b"%PDF-"
    paper_text = "".join(
        page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(paper.content)).pages
    )
    assert CHAPTER in paper_text  # Bengali survives the font pipeline
    assert "ANSWER KEY" not in paper_text

    answer = client.get(
        f"/teacher/qpapers/{qp['id']}/pdf", params={"kind": "answer"}, headers=teacher_headers
    )
    assert answer.status_code == 200 and answer.content[:5] == b"%PDF-"
    answer_text = "".join(
        page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(answer.content)).pages
    )
    assert "ANSWER KEY" in answer_text
    assert " <--" in answer_text

    bad = client.get(
        f"/teacher/qpapers/{qp['id']}/pdf", params={"kind": "bogus"}, headers=teacher_headers
    )
    assert bad.status_code == 400
