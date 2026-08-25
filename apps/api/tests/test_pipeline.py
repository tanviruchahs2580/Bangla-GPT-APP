import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import CurriculumMeta
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.ingestion.text_ingester import TextIngester
from bangla_gpt_api.main import create_app
from bangla_gpt_api.retrieval.bm25 import BM25Index


def test_ingest_attaches_metadata_and_chapters() -> None:
    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="test.md",
    )
    text = (
        "অধ্যায়: কোষ\n\n## কোষ কী\n\nজীবদেহের ক্ষুদ্রতম গঠন ও কার্যমূলক একককে কোষ বলে।\n\n"
        "অধ্যায়: বল ও গতি\n\n## বল কাকে বলে\n\nযে কারণ বস্তুর গতি পরিবর্তন করে তাকে বল বলে।\n"
    )
    chunks = TextIngester().ingest(text, meta)
    assert len(chunks) == 2
    chapters = {chunk.meta.chapter for chunk in chunks}
    assert chapters == {"কোষ", "বল ও গতি"}
    assert all(chunk.meta.class_level == 6 for chunk in chunks)
    assert all(chunk.meta.section for chunk in chunks)
    assert len({chunk.id for chunk in chunks}) == 2


def test_sample_corpus_loads_with_curriculum_versions() -> None:
    corpus = load_sample_corpus()
    assert len(corpus) >= 6
    subjects = {chunk.meta.subject for chunk in corpus}
    assert subjects == {"science", "mathematics"}
    assert all(chunk.meta.version == "sample-v1" for chunk in corpus)


def test_retrieval_finds_relevant_chunk() -> None:
    index = BM25Index(load_sample_corpus())
    hits = index.search(
        "কোষ কী? কোষের প্রধান অংশ কোনটি?",
        class_level=6,
        subject="science",
    )
    assert hits, "expected a hit for an in-corpus question"
    assert "কোষ" in hits[0].chunk.text


def test_retrieval_respects_filters() -> None:
    index = BM25Index(load_sample_corpus())
    assert index.search("কোষ", class_level=7) == []
    math_hits = index.search("ভগ্নাংশ কী?", class_level=7, subject="mathematics")
    assert math_hits and "ভগ্নাংশ" in math_hits[0].chunk.text


def test_irrelevant_query_returns_no_hits() -> None:
    index = BM25Index(load_sample_corpus())
    assert index.search("zzqq blorg wumpus", class_level=6) == []


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(env="test")))
