"""S1.11 — global search: relevance, ask-action detection, routing sanity.

Bengali fixtures are built from codepoints so this file stays ASCII-safe.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

# "ko-sh" (cell) -- top-level science chapter in the sample corpus.
KOSH = chr(0x0995) + chr(0x09CB) + chr(0x09B7)
# "kii" (what is) -- trailing interrogative used in section titles.
KII = chr(0x0995) + chr(0x09C0)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/search.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def _auth(client: TestClient) -> dict[str, str]:
    reg = client.post(
        "/auth/register",
        json={
            "email": "search@example.com",
            "password": "supersecret1",
            "name": "Search Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/auth/login", json={"email": "search@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_relevance_chapter_query(client: TestClient) -> None:
    """A keyword query returns chapter/question hits grounded in the corpus."""
    hits = client.get("/search", params={"q": KOSH}, headers=_auth(client)).json()["hits"]
    assert hits, "expected results for a real corpus keyword"
    # Top result must be about cells, in science, for class 6.
    assert all("science" in h["href"] or h["kind"] == "subject" for h in hits[:3])
    assert any(KOSH in h["title"] for h in hits)
    kinds = {h["kind"] for h in hits}
    assert kinds <= {"subject", "chapter", "question"}
    # Chapter links carry the class param the Learn pages expect (any class,
    # since global search spans the student's whole curriculum corpus).
    nav = [h for h in hits if h["kind"] in {"chapter", "question"}]
    assert nav and all(h["href"].startswith("/student/learn/science/") for h in nav)
    assert all("class=" in h["href"] for h in nav)
    assert any("class=6" in h["href"] for h in nav)


def test_question_section_and_ask_action(client: TestClient) -> None:
    """'cell what-is' phrasing classifies a question hit and offers ask-action."""
    body = client.get("/search", params={"q": KOSH + " " + KII}, headers=_auth(client)).json()
    assert body["ask_action"] is True
    assert any(h["kind"] == "question" and KII in h["title"] for h in body["hits"])


def test_plain_keyword_not_question_like(client: TestClient) -> None:
    body = client.get("/search", params={"q": KOSH}, headers=_auth(client)).json()
    assert body["ask_action"] is False


def test_ascii_question_mark_sets_ask_action(client: TestClient) -> None:
    body = client.get("/search", params={"q": "science?"}, headers=_auth(client)).json()
    assert body["ask_action"] is True


def test_subject_slug_match(client: TestClient) -> None:
    body = client.get("/search", params={"q": "science"}, headers=_auth(client)).json()
    subjects = [h for h in body["hits"] if h["kind"] == "subject"]
    assert subjects and subjects[0]["href"] == "/student/learn"
    assert subjects[0]["subtitle"] == "science"


def test_nonsense_query_has_no_hits(client: TestClient) -> None:
    body = client.get("/search", params={"q": "zzzqqqxyz"}, headers=_auth(client)).json()
    assert body["hits"] == []
    assert body["ask_action"] is False


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/search", params={"q": KOSH}).status_code == 401


def test_query_bounds(client: TestClient) -> None:
    headers = _auth(client)
    assert client.get("/search", params={"q": ""}, headers=headers).status_code == 422
    assert client.get("/search", params={"q": "   "}, headers=headers).status_code == 422
    assert client.get("/search", params={"q": "a" * 101}, headers=headers).status_code == 422
    assert client.get("/search", headers=headers).status_code == 422
