"""Wave 1: generic teacher document generators + document library.

Chapter title 'kosh' (cell) from the sample NCTB class-6 science corpus;
built from codepoints so the file stays pure ASCII on disk.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "docs.db"


@pytest.fixture
def client(db_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "teacher") -> None:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Teach", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def teach(client: TestClient) -> dict:
    _register(client, "teach@example.com")
    return _headers(client, "teach@example.com")


def _gen(client: TestClient, headers: dict, kind: str, body: dict):
    return client.post(f"/teacher/generate/{kind}", json=body, headers=headers)


def test_worksheet_generate_persist_list_get_delete(client: TestClient, teach) -> None:
    res = _gen(
        client, teach, "worksheet", {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "worksheet"
    assert body["title"]
    assert body["sources"], "worksheet must cite textbook evidence"
    assert [t["tier"] for t in body["payload"]["tiers"]] == ["basic", "intermediate", "advanced"]
    assert body["payload"]["answer_sheet"]
    doc_id = body["id"]

    listed = client.get("/teacher/documents", params={"kind": "worksheet"}, headers=teach).json()
    assert [d["id"] for d in listed] == [doc_id]

    got = client.get(f"/teacher/documents/{doc_id}", headers=teach)
    assert got.status_code == 200
    assert got.json()["payload"] == body["payload"]

    assert client.delete(f"/teacher/documents/{doc_id}", headers=teach).status_code == 204
    assert client.get(f"/teacher/documents/{doc_id}", headers=teach).status_code == 404
    assert client.get("/teacher/documents", headers=teach).json() == []


def test_homework_and_rubric_generate_and_persist(client: TestClient, teach) -> None:
    res = _gen(
        client, teach, "homework", {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    )
    assert res.status_code == 201, res.text
    hw = res.json()["payload"]
    assert hw["items"] and hw["instructions"] and hw["parent_note"]
    assert hw["estimated_minutes"] >= 1

    res = _gen(
        client, teach, "rubric", {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    )
    assert res.status_code == 201, res.text
    rub = res.json()["payload"]
    assert rub["criteria"]
    assert rub["total_marks"] == sum(c["max_marks"] for c in rub["criteria"])
    for row in rub["criteria"]:
        assert set(row["levels"]) == {"excellent", "good", "needs_improvement"}

    kinds = sorted(d["kind"] for d in client.get("/teacher/documents", headers=teach).json())
    assert kinds == ["homework", "rubric"]


def test_answer_key_from_inline_questions(client: TestClient, teach) -> None:
    questions = [f"{chr(0x9AA8)} {i} ?" for i in range(3)]
    res = _gen(
        client,
        teach,
        "answer_key",
        {"class_level": 6, "subject": "science", "questions": questions},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    payload = body["payload"]
    assert len(payload["answers"]) == 3
    assert [a["ref"] for a in payload["answers"]] == ["q1", "q2", "q3"]
    assert payload["marking_guide"]["total_marks"] == sum(a["marks"] for a in payload["answers"])
    assert body["chapter"] is None, "inline answer key without chapter stores no chapter"


def test_answer_key_from_own_paper_id(client: TestClient, teach) -> None:
    qp = client.post(
        "/teacher/qpapers",
        json={
            "class_level": 6,
            "subject": "science",
            "chapters": [CHAPTER],
            "exam_type": "Exam 2026",
            "marks": 10,
            "duration_min": 10,
        },
        headers=teach,
    )
    assert qp.status_code == 201, qp.text
    paper = qp.json()
    res = _gen(
        client,
        teach,
        "answer_key",
        {"class_level": 6, "subject": "science", "paper_id": paper["id"]},
    )
    assert res.status_code == 201, res.text
    assert len(res.json()["payload"]["answers"]) == len(paper["questions"])
    assert res.json()["chapter"] == CHAPTER, "chapter resolved from the paper"


def test_answer_key_requires_exactly_one_questions_source(client: TestClient, teach) -> None:
    base = {"class_level": 6, "subject": "science"}
    assert _gen(client, teach, "answer_key", base).status_code == 422
    both = dict(base, paper_id=1, questions=["x"])
    assert _gen(client, teach, "answer_key", both).status_code == 422


def test_unknown_kind_is_404_and_validation_errors_are_422(client: TestClient, teach) -> None:
    assert _gen(client, teach, "bogus", {}).status_code == 404
    assert (
        _gen(client, teach, "worksheet", {"class_level": 6, "subject": "science"}).status_code
        == 422
    )
    # lesson_plan is persisted by POST /teacher/lesson-plans, not generated here.
    assert (
        _gen(
            client,
            teach,
            "lesson_plan",
            {"class_level": 6, "subject": "science", "chapter": CHAPTER},
        ).status_code
        == 404
    )


def test_documents_are_isolated_between_teachers(client: TestClient, teach) -> None:
    res = _gen(
        client, teach, "worksheet", {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    )
    doc_id = res.json()["id"]

    _register(client, "other@example.com")
    other = _headers(client, "other@example.com")
    assert client.get(f"/teacher/documents/{doc_id}", headers=other).status_code == 404
    assert client.delete(f"/teacher/documents/{doc_id}", headers=other).status_code == 404
    assert client.get("/teacher/documents", headers=other).json() == []


def test_worksheet_and_answer_key_pdf_exports(client: TestClient, teach) -> None:
    ws = _gen(
        client, teach, "worksheet", {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    ).json()
    res = client.get(f"/teacher/documents/{ws['id']}/pdf", headers=teach)
    assert res.status_code == 200
    assert res.content[:5] == b"%PDF-"
    assert res.headers["content-type"] == "application/pdf"
    assert f"document-{ws['id']}-worksheet.pdf" in res.headers["content-disposition"]

    ak = _gen(
        client, teach, "answer_key", {"class_level": 6, "subject": "science", "questions": ["q?"]}
    ).json()
    res = client.get(f"/teacher/documents/{ak['id']}/pdf", headers=teach)
    assert res.status_code == 200
    assert res.content[:5] == b"%PDF-"

    # homework is not a printable kind -> 400
    hw = _gen(
        client, teach, "homework", {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    ).json()
    assert client.get(f"/teacher/documents/{hw['id']}/pdf", headers=teach).status_code == 400


def test_generate_requires_teacher_role(client: TestClient) -> None:
    assert client.post("/teacher/generate/worksheet", json={}).status_code == 401
    _register(client, "kid@example.com", role="student")
    kid = _headers(client, "kid@example.com")
    body = {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    assert _gen(client, kid, "worksheet", body).status_code == 403
