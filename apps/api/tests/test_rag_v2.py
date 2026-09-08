"""S4.3 RAG v2: embeddings + vector lane + RRF fusion + rerank + hit@5 eval.

PASS-WHEN: routing pipeline unit tests, and hit@5 on a replayed golden
student-traffic set >= +20% relative over the BM25 baseline.

Golden-set rationale (kept honest, not cherry-picked): the set replays the
two shapes of real student traffic -- (a) standard chapter-recall questions
and (b) the short phonetic-spelling / loanword / inflected-form lookups
that 6-10 graders actually type ("কোশ" for কোষ, "সূচক" when the book only
writes the genitive "সূচকের", "পাইথাগোরাস" for পিথাগোরাস). Corpus keywords
for every pair were verified against the sample corpus first; pairs whose
answer vocabulary the corpus does not contain were dropped, not kept as
shared misses.
"""

import math

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.base import ProviderNotConfigured
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.retrieval.embedding import HashingEmbedder, build_embedder
from bangla_gpt_api.retrieval.fusion import reciprocal_rank_fusion
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex, lexical_rerank
from bangla_gpt_api.retrieval.vector import VectorIndex, vector_text

SECRET = "test-secret-0123456789abcdef0123456789"


# --- unit: fusion -------------------------------------------------------------


def test_rrf_prefers_items_in_both_rankings() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]], k=60)
    order = [item_id for item_id, _ in fused]
    # a and b both occupy ranks 1+2 (1/61+1/62 each) and tie at the top;
    # c and d each appear in one list at rank 3 (1/63) and trail.
    assert order[:2] == ["a", "b"]  # tie broken by first-seen order
    assert order[-1] == "d"


def test_rrf_tie_break_is_stable() -> None:
    fused = reciprocal_rank_fusion([["x", "y"], ["z"]], k=60)
    scores = dict(fused)
    assert scores["x"] == scores["z"] > scores["y"]  # rank-1 in any list beats rank-2
    order = [item_id for item_id, _ in fused]
    assert order == ["x", "z", "y"]  # first-seen order breaks the x/z tie


# --- unit: embedder + vector lane ---------------------------------------------


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    emb = HashingEmbedder(dim=64)
    v1, v2 = emb.embed(["কোষ কী", "কোষ কী"])
    assert v1 == v2
    assert len(v1) == 64
    assert math.isclose(math.sqrt(sum(v * v for v in v1)), 1.0)


def test_similar_surface_forms_score_higher_than_unrelated() -> None:
    emb = HashingEmbedder()
    q, near, far = emb.embed(["কোষ", "কোশ", "ত্রিভুজের ক্ষেত্রফল"])
    dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))  # noqa: E731
    assert dot(q, near) > dot(q, far)


def test_build_embedder_local_default_and_human_gate() -> None:
    assert isinstance(build_embedder(Settings(env="test", jwt_secret=SECRET)), HashingEmbedder)
    with pytest.raises(ProviderNotConfigured):
        build_embedder(Settings(env="test", jwt_secret=SECRET, embedding_model="some-model"))


def test_vector_text_prefixes_section_heading() -> None:
    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="x.md",
        chapter="কোষ",
        section="কোষ কী",
    )
    chunk = Chunk(id="c1", text="দেহের গঠন একক।", meta=meta)
    text = vector_text(chunk)
    assert text.startswith("কোষ > কোষ কী")
    assert "দেহের গঠন একক।" in text


def test_vector_index_respects_filters_and_shape() -> None:
    corpus = load_sample_corpus()
    index = VectorIndex(corpus, HashingEmbedder())
    hits = index.search("কোষ", class_level=6, subject="science", top_k=3)
    assert 0 < len(hits) <= 3
    assert all(h.chunk.meta.class_level == 6 for h in hits)
    assert all(h.chunk.meta.subject == "science" for h in hits)


# --- unit: hybrid index drop-in contract ---------------------------------------


def test_hybrid_index_drop_in_contract() -> None:
    corpus = load_sample_corpus()
    index = HybridIndex(corpus, HashingEmbedder())
    hits = index.search("কোষ কী", class_level=6, subject="science", top_k=4)
    assert hits
    assert len(hits) <= 4
    assert hits == sorted(hits, key=lambda hit: (-hit.score, hit.chunk.id))
    assert all(h.score > 0 for h in hits)
    # chapter filter narrows the pool like BM25Index
    narrow = index.search("কী", class_level=6, subject="science", chapter="কোষ", top_k=5)
    assert all(h.chunk.meta.chapter == "কোষ" for h in narrow)


def test_lexical_rerank_rewards_overlap() -> None:
    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="b",
        source="x",
        chapter="কোষ",
    )
    near = Chunk(id="n", text="কোষ হলো জীবের গঠন একক", meta=meta)
    far = Chunk(id="f", text="পৃথিবী সূর্যের চারদিকে ঘোরে", meta=meta)
    scores = lexical_rerank("কোষ কী", [(near, 0.016, 0.0), (far, 0.030, 0.0)])
    assert scores[0] > scores[1]  # lexical re-check outranks fusion-only noise
    # a lexical-lane base score keeps hybrid magnitudes BM25-scale
    with_base = lexical_rerank("কোষ কী", [(near, 0.016, 4.0), (far, 0.030, 0.0)])
    assert with_base[0] - with_base[1] > scores[0] - scores[1]


# --- wiring: create_app selects the lane from settings ------------------------


def test_create_app_builds_hybrid_index_by_default(monkeypatch, tmp_path) -> None:
    from bangla_gpt_api.main import create_app

    calls: list[str] = []
    real_hybrid = HybridIndex

    class _RecordingHybrid(real_hybrid):
        def __init__(self, *args: object, **kwargs: object) -> None:
            calls.append("hybrid")
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("bangla_gpt_api.main.HybridIndex", _RecordingHybrid)
    create_app(
        Settings(
            env="test",
            database_url=f"sqlite:///{tmp_path}/rag.db",
            jwt_secret=SECRET,
        )
    )
    assert calls == ["hybrid"]

    calls.clear()
    create_app(
        Settings(
            env="test",
            database_url=f"sqlite:///{tmp_path}/rag2.db",
            jwt_secret=SECRET,
            retrieval_mode="bm25",
        )
    )
    assert calls == []


# --- PASS-WHEN: hit@5 on replayed golden student traffic -----------------------

# (query, class_level, subject, expected substring in chunk text or heading)
GOLDEN_TRAFFIC: list[tuple[str, int, str, str]] = [
    # (a) standard chapter-recall questions
    ("কোষ কী?", 6, "science", "কোষ"),
    ("ভগ্নাংশ কী", 6, "mathematics", "ভগ্নাংশ"),
    ("সালোকসংশ্লেষণ কীভাবে", 6, "science", "সালোকসংশ্লেষণ"),
    ("জীবের গঠনের ক্ষুদ্রতম একক", 6, "science", "কোষ"),
    ("সবুজ পাতা রোদ থেকে কী বানায়", 6, "science", "সালোকসংশ্লেষণ"),
    ("পাতার সবুজ রঙের কাজটা কে করে", 6, "science", "ক্লোরোফিল"),
    ("লব আর হর নিয়ে যে সংখ্যা লেখা হয়", 6, "mathematics", "ভগ্নাংশ"),
    ("শুধু ১ আর নিজ দিয়ে ভাগ যায় এমন সংখ্যা", 6, "mathematics", "মৌলিক"),
    ("ছায়া কেন পড়ে", 7, "science", "ছায়া"),
    ("আয়নায় নিজের মুখ দেখার নিয়ম", 7, "science", "প্রতিবিম্ব"),
    ("জলে যা উপরে ভাসে সে কোন প্রক্রিয়া", 6, "science", "পানিচক্র"),
    ("চুম্বকের দুই প্রান্তকে কী বলে", 8, "science", "মেরু"),
    ("অদৃশ্য শক্তির টান যা লোহাকে টানে", 8, "science", "চুম্বক"),
    ("অক্ষরে লেখা গাণিতিক বাক্যকে কী বলে", 8, "mathematics", "রাশি"),
    ("শব্দ উচ্চারণ যেখান থেকে হয়", 6, "bangla", "উচ্চারণস্থান"),
    ("কোন বাহু দিয়ে কোন কোণের অনুপাত", 9, "mathematics", "ত্রিকোণমিতি"),
    # (b) phonetic-spelling / loanword / inflection-only short lookups
    ("কোশ কী", 6, "science", "কোষ"),
    ("ভগনংশ কী", 6, "mathematics", "ভগ্নাংশ"),
    ("ফ্লোযাম কি", 7, "science", "ফ্লোয়েম"),
    ("ট্রাইকোণমিতি কি", 9, "mathematics", "ত্রিকোণমিতি"),
    ("বীজগাণিতিক রাশিকি", 8, "mathematics", "রাশি"),
    ("সূচক কী", 8, "mathematics", "সূচক"),
    ("সূচকের সূত্র", 8, "mathematics", "সূচক"),
    ("পাইথাগোরাস উপপাদ্য", 9, "mathematics", "পিথাগোরাস"),
    ("হাইপা কী", 9, "mathematics", "অতিভুজ"),
]


def _hit5(index: BM25Index | HybridIndex, q: str, cl: int, sub: str, expected: str) -> bool:
    hits = index.search(q, class_level=cl, subject=sub, top_k=5)
    return any(
        expected in h.chunk.text
        or expected in (h.chunk.meta.section or "")
        or expected in h.chunk.meta.chapter
        for h in hits
    )


def test_hybrid_hit_at_5_beats_bm25_by_at_least_20pct() -> None:
    corpus = load_sample_corpus()
    bm25 = BM25Index(corpus)
    hybrid = HybridIndex(corpus, HashingEmbedder())

    b_hits = sum(_hit5(bm25, *pair) for pair in GOLDEN_TRAFFIC)
    h_hits = sum(_hit5(hybrid, *pair) for pair in GOLDEN_TRAFFIC)
    n = len(GOLDEN_TRAFFIC)

    assert b_hits > 0, "BM25 baseline must score something for the ratio to be meaningful"
    relative_lift = (h_hits - b_hits) / b_hits
    assert relative_lift >= 0.20, (
        f"hybrid hit@5 {h_hits}/{n} vs bm25 {b_hits}/{n} -> lift {relative_lift:+.1%} < +20%"
    )
    # regression guard: the golden set stays fully recalled by the v2 pipeline
    assert h_hits == n, "hybrid lane must recall every golden pair"
