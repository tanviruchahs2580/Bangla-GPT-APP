"""Honest metering and diagnostics for locally-produced refusals.

Three gaps: (1) /tutor/ask finalized a REFUSAL's ledger line with the
refusal copy as answer text, charging template bytes as completion tokens —
RAG-27 says a locally-produced refusal is not a model completion (the
same rule retrieval-only answers already follow); (2) a vision-unsupported
chat turn left its reserved ledger row forever unfinalized, the one
shape no caller knows how to finish (BE-FIX-003 docstring); (3) the
saturated-lane refusal (ai_busy) produced no answer trace at all, so the
per-answer diagnostic store has a blind spot for every busy turn.
"""

from __future__ import annotations

import asyncio
import base64

from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.evaluation.observability import AnswerTraceStore
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import GenerationBusyError, TutorService
from conftest import engine_url

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "supersecret1"
# 1x1 transparent PNG (a real, decodable image) — payload sniffing refuses
# anything else before the vision contract even applies.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _settings(tmp_path, **over) -> Settings:
    base = dict(env="test", database_url=engine_url(tmp_path, "honesty"), jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _student_headers(client: TestClient) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": "s@example.com",
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "s@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ledger(tmp_path) -> list[AiUsage]:
    engine = make_engine(_settings(tmp_path))
    with make_session_factory(engine)() as db:
        return list(db.execute(select(AiUsage).order_by(AiUsage.id)).scalars())


# 1. grounding refusal is not charged as a completion -------------------------


def test_grounding_refusal_finalizes_zero_completion(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _student_headers(client)
    # Out of corpus: the gate refuses with INSUFFICIENT_EVIDENCE locally —
    # no provider call ever happened.
    res = client.post(
        "/tutor/ask",
        json={"question": "মঙ্গল গ্রহে কি মানুষ বাস করে?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["grounded"] is False
    assert body["refused_reason"] == "insufficient_evidence"

    rows = _ledger(tmp_path)
    assert len(rows) == 1, "the reserved turn must own exactly one ledger line"
    assert rows[0].prompt_tokens > 0, "the prompt-side estimate is honest spend"
    assert rows[0].completion_tokens == 0, (
        "the refusal copy is generated locally; charging it as completions "
        "invents provider spend that never happened"
    )


# 2. vision-unsupported chat turn finalizes its reserve -----------------------


def test_vision_unsupported_turn_finalizes_with_an_abandon_marker(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    headers = _student_headers(client)
    conv = client.post("/tutor/conversations", json={}, headers=headers).json()
    image = {
        "mime_type": "image/png",
        "data_base64": base64.b64encode(TINY_PNG).decode(),
    }
    res = client.post(
        f"/tutor/conversations/{conv['id']}/messages",
        json={"message": "এই ছবিতে কী আছে?", "image": image},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["refused_reason"] == "vision_unsupported"

    rows = _ledger(tmp_path)
    assert len(rows) == 1, "the reserve exists; it must not be left in flight shape"
    assert rows[0].completion_tokens == 0, "no provider call happened for a local refusal"
    assert rows[0].route.endswith("vision_unsupported"), rows[0].route
    assert not rows[0].route.endswith("vision_unsupported" * 2)


# 3. saturated lane records its trace -----------------------------------------


def _busy_tutor(store: AnswerTraceStore) -> TutorService:
    index = HybridIndex(_corpus(), build_embedder(Settings(env="test")))
    tutor = TutorService(index=index, provider=MockLLMProvider(), trace_store=store)

    async def saturated(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise GenerationBusyError("generation lane saturated")

    tutor._generate = saturated.__get__(tutor)  # type: ignore[method-assign]
    return tutor


def _corpus():
    from bangla_gpt_api.data.loader import load_sample_corpus

    return load_sample_corpus()


def test_saturated_lane_records_an_ai_busy_trace() -> None:
    store = AnswerTraceStore(capacity=4)
    tutor = _busy_tutor(store)
    response = asyncio.run(tutor.ask("কোষ কী?", 6, "science"))
    assert response.refused_reason == "ai_busy"
    traces = store.recent(4)
    assert traces, "a busy turn is invisible to per-answer diagnostics today"
    assert traces[-1].outcome == "ai_busy"


def test_saturated_stream_records_an_ai_busy_trace() -> None:
    store = AnswerTraceStore(capacity=4)
    tutor = _busy_tutor(store)

    async def saturated_stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise GenerationBusyError("generation lane saturated")
        yield  # pragma: no cover - makes this an async generator

    tutor._stream_with_fallback = saturated_stream.__get__(tutor)  # type: ignore[method-assign]

    async def run() -> None:
        async for _event in tutor.ask_stream("কোষ কী?", 6, "science"):
            pass

    asyncio.run(run())
    traces = store.recent(4)
    assert traces, "a busy stream turn is invisible to diagnostics today"
    assert [t.outcome for t in traces] == ["ai_busy"], traces
