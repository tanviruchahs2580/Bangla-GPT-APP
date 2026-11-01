"""Language-integrity metrics on generated answers (RAG-21 deterministic legs).

The master requirement is "a Bangla question gets a Bangla answer and zero
Assamese letters". Both legs are deterministic and run under the mock provider;
the register/fluency legs remain a human or model judgement and the CLI labels
them UNVERIFIED-LIVE. The repo's own unicode gate uses U+09F0/U+09F1 for
Assamese r/rh, and these tests use the same two codepoints.
"""

from __future__ import annotations

import asyncio

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation.metrics import (
    assamese_letters,
    bengali_letter_share,
    language_verdict,
    run_suite,
)
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService

_BANGLA_QUESTION = "কোষ কী?"
_BANGLA_ANSWER = "কোষ হলো জীবদেহের গঠন ও কার্যের একক।"
_ENGLISH_ANSWER = "The cell is the structural and functional unit of life."


def test_bangla_question_with_bangla_answer_is_consistent() -> None:
    verdict = language_verdict(_BANGLA_QUESTION, _BANGLA_ANSWER)
    assert verdict["bengali_question"] is True
    assert verdict["consistent"] is True
    assert verdict["assamese"] == 0


def test_bangla_question_with_english_answer_is_inconsistent() -> None:
    verdict = language_verdict(_BANGLA_QUESTION, _ENGLISH_ANSWER)
    assert verdict["bengali_question"] is True
    assert verdict["consistent"] is False


def test_english_question_is_not_judged_for_consistency() -> None:
    verdict = language_verdict("what is a cell?", _ENGLISH_ANSWER)
    assert verdict["bengali_question"] is False
    assert verdict["consistent"] is True


def test_assamese_letters_are_counted() -> None:
    # U+09F0 (Assamese ra) and U+09F1 (Assamese va) inside an otherwise Bangla
    # sentence: the repo's bn_scan gate rejects exactly these codepoints.
    contaminated = "\u09f0\u09f1 কাপ"
    assert assamese_letters(contaminated) == 2
    assert assamese_letters(_BANGLA_ANSWER) == 0
    verdict = language_verdict(_BANGLA_QUESTION, contaminated)
    assert verdict["assamese"] == 2


def test_bengali_share_counts_script_not_punctuation() -> None:
    assert bengali_letter_share("কোষ ১২৩।") == 1.0  # Bengali digits are script
    assert bengali_letter_share("abc") == 0.0
    assert bengali_letter_share("কোষ cell") == 0.4286  # 3 Bengali / 7 total
    assert bengali_letter_share("123.") == 0.0  # ASCII digits are not letters


def test_suite_reports_language_metrics_on_the_mock_stack() -> None:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    tutor = TutorService(index=index, provider=MockLLMProvider(), term_stats=index.term_stats)
    items = [
        {"question": _BANGLA_QUESTION, "class_level": 6, "subject": "science", "expect": "answer"},
        {
            "question": "মঙ্গল গ্রহে প্রাণ আছে?",
            "class_level": 6,
            "subject": "science",
            "expect": "refuse",
        },
    ]
    metrics = asyncio.run(run_suite(tutor, items))
    assert metrics.language_consistency == 1.0
    assert metrics.assamese_letter_violations == 0
    assert metrics.language_violations == []
