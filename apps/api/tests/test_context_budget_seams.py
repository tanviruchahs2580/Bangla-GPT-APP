"""Service-seam tests: the history budget prunes ONLY the prompt copy.

The settled D3 boundary: the router-capped history reaches retrieval
INTACT (follow-up resolution depends on it), and only the transient
history copy handed to prompt construction is pruned -- after the
grounding gate and evidence assembly, immediately before
``_prompt_blocks``. These tests prove both halves on the real service
with a real sample-corpus index, plus the privacy contract of the
``context_history_pruned`` diagnostic (counts only, never content).
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.logging_config import request_id_var
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid import tokenize
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService

# Synthetic sentinels only -- never real student wording. DROPPED tokenises
# to 5 tokens, RETAINED to 2, so a 2-token budget retains exactly the newest
# item and drops the oldest one.
DROPPED = "পুরোনো গোপন বার্তা নমুনা শব্দ"
RETAINED = "সংক্ষিপ্ত উত্তর"
QUESTION = "উদ্ভিদ কোষের গঠন কী?"
#: the exact field allowlist of the context_history_pruned event
LOG_ALLOWLIST = {
    "history_budget_units",
    "kept_items",
    "dropped_items",
    "kept_units",
    "dropped_units",
}


class _RecordingProvider:
    """Minimal provider that records every prompt it is handed."""

    name = "recording"
    supports_vision = False

    def __init__(self, answer: str = "নমুনা উত্তর") -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def generate(self, prompt, *, system=None, image=None):  # noqa: ANN001
        self.prompts.append(prompt)
        return self.answer

    async def stream(self, prompt, *, system=None, image=None):  # noqa: ANN001
        self.prompts.append(prompt)
        for piece in self.answer.split(" "):
            yield piece


@pytest.fixture(scope="module")
def index() -> HybridIndex:
    return HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))


def _tutor(index: HybridIndex, provider: _RecordingProvider, budget: int) -> TutorService:
    return TutorService(index=index, provider=provider, history_token_budget=budget)


def _history() -> list[dict[str, str]]:
    return [
        {"role": "user", "content": DROPPED},
        {"role": "assistant", "content": RETAINED},
    ]


def _spy_retrieval_history(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture the history list the retrieval seam actually receives."""
    seen: dict = {}
    original = TutorService._conversation_retrieval_query

    def spy(self, question, history):  # noqa: ANN001
        seen["history"] = list(history) if history is not None else None
        return original(self, question, history)

    monkeypatch.setattr(TutorService, "_conversation_retrieval_query", spy)
    return seen


# ------------------------------------------------------------------- ask() --


def test_ask_retrieval_sees_full_history_prompt_gets_only_suffix(
    index: HybridIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _RecordingProvider()
    tutor = _tutor(index, provider, budget=2)
    seen = _spy_retrieval_history(monkeypatch)
    history = _history()
    snapshot = [dict(m) for m in history]

    asyncio.run(tutor.ask(QUESTION, 6, "science", history))

    assert seen["history"] == snapshot, "retrieval must see the FULL router-capped history"
    assert history == snapshot, "the caller's history must not be mutated"
    assert provider.prompts, "the provider must have been called"
    prompt = provider.prompts[0]
    assert RETAINED in prompt, "the retained suffix must still be rendered"
    assert DROPPED not in prompt, "the dropped turn must not reach the provider prompt"
    assert "পাঠ্যবইয়ের অংশ:" in prompt, "evidence rendering is unchanged"
    assert QUESTION in prompt, "the current question is never dropped"


# ------------------------------------------------------------- ask_stream() --


def test_stream_applies_the_same_pruning_policy(
    index: HybridIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _RecordingProvider()
    tutor = _tutor(index, provider, budget=2)
    seen = _spy_retrieval_history(monkeypatch)
    history = _history()
    snapshot = [dict(m) for m in history]

    async def run() -> None:
        async for _event in tutor.ask_stream(QUESTION, 6, "science", history):
            pass

    asyncio.run(run())

    assert seen["history"] == snapshot, "streaming retrieval must also see the FULL history"
    assert history == snapshot
    prompt = provider.prompts[0]
    assert RETAINED in prompt
    assert DROPPED not in prompt


# --------------------------------------------------------- no-op preservation --


def test_pruning_preserves_extra_fields_on_retained_history() -> None:
    provider = _RecordingProvider()
    tutor = TutorService(index=None, provider=provider, history_token_budget=2)  # type: ignore[arg-type]
    history = [
        {"role": "user", "content": DROPPED, "source": "synthetic-old"},
        {"role": "assistant", "content": RETAINED, "source": "synthetic-new"},
    ]

    prompt_history = tutor._prune_prompt_history(history)

    assert prompt_history == [history[1]]
    assert prompt_history is not None
    assert prompt_history[0]["source"] == "synthetic-new"
    assert DROPPED not in [item["content"] for item in prompt_history]


def test_prompt_is_byte_identical_when_the_budget_does_not_bind(index: HybridIndex) -> None:
    """Feature lock: a history that fits must produce exactly the prompt the
    service always produced -- a binding-just-at-total budget and a huge
    budget must agree byte for byte."""
    huge = _RecordingProvider()
    exact = _RecordingProvider()
    history = _history()

    asyncio.run(_tutor(index, huge, 10**9).ask(QUESTION, 6, "science", history))
    total = sum(len(tokenize(m["content"])) for m in history)
    asyncio.run(_tutor(index, exact, total).ask(QUESTION, 6, "science", history))

    assert huge.prompts[0] == exact.prompts[0]


# ---------------------------------------------------------------- diagnostics --


def test_prune_event_is_count_only_without_request_id(
    index: HybridIndex, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    provider = _RecordingProvider()
    tutor = _tutor(index, provider, budget=2)
    _spy_retrieval_history(monkeypatch)
    token = request_id_var.set("synthetic-request-id")
    try:
        asyncio.run(tutor.ask(QUESTION, 6, "science", _history()))
    finally:
        request_id_var.reset(token)

    records = [r for r in caplog.records if getattr(r, "event", None) == "context_history_pruned"]
    if not records:
        # json_log writes the whole payload as the record's message; fall back
        # to parsing the message JSON for the event name.
        records = [
            r
            for r in caplog.records
            if isinstance(r.msg, str) and '"context_history_pruned"' in r.msg
        ]
    assert len(records) == 1, "a no-op plan emits no event; a pruning plan emits exactly one"
    payload = json.loads(records[0].msg)
    assert set(payload) <= {"event"} | LOG_ALLOWLIST, payload
    assert set(payload) >= LOG_ALLOWLIST, payload
    assert payload["history_budget_units"] == 2
    assert payload["dropped_items"] == 1
    assert payload["kept_items"] == 1
    assert payload["kept_units"] == len(tokenize(RETAINED))
    assert payload["dropped_units"] == len(tokenize(DROPPED))
    assert DROPPED not in caplog.text, "dropped student text must never reach the logs"
    assert "synthetic-request-id" not in records[0].msg
