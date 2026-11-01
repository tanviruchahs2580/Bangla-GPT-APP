"""F-048 / RAG-20 and F-050+F-059 / RAG-23: the runnable evaluation gates.

F-048: family-B MRR in scripts/evaluate_nctb_retrieval.py reciprocated a value
that the ``mrr`` helper reciprocates again (measured 1.275, impossible for a
mean reciprocal rank). The script now feeds ranks and asserts every reported
metric is a fraction before writing the artifact.

F-050/F-059: CI must be able to call one command that gates (a) the golden set
with a retrieval hit@k floor and (b) the red-team suite, exiting non-zero on
failure. ``evaluation.cli --gate`` is that command; this file pins its exit
codes and the hit@k metric itself.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation import cli as eval_cli
from bangla_gpt_api.evaluation.metrics import retrieval_hit_at_k
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

API_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = API_ROOT / "scripts" / "evaluate_nctb_retrieval.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evaluate_nctb_retrieval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mrr_reciprocates_the_rank_once() -> None:
    module = _load_script()
    # ranks (1-based; 0 = not retrieved)
    assert module.mrr([1, 1, 1]) == 1.0
    assert module.mrr([1, 2, 4]) == round((1 + 0.5 + 0.25) / 3, 4)
    assert module.mrr([0, 0]) == 0.0
    assert module.mrr([]) == 0.0
    for ranks in ([1, 2, 3], [2, 2, 2], [5, 1, 0]):
        assert 0.0 <= module.mrr(ranks) <= 1.0


def _write_synthetic_corpus(target: Path) -> None:
    pages = [
        PageText(1, "অধ্যায়: বল ও গতি", "bijoy-converted"),
        PageText(2, "নিউটনের প্রথম সূত্র অনুযায়ী গতির অবস্থা পরিবর্তনে বাহ্যিক বল প্রয়োজন। " * 12),
    ]
    chunks = chunk_pages(pages, source_id="synthetic-nctb")
    normalized = target / "normalized"
    normalized.mkdir(parents=True)
    with (normalized / "synthetic-nctb.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    (target / "quality_report.json").write_text(
        json.dumps(
            {
                "synthetic-nctb": {
                    "level": "secondary",
                    "subject_bn": "পদার্থবিদ্যা",
                    "curriculum_year": "2012",
                    "bangla_char_ratio_on_usable": 0.9,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_family_b_mrr_is_a_fraction_in_the_written_report(tmp_path, monkeypatch) -> None:
    corpus = tmp_path / "nctb"
    _write_synthetic_corpus(corpus)
    module = _load_script()
    monkeypatch.setattr(sys, "argv", ["evaluate_nctb_retrieval.py", str(corpus)])

    assert module.main() == 0

    report = json.loads((corpus / "retrieval_eval.json").read_text(encoding="utf-8"))
    for family in ("family_A_self_sentence", "family_B_chapter_title"):
        metrics = report[family]
        assert 0.0 <= metrics["mrr"] <= 1.0, (family, metrics["mrr"])
        assert 0.0 <= metrics["recall_at_1"] <= 1.0
        assert 0.0 <= metrics["recall_at_5"] <= 1.0
    assert 0.0 <= report["family_C_adversarial_refusal_rate"] <= 1.0


# --- F-050/F-059: the one-command gate --------------------------------------


def test_hit_at_k_metric_counts_chapter_hits() -> None:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    items = [
        {
            "question": "ভগ্নাংশ কী?",
            "class_level": 6,
            "subject": "mathematics",
            "expect": "answer",
            "chapter": "ভগ্নাংশ",
        },
        {
            "question": "কোষ কী?",
            "class_level": 6,
            "subject": "science",
            "expect": "answer",
            "chapter": "নেই এমন অধ্যায়ের নাম",
        },
        {
            "question": "মঙ্গল গ্রহে প্রাণ আছে?",
            "class_level": 6,
            "subject": "science",
            "expect": "refuse",
            "chapter": None,
        },
    ]
    result = retrieval_hit_at_k(index, items, k=3)
    assert result["n"] == 2  # refusal items have no chapter to hit
    assert result["hit"] == 1
    assert result["hit_rate"] == 0.5
    assert [m["chapter"] for m in result["misses"]] == ["নেই এমন অধ্যায়ের নাম"]


def test_real_golden_hit_floor_is_met_on_this_tree() -> None:
    """The new hit@k floor is met with margin on the committed golden set."""
    settings = Settings(env="test", llm_provider="mock")
    items = eval_cli._load_golden_items(API_ROOT / "eval" / "golden_v2.json", seed_bad=0)
    assert eval_cli._hit_gate(settings, items, eval_cli.DEFAULT_HIT_FLOOR) is True


def _tiny_golden(tmp_path: Path) -> Path:
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "question": "ভগ্নাংশ কী?",
                        "class_level": 6,
                        "subject": "mathematics",
                        "expect": "answer",
                        "chapter": "ভগ্নাংশ",
                        "section": None,
                    },
                    {
                        "question": "কোষ কী?",
                        "class_level": 6,
                        "subject": "science",
                        "expect": "answer",
                        "chapter": "কোষ",
                        "section": None,
                    },
                    {
                        "question": "মঙ্গল গ্রহে প্রাণ আছে?",
                        "class_level": 6,
                        "subject": "science",
                        "expect": "refuse",
                        "chapter": None,
                        "section": None,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_gate_command_runs_every_gate(tmp_path, capsys) -> None:
    """`evaluation.cli --gate`: golden + hit@k + red-team, hermetically."""
    settings = Settings(env="test", llm_provider="mock")
    code = eval_cli._run_all_gates(
        settings,
        _tiny_golden(tmp_path),
        tmp_path / "no-baseline.json",  # report-only golden leg
        hit_floor=0.95,
    )
    out = capsys.readouterr().out
    assert "RETRIEVAL hit@3" in out
    assert "REDTEAM: PASS" in out
    assert "ALL GATES: PASS" in out
    assert code == 0


def test_gate_command_fails_when_the_hit_floor_is_unreachable(tmp_path, capsys) -> None:
    settings = Settings(env="test", llm_provider="mock")
    code = eval_cli._run_all_gates(
        settings,
        _tiny_golden(tmp_path),
        tmp_path / "no-baseline.json",
        hit_floor=1.01,  # impossible floor: the gate must fail, not clamp
    )
    out = capsys.readouterr().out
    assert "ALL GATES: FAIL" in out
    assert code == 1


def test_redteam_mode_is_reachable_as_its_own_command() -> None:
    """F-059: the red-team suite stays callable on its own (CI step form)."""
    settings = Settings(env="test", llm_provider="mock")
    import asyncio

    assert asyncio.run(eval_cli._redteam(settings)) == 0
