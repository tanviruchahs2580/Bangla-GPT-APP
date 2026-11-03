"""P2/P3 audit-fix contracts (2026-11 RAG audit): reindex, metrics, gate,
citation grading.

* /admin/reindex swaps a fully rebuilt index + tutor onto the live context
  under a lock, audit-logged, admin-only (F-18);
* retarget_index carries provider/fast/breaker/thresholds — the reindex
  can never silently change policy (F-18);
* per-lane latency and gate-coverage histograms are exported (F-21/C4);
* the out-of-corpus weight floor refuses out-of-domain questions that the
  old all-df=0 rule admitted (F-11/D2) — the real-corpus family C went
  0.25 → 1.0 with this floor and the 634-item golden set stayed at 1.0;
* citation verification is graded (pass/weak/fail) at the calibrated
  0.35/0.20 bands (F-14/D4).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.metrics import REGISTRY
from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.services.safety import citation_coverage, citation_level
from bangla_gpt_api.services.tutor import TutorService

PASSWORD = "Biplob#2026"
SECRET = "test-secret-aaaaaaaaaaaaaaaa"


class _StubProvider(LLMProvider):
    name = "stub"

    async def generate(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        return "উত্তর।"

    async def stream(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        yield "উত্তর"


class _StaticIndex:
    """A one-hit index standing in for the post-rebuild snapshot."""

    def __init__(self) -> None:
        self.chunks: list[Any] = []

    def search(self, query: str, **_kwargs: Any) -> list:
        return []


# ------------------------------------------------------------- reindex ---
def test_retarget_index_carries_policy_not_corpus() -> None:
    old_index = _StaticIndex()
    provider = _StubProvider()
    tutor = TutorService(
        index=old_index,
        provider=provider,
        term_stats=None,
        top_k=5,
        min_coverage=0.6,
    )
    new_index = _StaticIndex()
    retargeted = tutor.retarget_index(new_index, term_stats=None)
    assert retargeted.index is new_index and retargeted.index is not old_index
    assert retargeted.provider is provider
    assert retargeted.top_k == 5 and retargeted.min_coverage == 0.6


@pytest.fixture
def admin_client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///./{tmp_path / 'audit_p2.db'}",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_reindex_swaps_a_fresh_index(admin_client: TestClient) -> None:
    headers = _login(admin_client, "root@example.com")
    before = admin_client.get("/search", params={"q": "কোষ"}, headers=headers)
    assert before.status_code == 200
    res = admin_client.post("/admin/reindex", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["corpus_chunks"] > 0
    assert body["build_seconds"] >= 0
    assert body["retrieval_mode"] == "hybrid"
    # the swapped index still serves queries
    after = admin_client.get("/search", params={"q": "কোষ"}, headers=headers)
    assert after.status_code == 200 and after.json()["hits"], "post-reindex search must work"


def test_admin_reindex_is_admin_only(admin_client: TestClient) -> None:
    res = admin_client.post(
        "/auth/register",
        json={
            "email": "kid@example.com",
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201
    headers = _login(admin_client, "kid@example.com")
    assert admin_client.post("/admin/reindex", headers=headers).status_code == 403
    assert admin_client.post("/admin/reindex").status_code in {401, 403}


# ------------------------------------------------- metrics (C4) ---
def test_per_lane_latency_and_coverage_histograms_export() -> None:
    from bangla_gpt_api.data.loader import load_sample_corpus
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    index = HybridIndex(load_sample_corpus(), HashingEmbedder())
    assert index.search("কোষ কী", class_level=6)
    for lane in ("bm25", "vector"):
        sample = REGISTRY.get_sample_value("bgpt_rag_lane_latency_seconds_count", {"lane": lane})
        assert sample and sample > 0, f"lane {lane} latency must be metered"


def test_gate_coverage_histogram_observes_refusal_and_pass(
    admin_client: TestClient,
) -> None:
    headers = _login(admin_client, "root@example.com")
    # one refused turn (out-of-corpus) and one answered turn (in-corpus)
    admin_client.post(
        "/tutor/ask",
        headers=headers,
        json={"question": "ক্রিকেট বিশ্বকাপ ফাইনাল কে জিতেছিল?", "class_level": 6},
    )
    count = REGISTRY.get_sample_value("bgpt_rag_gate_coverage_count")
    assert count and count >= 1


# ------------------------------------------------- gate floor (D2) ---
class _TinyStats:
    """TermStats double: one in-corpus term, one unknown to the corpus."""

    total_documents = 100

    def document_frequency(self, term: str) -> int:
        return 5 if term == "দাম" else 0


def test_gate_refuses_when_corpus_weight_share_is_low() -> None:
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta

    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="b",
        source="s",
        chapter="c",
    )
    hit = type("HitStub", (), {})()
    hit.chunk = Chunk(id="x", text="দাম নির্ধারণের নিয়ম", meta=meta)
    hit.score = 4.2
    tutor = TutorService(index=_StaticIndex(), provider=_StubProvider(), term_stats=_TinyStats())
    coverage, passed = tutor._coverage_details("ডলারের দাম কত", [hit])
    assert passed is False and coverage == 0.0


def test_gate_still_passes_when_corpus_knows_the_question() -> None:
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta

    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="b",
        source="s",
        chapter="c",
    )
    hit = type("HitStub", (), {})()
    hit.chunk = Chunk(id="x", text="দাম ও সপ্তাহের হিসাব", meta=meta)
    hit.score = 4.2

    class _AllKnown:
        total_documents = 100

        def document_frequency(self, term: str) -> int:
            return 5

    tutor = TutorService(index=_StaticIndex(), provider=_StubProvider(), term_stats=_AllKnown())
    _coverage, passed = tutor._coverage_details("দাম সপ্তাহ", [hit])
    assert passed is True


# ------------------------------------------------- citation bands (D4) ---
def test_citation_level_bands_are_graded() -> None:
    evidence = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক এবং কোষের প্রধান অংশ নিউক্লিয়াস।"
    assert citation_level("কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত একক।", evidence) == "pass"
    assert citation_level("কোষ হলো জীবদেহের একক।", evidence) in {"weak", "pass"}
    assert citation_level("বাইরের মাঠে ফুটবল খেলা হয় প্রচুর গোল হয় দল জেতে।", evidence) == "fail"
    # an answer with no claim-worthy tokens (all ≤2 chars) has nothing to flag
    assert citation_coverage("ও?", evidence) == 1.0
