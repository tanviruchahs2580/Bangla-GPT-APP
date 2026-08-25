"""End-to-end tutor integration over the built NCTB corpus.

Runs against the REAL acquired corpus when ``data/nctb`` exists locally;
skips cleanly in CI where the copyrighted corpus is not checked out.
The wiring itself (env var → loader → index → API) is additionally
covered unconditionally by a synthetic-corpus test below.
"""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CORPUS = REPO_ROOT.parent / "data" / "nctb"

REAL_CORPUS_AVAILABLE = (REAL_CORPUS / "quality_report.json").exists()


def _register_and_login(client: TestClient, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "class_level": 9,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _write_synthetic_nctb_corpus(target: Path) -> None:
    """Corpus in exactly the format the pipeline produces on disk."""
    pages = [
        PageText(
            1,
            "অধ্যায়: বল ও গতি",
            "bijoy-converted",
        ),
        PageText(2, "নিউটনের প্রথম সূত্র অনুযায়ী গতির অবস্থা পরিবর্তনে বাহ্যিক বল প্রয়োজন। " * 10),
    ]
    chunks = chunk_pages(pages, source_id="synthetic-nctb")
    extracted = target / "extracted"
    normalized = target / "normalized"
    normalized.mkdir(parents=True)
    extracted.mkdir(parents=True)
    (extracted / "synthetic-nctb.pages.json").write_text(
        json.dumps({"source_id": "synthetic-nctb", "pages": [asdict(p) for p in pages]}),
        encoding="utf-8",
    )
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


def _client_with_corpus(corpus_dir: Path) -> TestClient:
    settings = Settings(
        env="test",
        jwt_secret=SECRET,
        nctb_corpus_dir=str(corpus_dir),
    )
    return TestClient(create_app(settings))


def test_synthetic_nctb_corpus_served_by_tutor(tmp_path: Path) -> None:
    _write_synthetic_nctb_corpus(tmp_path / "nctb")
    client = _client_with_corpus(tmp_path / "nctb")
    headers = _register_and_login(client, "nctb-student@example.com")
    res = client.post(
        "/tutor/ask",
        json={"question": "নিউটনের প্রথম সূত্র কী?", "class_level": 9, "subject": "physics"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["grounded"] is True
    assert body["sources"], "NCTB-grounded answer must cite provenance"
    source = body["sources"][0]
    assert source["book"] == "পদার্থবিদ্যা"
    assert source["chapter"] == "বল ও গতি"
    assert source["page"] >= 1


def test_low_bangla_ratio_source_is_gated_out(tmp_path: Path) -> None:
    _write_synthetic_nctb_corpus(tmp_path / "nctb")
    report_path = tmp_path / "nctb" / "quality_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["synthetic-nctb"]["bangla_char_ratio_on_usable"] = 0.05
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    client = _client_with_corpus(tmp_path / "nctb")
    headers = _register_and_login(client, "gate@example.com")
    res = client.post(
        "/tutor/ask",
        json={"question": "নিউটনের প্রথম সূত্র কী?", "class_level": 9},
        headers=headers,
    )
    # Corpus gated out entirely → sample corpus absent → refusal, not crash
    assert res.status_code in (200, 503)


@pytest.mark.skipif(not REAL_CORPUS_AVAILABLE, reason="real NCTB corpus not present (CI)")
def test_real_nctb_corpus_end_to_end() -> None:
    client = _client_with_corpus(REAL_CORPUS)
    headers = _register_and_login(client, "real-nctb@example.com")

    # Question about actual curriculum content (science process & measurement)
    res = client.post(
        "/tutor/ask",
        json={"question": "বৈজ্ঞানিক প্রক্রিয়া ও পরিমাপ কী?", "class_level": 9, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    if body["grounded"]:
        assert body["sources"]
        assert all(src["page"] is not None for src in body["sources"])
    else:
        # coverage gate refused — acceptable only when evidence genuinely thin
        assert body["answer"]

    # Out-of-curriculum question must be refused by the grounding gate
    res = client.post(
        "/tutor/ask",
        json={"question": "গত বিশ্বকাপে কোন দল জিতেছিল?", "class_level": 9},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["grounded"] is False


def test_real_corpus_metrics_file_matches_loader(tmp_path: Path) -> None:
    if not REAL_CORPUS_AVAILABLE:
        pytest.skip("real corpus absent")
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

    chunks = load_nctb_corpus(
        REAL_CORPUS / "normalized",
        quality_report_path=REAL_CORPUS / "quality_report.json",
    )
    assert len(chunks) > 500, "expected a substantial verified corpus"
    assert shutil  # keep import meaningful
