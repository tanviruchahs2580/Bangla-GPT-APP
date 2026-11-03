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
    assert subjects == {"science", "mathematics", "bangla"}
    assert all(chunk.meta.version == "sample-v1" for chunk in corpus)


def _ingest_meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="s.md",
    )


def test_ingest_ids_are_content_addressed() -> None:
    # Audit F-15: the id must fold the CONTENT, not a running sequence —
    # inserting an earlier paragraph can never renumber the later chunks.
    meta = _ingest_meta()
    body = "প্রথম অনুচ্ছেদের বাক্য।\n\nদ্বিতীয় অনুচ্ছেদের বাক্য।\n"
    before = TextIngester().ingest(body, meta)
    after = TextIngester().ingest("নতুন অনুচ্ছেদের বাক্য।\n\n" + body, meta)
    before_ids = {c.id for c in before}
    after_ids = {c.id for c in after}
    assert before_ids < after_ids, "existing chunks keep their ids after an insertion"


def test_ingest_dedupes_byte_identical_passages() -> None:
    meta = _ingest_meta()
    body = "একই অনুচ্ছেদ দুবার এসেছে।\n\nএকই অনুচ্ছেদ দুবার এসেছে।\n"
    chunks = TextIngester().ingest(body, meta)
    assert len(chunks) == 1, "a repeated passage is ingested once per section scope"


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


def test_ingester_splits_long_paragraph_on_sentences() -> None:
    # The char-limit splitter must never cut a sentence in half and must
    # exercise both sides of the accumulate/flush boundary (F-06/B3).
    meta = _ingest_meta()
    # numbered sentences keep every piece content-distinct, so the
    # content-addressed dedupe cannot collapse them (B5 path) and this test
    # isolates the splitter alone
    sentences = [f"দীর্ঘ বাক্য নম্বর {i} একদম শেষ পর্যন্ত চলে।" for i in range(40)]
    body = " ".join(sentences)
    sentence = sentences[0]
    chunks = TextIngester().ingest(body, meta)
    assert len(chunks) >= 2
    # each accumulated piece may overshoot only to the sentence that broke
    # the limit — never by an entire unsplit remainder
    assert all(len(c.text) <= 700 + len(sentence) for c in chunks)
    for piece in chunks:
        assert piece.text.strip().endswith("।"), "every split piece ends at a sentence boundary"
    joined = " ".join(c.text for c in chunks)
    assert all(f"বাক্য নম্বর {i} " in joined for i in range(40)), (
        "splitting must preserve every sentence exactly once"
    )
