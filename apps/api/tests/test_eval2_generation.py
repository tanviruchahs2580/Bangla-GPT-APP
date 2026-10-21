"""A8-04: generation metric definitions and the judge-agreement harness.

Every definition is pinned on hand-built responses whose expected value is
known by construction; the end-to-end case drives the real tutor over a few
golden items with the mock provider (hermetic).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation import generation as gen
from bangla_gpt_api.evaluation import judge as judge_mod
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.answer_structure import (
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
)
from bangla_gpt_api.services.tutor import TutorService

API_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = API_ROOT / "eval" / "golden_v2.json"


def _source(chapter: str, section: str) -> SourceRef:
    return SourceRef(book="বিজ্ঞান", chapter=chapter, section=section, page=1, score=1.0)


def _valid_answer() -> str:
    return (
        f"[mock] {SECTION_SIMPLE} কোষ হলো জীবদেহের একক।\n"
        f"{SECTION_EXAMPLE} কোষের উদাহরণ।\n{SECTION_POINTS} - এক\n- দুই\n{SECTION_CHECK} বুঝেছ?"
    )


def test_language_rules_are_documented_and_enforced() -> None:
    assert gen.language_ok("কোষ হলো জীবদেহের একক।") is True
    assert gen.language_ok("The cell is the unit.") is False, "Latin-only is not Bangla"
    # U+09F0 (Assamese ra) is a mis-script character, never legitimate here
    assert gen.has_mis_script("ৰাষ্ট্ৰ") is True
    assert gen.language_ok("কোষ ৰ গঠন") is False
    assert gen.bangla_letter_share("123") == 0.0, "ASCII digits are not Bengali script"
    assert gen.bangla_letter_share("১২৩") == 1.0, "Bengali digits are"


def test_format_requires_labels_and_a_source() -> None:
    assert gen.format_ok(_valid_answer(), source_count=1) is True
    assert gen.format_ok(_valid_answer(), source_count=0) is False
    assert gen.format_ok("কোষ হলো একক।", source_count=3) is False


def test_source_matching_is_identity_on_the_pipelines_own_fields() -> None:
    source = _source("কোষ", "কোষ কী")
    assert gen.source_matches_gold(source, chapter="কোষ", section="কোষ কী") is True
    assert gen.source_matches_gold(source, chapter="কোষ", section=" কোষ   কী ") is True
    assert gen.source_matches_gold(source, chapter="কোষ", section="কোষের প্রধান অংশ") is False
    assert gen.source_matches_gold(source, chapter="কোষ", section=None) is True
    assert gen.source_matches_gold(source, chapter="বল ও গতি", section=None) is False
    assert gen.source_matches_chapter(source, chapter="কোষ") is True
    assert gen.source_matches_chapter(source, chapter="বল ও গতি") is False


def test_generation_metrics_count_every_defined_rate() -> None:
    rows = [
        {  # answerable, answered, one of two sources is the gold section
            "expect": "answer",
            "grounded": True,
            "sources": [_source("কোষ", "কোষ কী"), _source("কোষ", "ভিন্ন অংশ")],
            "gold_chapter": "কোষ",
            "gold_section": "কোষ কী",
            "answer": _valid_answer(),
        },
        {  # answerable but refused -> false refusal
            "expect": "answer",
            "grounded": False,
            "sources": [],
            "gold_chapter": "কোষ",
            "gold_section": "কোষ কী",
            "answer": "",
        },
        {  # unanswerable and refused -> correct abstention
            "expect": "refuse",
            "grounded": False,
            "sources": [],
            "gold_chapter": None,
            "gold_section": None,
            "answer": "",
        },
    ]
    metrics = gen.generation_metrics(rows, refusal_correct_unsafe=4, unsafe_total=4)
    assert metrics["citation_precision"] == 0.5
    assert metrics["citation_precision_chapter"] == 1.0
    assert metrics["citation_recall"] == 1.0
    assert metrics["abstention_precision"] == 0.5, "one of two refusals was unwarranted"
    assert metrics["abstention_recall"] == 1.0
    assert metrics["false_refusal_rate"] == 0.5
    assert metrics["refusal_correctness_unsafe"] == 1.0
    assert metrics["response_language_correctness"] == 1.0
    assert metrics["format_validity"] == 1.0
    assert metrics["grounded_items"] == 1 and metrics["refusals_total"] == 2


def test_kappa_is_chance_corrected_and_degenerate_safe() -> None:
    assert judge_mod.cohen_kappa([1, 0, 1, 0, 1], [1, 0, 1, 0, 1]) == 1.0
    # observed 0.75, chance 0.5 -> kappa 0.5
    assert judge_mod.cohen_kappa([1, 0, 1, 0], [1, 0, 1, 1]) == 0.5
    assert judge_mod.cohen_kappa([1, 1, 1], [1, 1, 1]) == 0.0, (
        "constant raters: no chance correction"
    )
    assert judge_mod.cohen_kappa([], []) == 0.0


def test_judge_agreement_refuses_to_report_below_the_floor() -> None:
    small = judge_mod.judge_agreement(
        [1.0] * 10, [1] * 10, judge_model="judge-x", generator_model="gen-y"
    )
    assert small["status"] == "owner_action_required"
    assert "cohen_kappa" not in small
    assert small["human_labelled_items"] == 10
    # a mixed 50-item sample with 45 agreements: kappa = (0.9-0.5)/0.5 = 0.8
    human = [1] * 25 + [0] * 25
    judge = [1.0] * 22 + [0.0] * 3 + [1.0] * 2 + [0.0] * 23
    big = judge_mod.judge_agreement(judge, human, judge_model="judge-x", generator_model="gen-y")
    assert big["status"] == "measured"
    assert big["raw_agreement"] == 0.9
    assert big["cohen_kappa"] == 0.8
    assert big["passes_floor"] is True
    # both raters constant -> the floor is not evaluable on this sample
    flat = judge_mod.judge_agreement([1.0] * 50, [1] * 50, judge_model="j", generator_model="g")
    assert flat["kappa_degenerate"] is True
    assert flat["passes_floor"] is False
    assert "kappa is" in flat["note"]
    same = judge_mod.judge_agreement(judge, human, judge_model="same", generator_model="same")
    assert same["self_preference_flag"] is True


def test_verbosity_bias_flags_length_association() -> None:
    lengths = [10, 20, 30, 40, 50, 60]
    perfect = judge_mod.verbosity_bias([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], lengths)
    assert perfect["flagged"] is True
    assert "pointwise" in perfect["position_bias"]
    flat = judge_mod.verbosity_bias([0.5] * len(lengths), lengths)
    assert flat["pearson_score_vs_chars"] == 0.0 and flat["flagged"] is False
    with pytest.raises(ValueError, match="paired"):
        judge_mod.verbosity_bias([0.5], [1, 2])


def test_judge_prompt_version_tracks_only_the_prompt_block(tmp_path: Path) -> None:
    path = tmp_path / "prompt.md"
    path.write_text("# header\n\n```text\nscore it\n```\n", encoding="utf-8")
    first = judge_mod.judge_prompt_version(path)
    assert judge_mod.load_judge_prompt(path) == "score it\n"
    path.write_text("# different header\n\n```text\nscore it\n```\n", encoding="utf-8")
    assert judge_mod.judge_prompt_version(path) == first, "documentation is not the prompt"
    path.write_text("# header\n\n```text\nscore it strictly\n```\n", encoding="utf-8")
    assert judge_mod.judge_prompt_version(path) != first
    path.write_text("no fenced block", encoding="utf-8")
    with pytest.raises(ValueError, match="no ```text prompt block"):
        judge_mod.load_judge_prompt(path)


def test_shipped_harness_files_are_honest_about_missing_humans() -> None:
    report = judge_mod.load_judge_harness(API_ROOT)
    assert report["status"] == "owner_action_required"
    assert report["template_items"] == judge_mod.MIN_HUMAN_LABELS
    assert report["human_labelled_items"] == 0
    assert report["verbosity_bias"] is None
    assert report["judge_prompt_version"] == judge_mod.judge_prompt_version(
        judge_mod.judge_prompt_path(API_ROOT)
    )


def test_judge_sample_is_deterministic_and_stratum_covering() -> None:
    items = json.loads(GOLDEN.read_text(encoding="utf-8"))["items"]
    first = judge_mod.build_judge_sample(items, 50)
    second = judge_mod.build_judge_sample(items, 50)
    assert first == second
    assert len(first["items"]) == 50
    groups = {(row["class_level"], row["subject"]) for row in first["items"]}
    assert len(groups) >= 8, "a 50-item sample must not be one class-subject pair"
    assert all(row["judge_score"] is None and row["human_label"] is None for row in first["items"])
    assert all(row["class_level"] in {6, 7, 8, 9, 10} for row in first["items"])


async def test_end_to_end_metrics_on_real_tutor_answers() -> None:
    from bangla_gpt_api.config import Settings

    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    tutor = TutorService(index=index, provider=MockLLMProvider(), fast_provider=None)
    items = json.loads(GOLDEN.read_text(encoding="utf-8"))["items"]
    answerable = [item for item in items if item["expect"] == "answer"][:5]
    negatives = [item for item in items if item["expect"] == "refuse"][:5]
    report = await gen.run_generation_report(tutor, answerable + negatives, unsafe_items=[])
    assert report["items"] == 10
    assert report["citation_recall"] == 1.0, "the mock quotes its retrieved evidence"
    assert report["abstention_recall"] == 1.0
    assert report["false_refusal_rate"] == 0.0
    assert report["response_language_correctness"] == 1.0
    assert report["format_validity"] == 1.0
    assert report["unsafe_items"] == 0
