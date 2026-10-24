"""Read-only Learn catalog endpoint tests.

Covers the grounded subject → chapter → concept flow that backs the Learn
frontend. Content is real corpus text, never hallucinated.
"""

import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.services.learn import (
    canonical_subject,
    chapter_content,
    list_subjects,
    subject_chapters,
)
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def admin_client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "learn"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient) -> dict:
    res = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_learn_requires_auth(admin_client: TestClient):
    assert admin_client.get("/learn/subjects").status_code in (401, 403)


def test_learn_subjects(admin_client: TestClient):
    headers = _login(admin_client)
    res = admin_client.get("/learn/subjects?class_level=6", headers=headers)
    assert res.status_code == 200
    subjects = {s["subject"] for s in res.json()}
    assert {"science", "mathematics", "bangla"} <= subjects


def test_learn_subject_chapters(admin_client: TestClient):
    headers = _login(admin_client)
    res = admin_client.get("/learn/subjects/science/chapters?class_level=6", headers=headers)
    assert res.status_code == 200
    chapters = res.json()
    assert chapters
    for ch in chapters:
        assert ch["chapter"]
        assert ch["section_count"] >= 1


def test_learn_chapter_content(admin_client: TestClient):
    headers = _login(admin_client)
    chapters = admin_client.get(
        "/learn/subjects/science/chapters?class_level=6", headers=headers
    ).json()
    first = chapters[0]["chapter"]
    res = admin_client.get(
        f"/learn/subjects/science/chapters/{first}?class_level=6", headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["chapter"] == first
    assert body["book"]
    assert body["sections"], "concept authoring must provide grounded content"
    assert any(s["text"].strip() for s in body["sections"])


def test_learn_subject_404(admin_client: TestClient):
    headers = _login(admin_client)
    assert (
        admin_client.get("/learn/subjects/nonexistent/chapters", headers=headers).status_code == 404
    )


def test_learn_chapter_404(admin_client: TestClient):
    headers = _login(admin_client)
    assert (
        admin_client.get(
            "/learn/subjects/science/chapters/%E0%A6%85%E0%A6%9C%E0%A6%BE%E0%A6%A8%E0%A6%BE",
            headers=headers,
        ).status_code
        == 404
    )


def test_learn_service_functions():
    subjects = list_subjects(6)
    assert {s.subject for s in subjects} >= {"science", "mathematics", "bangla"}
    chapters = subject_chapters("science", 6)
    assert chapters
    content = chapter_content("science", 6, chapters[0].chapter)
    assert content is not None
    assert content.sections


def test_canonical_subject_resolves_real_corpus_subject_keys() -> None:
    for key in ("english", "physics", "chemistry", "biology", "ict", "higher-mathematics"):
        assert canonical_subject(key) == key
    assert canonical_subject("পদার্থবিদ্যা") == "physics"  # real-corpus book title
    assert canonical_subject("গণিত") == "mathematics"  # sample alias still works
    assert canonical_subject("নেই") is None


def _write_synthetic_corpus(target: Path) -> None:
    """Corpus in exactly the format the pipeline produces on disk."""
    pages = [
        PageText(1, "অধ্যায়: বল ও গতি", "bijoy-converted"),
        PageText(2, "নিউটনের প্রথম সূত্র অনুযায়ী গতির অবস্থা পরিবর্তনে বাহ্যিক বল প্রয়োজন। " * 12),
    ]
    chunks = chunk_pages(pages, source_id="synthetic-nctb")
    normalized = target / "normalized"
    normalized.mkdir(parents=True)
    with (normalized / "synthetic-nctb.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    (target / "quality_report.json").write_text(
        json.dumps(
            {
                "synthetic-nctb": {
                    "level": "secondary",
                    "subject_bn": "পদার্থবিদ্যা",
                    "curriculum_year": "2012",
                    "bangla_char_ratio_on_usable": 0.9,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def corpus_client(tmp_path) -> TestClient:
    _write_synthetic_corpus(tmp_path / "nctb")
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "learn-corpus"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        nctb_corpus_dir=str(tmp_path / "nctb"),
    )
    return TestClient(create_app(settings))


def test_learn_catalog_reflects_the_configured_corpus(corpus_client: TestClient):
    """With NCTB_CORPUS_DIR set, Learn must list the served corpus.

    Before the fix Learn always read the packaged sample, so every real subject
    (physics/english/chemistry/...) 404'd on a screen the tutor already served.
    """
    headers = _login(corpus_client)
    subjects = corpus_client.get("/learn/subjects?class_level=9", headers=headers)
    assert subjects.status_code == 200, subjects.text
    assert [s["subject"] for s in subjects.json()] == ["physics"]
    assert subjects.json()[0]["book"] == "পদার্থবিদ্যা"
    # the packaged sample is not part of the loaded corpus
    assert corpus_client.get("/learn/subjects/science/chapters", headers=headers).status_code == 404

    chapters = corpus_client.get("/learn/subjects/physics/chapters?class_level=9", headers=headers)
    assert chapters.status_code == 200, chapters.text
    assert [c["chapter"] for c in chapters.json()] == ["বল ও গতি"]

    content = corpus_client.get(
        f"/learn/subjects/physics/chapters/{quote('বল ও গতি')}?class_level=9", headers=headers
    )
    assert content.status_code == 200, content.text
    body = content.json()
    assert body["book"] == "পদার্থবিদ্যা"
    assert body["sections"] and all(s["text"].strip() for s in body["sections"])

    # the Bangla book title resolves to the same subject
    alias = corpus_client.get("/learn/subjects/padarthobidda/chapters", headers=headers)
    assert alias.status_code == 404  # unknown slug stays a 404
    aliased = corpus_client.get(f"/learn/subjects/{quote('পদার্থবিদ্যা')}/chapters", headers=headers)
    assert aliased.status_code == 200, aliased.text


def test_tutor_and_learn_speak_about_the_same_corpus(corpus_client: TestClient):
    """The chapter the tutor cites is listed by the Learn catalog."""
    headers = _login(corpus_client)
    ask = corpus_client.post(
        "/tutor/ask",
        json={"question": "নিউটনের প্রথম সূত্র কী?", "class_level": 9, "subject": "physics"},
        headers=headers,
    )
    assert ask.status_code == 200, ask.text
    assert ask.json()["grounded"] is True
    cited = ask.json()["sources"][0]["chapter"]

    listed = corpus_client.get(
        "/learn/subjects/physics/chapters?class_level=9", headers=headers
    ).json()
    assert cited in [c["chapter"] for c in listed]
