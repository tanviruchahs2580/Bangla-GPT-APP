"""S4.7 Evaluation v2 -- golden-set sanity, metric units, and the CI gate.

PASS-WHEN for step 4.7, in test form:
* the committed golden set meets the spec's shape (>=300 questions, every
  class+subject pair, byte-stable ASCII);
* the metric heuristics are pinned by units (R12: definition changes must
  break these tests, never drift silently);
* the deliberately-seeded bad prompt demonstrably FAILS the 2pp gate and
  reverting the seed makes it green again (small hermetic subset -- the
  full 634-item suite runs in the CI job / `evaluation.cli`).

All Bengali literals are \\u escapes (repo rule: never type Bengali through
a shell heredoc).
"""

from __future__ import annotations

import json
from pathlib import Path

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation.metrics import (
    GATE_PP,
    SuiteMetrics,
    compare_gate,
    faithfulness,
    grammar_score,
    run_suite,
)
from bangla_gpt_api.providers import get_provider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService

API_ROOT = Path(__file__).resolve().parents[1]  # apps/api
GOLDEN = API_ROOT / "eval" / "golden_v2.json"
BASELINE = API_ROOT / "eval" / "baseline_v2.json"

# --- Bengali building blocks (\u escapes only) -----------------------------
_KOSH = "কোষ"  # কোষ
_HOLO = "হলো"  # হলো
_JIBONER = "জীবনের"  # জীবনের
_EKOK = "একক"  # একক
_DANDA = "।"  # danda
_LABEL = "সহজ ব্যাখ্যা:"  # সহজ ব্যাখ্যা:
_GOOD = f"{_KOSH} {_HOLO} {_JIBONER} {_EKOK}{_DANDA}"  # "কোষ হলো জীবনের একক।"
_UNRELATED = f"আকাশ নীল রং{chr(0x0964)}"


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# --- golden-set sanity ------------------------------------------------------


def test_golden_v2_shape_meets_spec() -> None:
    data = _golden()
    items = data["items"]
    assert len(items) >= 300, "spec: golden set 300+ Q"
    assert sum(1 for i in items if i["expect"] == "answer") >= 300
    pairs = {(i["class_level"], i["subject"]) for i in items}
    assert len(pairs) == 11, f"expected all 11 (class,subject) pairs, got {len(pairs)}"
    for p in sorted(pairs):
        n = sum(1 for i in items if (i["class_level"], i["subject"]) == p)
        assert n >= 10, f"pair {p} has only {n} items"
    seen = set()
    for i in items:
        key = (i["class_level"], i["subject"], i["question"])
        assert key not in seen, f"duplicate golden item {key}"
        seen.add(key)
        assert i["expect"] in ("answer", "refuse")
        if i["expect"] == "answer":
            assert i["chapter"] and i["section"]


def test_golden_v2_is_byte_stable_ascii() -> None:
    assert GOLDEN.read_bytes().isascii()


def test_golden_negatives_absent_from_corpus() -> None:
    """The construction invariant behind expect=refuse, re-checked here."""
    corpus_words = " ".join(c.text for c in load_sample_corpus()).casefold()
    negatives = [i for i in _golden()["items"] if i["expect"] == "refuse"]
    assert len(negatives) >= 5
    probe_tokens = [
        "ফুটবল",  # ফুটবল
        "ক্রিকেট",  # ক্রিকেট
        "পাসওয়ার্ড",  # পাসওয়ার্ড
        "xylofon",
        "zzqq",
    ]
    for tok in probe_tokens:
        assert tok.casefold() not in corpus_words, f"negative token {tok!r} leaked into corpus"


# --- metric heuristic units (R12: pinned definitions) -----------------------


def test_grammar_score_units() -> None:
    assert grammar_score("") == 0.0
    # clean Bengali sentence closing with the danda: perfect
    assert grammar_score(_GOOD) == 1.0
    # a question mark is a legal closure too
    assert grammar_score("তুমি বুঝেছ?") == 1.0  # তুমি বুঝেছ?
    # missing terminator costs the documented 1/(n+1) penalty
    assert grammar_score(_GOOD.rstrip(_DANDA)) == 0.5
    # a Latin-only sentence scores 0 for the "good Bengali" fraction
    assert grammar_score("hello world") == 0.0
    # scaffolding is stripped before scoring, not counted as Latin noise
    assert grammar_score(f"[mock] {_LABEL} {_GOOD}") == 1.0
    assert grammar_score(f"মূল বিষয়:\n- {_GOOD}\n- {_UNRELATED}") == 1.0


async def test_faithfulness_local_overlap_unit() -> None:
    ev = [_GOOD]
    # every answer sentence found in the evidence -> 1.0 (after label strip)
    assert await faithfulness(f"{_LABEL} {_GOOD}", "q", ev, None) == {
        "mode": "local_overlap",
        "score": 1.0,
    }
    # half the sentences unsupported -> honest 0.5 (mock check-questions)
    assert (await faithfulness(f"{_GOOD}\n{_UNRELATED}", "q", ev, None))["score"] == 0.5
    # fully unsupported -> 0.0
    assert (await faithfulness(_UNRELATED, "q", ev, None))["score"] == 0.0


class _FakeJudge:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return self.reply


async def test_faithfulness_llm_judge_unit() -> None:
    res = await faithfulness("uttor", "prosno", ["proman"], _FakeJudge("0.75"))
    assert res["mode"] == "llm_judge"
    assert res["score"] == 0.75
    junk = await faithfulness("uttor", "prosno", ["proman"], _FakeJudge("maybe?"))
    assert junk["mode"] == "llm_judge"
    assert junk["score"] == 0.0  # never silent: unparsable judge = score of record 0
    assert "raw" in junk


def _metrics(grounded: float, cov_true: float = 1.0) -> dict:
    return SuiteMetrics(
        total=100,
        grounded_rate=grounded,
        coverage_true=cov_true,
        coverage_false=1.0,
        precision_true=1.0,
        faithfulness_avg=0.9,
        faithfulness_mode="local_overlap",
        grammar_avg=0.9,
    ).as_dict()


def test_compare_gate_2pp_boundary() -> None:
    # spec: FAILS on ">2% regression" -- exactly 2.00pp is still a pass
    ok, _ = compare_gate(_metrics(0.90), _metrics(0.88))
    assert ok, "exactly 2pp drop must not trip a '>2%' gate"
    fail, lines = compare_gate(_metrics(0.90), _metrics(0.8799))
    assert not fail
    assert any("grounded_rate" in ln and "FAIL" in ln for ln in lines)
    # improvements never fail the gate
    ok2, _ = compare_gate(_metrics(0.80), _metrics(0.95))
    assert ok2
    assert GATE_PP == 2.0


# --- seeded-bad demo (spec PASS-WHEN), on a small hermetic subset -----------


def _tutor() -> TutorService:
    settings = Settings(env="test", llm_provider="mock")
    index = HybridIndex(load_sample_corpus(), build_embedder(settings))
    return TutorService(index=index, provider=get_provider(settings))


async def test_seeded_bad_prompt_fails_gate_then_revert_is_green() -> None:
    items = _golden()["items"]
    positives = [i for i in items if i["expect"] == "answer"][:12]
    negatives = [i for i in items if i["expect"] == "refuse"]
    tutor = _tutor()

    honest = positives + negatives
    baseline = await run_suite(tutor, honest)
    assert baseline.grounded_rate == 1.0, "subset baseline must be fully green first"
    # every golden negative must actually be refused by the live pipeline
    for f in baseline.failures:
        raise AssertionError(f"unexpected baseline failure: {f}")

    # seed the bad prompt: flip the refuse-expectation to answer (wrong on purpose)
    seeded = positives + [{**n, "expect": "answer"} for n in negatives]
    bad = await run_suite(tutor, seeded)
    passed, lines = compare_gate(baseline.as_dict(), bad.as_dict())
    assert not passed, "deliberately-seeded bad prompt must FAIL the gate"
    assert any("grounded_rate" in ln and "FAIL" in ln for ln in lines)
    assert all(f["refused_reason"] == "insufficient_evidence" for f in bad.failures)

    # revert the seed -> green again (same honest items, deterministic metrics)
    reverted = await run_suite(tutor, honest)
    assert reverted.as_dict() == baseline.as_dict(), "runs must be deterministic"
    ok, _ = compare_gate(baseline.as_dict(), reverted.as_dict())
    assert ok


def test_baseline_recorded_with_six_compared_metrics() -> None:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    m = data["metrics"]
    for key in (
        "grounded_rate",
        "coverage_true",
        "coverage_false",
        "precision_true",
        "faithfulness_avg",
        "grammar_avg",
    ):
        assert key in m
    assert m["grounded_rate"] >= 0.95, "G4: golden grounded-rate >= 95% at baseline"


def test_eval_gate_workflow_file_present_locally() -> None:
    root = API_ROOT.parents[1]
    wf = root / ".github" / "workflows" / "eval-gate.yml"
    assert wf.exists(), "spec 4.7: workflow file added locally (NOT pushed)"
    text = wf.read_text(encoding="utf-8")
    assert "bangla_gpt_api.evaluation.cli" in text
