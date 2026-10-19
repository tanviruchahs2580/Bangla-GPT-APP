"""A9-01: the stage harness measures the real pipeline, honestly.

The tests pin the properties that make the numbers usable: every stage is
present on the path that has it and *absent* (not zero) on the path that does
not, the remainder stage accounts for the wall time, TTFT exists only on the
streaming path, and the instrumentation leaves the tutor exactly as it found
it.
"""

from __future__ import annotations

import asyncio

import pytest

from bangla_gpt_api.evaluation import stage_latency
from bangla_gpt_api.evaluation.harness import build_hermetic_tutor, hermetic_settings


@pytest.fixture(scope="module")
def tutor():
    return build_hermetic_tutor(hermetic_settings())


def test_ask_path_records_its_stages_and_not_the_stream_only_one(tutor) -> None:
    with stage_latency._Instrumentation(tutor):  # noqa: SLF001 - measuring the harness
        samples = asyncio.run(
            stage_latency._one_ask(tutor, "কোষ কী?", 6, "science")  # noqa: SLF001
        )
    for stage in (
        "retrieval_ms",
        "context_build_ms",
        "provider_select_ms",
        "llm_total_ms",
        "post_process_ms",
        "query_processing_ms",
    ):
        assert stage in samples.measured, stage
    assert "llm_ttft_ms" not in samples.measured, "the non-streaming path has no first token"
    assert samples.llm_total_ms <= samples.wall_ms


def test_stream_path_records_ttft_and_not_the_assemble_stage(tutor) -> None:
    with stage_latency._Instrumentation(tutor):  # noqa: SLF001
        sample = asyncio.run(
            stage_latency._one_stream(tutor, "কোষ কী?", 6, "science")  # noqa: SLF001
        )
    assert "llm_ttft_ms" in sample.measured
    assert sample.llm_ttft_ms is not None and sample.llm_ttft_ms > 0
    assert sample.llm_ttft_ms <= sample.llm_total_ms <= sample.wall_ms
    assert "post_process_ms" not in sample.measured, (
        "ask_stream never calls _assemble; a 0.0 would be a stage nobody measured"
    )


def test_stages_sum_to_the_wall_clock(tutor) -> None:
    with stage_latency._Instrumentation(tutor):  # noqa: SLF001
        sample = asyncio.run(
            stage_latency._one_ask(tutor, "ভগ্নাংশ কী?", 6, "mathematics")  # noqa: SLF001
        )
    instrumented = (
        sample.retrieval_ms
        + sample.context_build_ms
        + sample.provider_select_ms
        + sample.llm_total_ms
        + sample.post_process_ms
    )
    assert sample.query_processing_ms == pytest.approx(
        max(sample.wall_ms - instrumented, 0.0), abs=0.01
    )
    assert instrumented <= sample.wall_ms + 0.01


def test_rerank_is_a_substage_of_retrieval(tutor) -> None:
    with stage_latency._Instrumentation(tutor):  # noqa: SLF001
        sample = asyncio.run(
            stage_latency._one_ask(tutor, "সালোকসংশ্লেষণ কী?", 6, "science")  # noqa: SLF001
        )
    assert 0 < sample.rerank_ms <= sample.retrieval_ms


def test_instrumentation_is_restored_on_exit(tutor) -> None:
    before = (tutor._retrieve_and_gate, tutor._assemble, tutor.index.reranker)  # noqa: SLF001
    with stage_latency._Instrumentation(tutor):  # noqa: SLF001
        assert tutor._retrieve_and_gate is not before[0]  # noqa: SLF001
    after = (tutor._retrieve_and_gate, tutor._assemble, tutor.index.reranker)  # noqa: SLF001
    assert after == before


def test_level_report_shape_and_budget_rows(tutor) -> None:
    level = asyncio.run(
        stage_latency.run_level(
            tutor,
            list(stage_latency.QUESTIONS[:3]),
            concurrency=2,
            iterations=6,
            mode="ask",
        )
    )
    assert level["concurrency"] == 2
    for stage, block in level["stages"].items():
        if block["n"] == 0:
            continue
        assert block["p50_ms"] <= block["p95_ms"] <= block["p99_ms"], stage
    row = stage_latency.budgets_row(level)
    assert row["retrieval_within_budget"] is (row["retrieval_p95_ms"] <= 300)
    assert row["ttft_p95_ms"] is None, "the ask mode carries no TTFT reading"
    assert set(row) >= {"full_answer_p95_ms", "full_answer_budget_ms"}


def test_markdown_hides_stages_that_never_ran() -> None:
    report = {
        "levels": [
            {
                "concurrency": 1,
                "mode": "ask",
                "stages": {
                    "retrieval_ms": {"n": 5, "p50_ms": 1.0, "p95_ms": 2.0, "p99_ms": 2.0},
                    "llm_ttft_ms": {"n": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0},
                },
                "full_answer": {"wall_ms": {"n": 5, "p50_ms": 3.0, "p95_ms": 4.0, "p99_ms": 4.0}},
            }
        ]
    }
    markdown = stage_latency.markdown_summary(report)
    assert "retrieval_ms" in markdown and "full_answer" in markdown
    assert "llm_ttft_ms" not in markdown
