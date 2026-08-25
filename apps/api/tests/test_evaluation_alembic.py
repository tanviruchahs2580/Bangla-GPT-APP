import json
import pathlib

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation.runner import EvalQuestion, evaluate_questions
from bangla_gpt_api.providers import get_provider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.tutor import TutorService


@pytest.mark.asyncio
async def test_evaluation_harness_scores_grounding_correctly() -> None:
    settings = Settings(env="test")
    index = BM25Index(load_sample_corpus())
    provider = get_provider(settings)
    tutor = TutorService(index=index, provider=provider)

    questions = [
        EvalQuestion(question="কোষ কী?", class_level=6, subject="science", expected_grounded=True),
        EvalQuestion(
            question="ভগ্নাংশ কী?", class_level=7, subject="mathematics", expected_grounded=True
        ),
        EvalQuestion(
            question="বিশ্বকাপ ফুটবল কে জিতেছিল?",
            class_level=6,
            subject="science",
            expected_grounded=False,
        ),
        EvalQuestion(
            question="zzqq blorg", class_level=6, subject="science", expected_grounded=False
        ),
    ]
    result = await evaluate_questions(tutor, questions)
    assert result.total == 4
    assert result.accuracy == 1.0
    assert result.failures == []


@pytest.mark.asyncio
async def test_sample_questions_file_is_loadable_and_scores_perfectly(tmp_path) -> None:
    source = pathlib.Path("eval/sample_questions.json")
    if not source.exists():
        source = pathlib.Path(__file__).parent.parent / "eval" / "sample_questions.json"
    items = json.loads(source.read_text(encoding="utf-8"))
    assert len(items) == 10
    settings = Settings(env="test")
    tutor = TutorService(index=BM25Index(load_sample_corpus()), provider=get_provider(settings))
    questions = [EvalQuestion(**row) for row in items]
    result = await evaluate_questions(tutor, questions)
    assert result.accuracy == 1.0, f"failures: {result.failures}"


def test_alembic_versions_directory_contains_initial_migration() -> None:
    versions = pathlib.Path("alembic/versions")
    if not versions.exists():
        versions = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
    py_files = [f for f in versions.iterdir() if f.suffix == ".py" and not f.name.startswith("__")]
    assert py_files, "expected at least one Alembic revision"
    assert any("initial" in f.name.lower() for f in py_files)
