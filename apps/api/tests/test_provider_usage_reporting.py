"""T-23/BC-9: provider-reported usage extraction and ledger precedence."""

from __future__ import annotations

import threading

from bangla_gpt_api.providers.base import ProviderUsage, UsageReportingMixin
from bangla_gpt_api.providers.gemini import _gemini_usage
from bangla_gpt_api.providers.openai import _openai_usage
from bangla_gpt_api.services.costs import finalize_ai_usage


class _FakeDB:
    """finalize only calls db.add(row); a one-method stand-in avoids a real
    Session for a pure ledger-math test."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def test_gemini_usage_extracted_from_response_metadata():
    body = {
        "usageMetadata": {
            "promptTokenCount": 120,
            "candidatesTokenCount": 45,
            "totalTokenCount": 165,
        }
    }
    usage = _gemini_usage(body, prompt_chars=100, answer_chars=50)
    assert usage.usage_source == "provider"
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (120, 45, 165)


def test_gemini_usage_falls_back_to_estimated_label():
    usage = _gemini_usage({}, prompt_chars=100, answer_chars=50)
    assert usage.usage_source == "estimated"


def test_openai_usage_extracted_from_response_usage():
    body = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    usage = _openai_usage(body)
    assert usage.usage_source == "provider"
    assert usage.total_tokens == 15


def test_openai_usage_falls_back_to_estimated_label():
    assert _openai_usage({}).usage_source == "estimated"


def test_take_last_usage_is_thread_local_and_consuming():
    class P(UsageReportingMixin):
        pass

    provider = P()
    provider.record_usage(ProviderUsage(1, 2, 3))
    assert provider.take_last_usage() == ProviderUsage(1, 2, 3)
    # consumed: a stale report cannot be billed to a later request
    assert provider.take_last_usage() is None

    seen: dict = {}

    def worker():
        seen["value"] = provider.take_last_usage()

    provider.record_usage(ProviderUsage(9, 9, 9))
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert seen["value"] is None, "another thread must not see this thread's usage"
    assert provider.take_last_usage() == ProviderUsage(9, 9, 9)


def test_finalize_prefers_provider_reported_completion_tokens():
    class Row:
        def __init__(self):
            self.model = "gemini-2.5-flash"
            self.prompt_tokens = 999  # would be a huge estimate if used
            self.completion_tokens = 0
            self.estimated_cost_usd = 0.0

    row = Row()
    finalize_ai_usage(
        _FakeDB(), row, model=None, answer_text="x" * 400, completion_tokens_override=45
    )
    assert row.completion_tokens == 45, "provider-reported count must beat the estimate"

    row2 = Row()
    finalize_ai_usage(
        _FakeDB(),
        row2,
        model=None,
        answer_text=None,
        completion_tokens_override=None,
        prompt_tokens_override=120,
    )
    assert row2.prompt_tokens == 120


def test_finalize_without_overrides_still_estimates():
    class Row:
        def __init__(self):
            self.model = "mock"
            self.prompt_tokens = 10
            self.completion_tokens = 0
            self.estimated_cost_usd = 0.0

    row = Row()
    finalize_ai_usage(_FakeDB(), row, model=None, answer_text="abcd" * 100)
    assert row.completion_tokens > 0, "no override -> the char heuristic stands"
