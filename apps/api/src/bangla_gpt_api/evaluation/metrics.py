"""S4.7 Evaluation v2 -- metric layer for the golden-set CI regression gate.

Four spec metrics, all deterministic under the mock provider so the gate is
reproducible without any external model (R8: a real LLM-judge run is a human
input once a provider is configured -- see :func:`faithfulness`):

* :func:`grammar_score` -- heuristic 0..1 for "clean Bengali prose": every
  sentence must carry Bengali letters and no Latin characters, and the answer
  must close with the Bengali full stop (danda). The heuristic definition is
  pinned by unit tests (R12: never silently lowered).
* :func:`faithfulness` -- with a configured provider the judge is an LLM
  asked to grade whether every answer claim is supported by the given
  evidence; without one it returns the deterministic evidence-overlap
  fraction and reports mode="local_overlap" so no run can fake an LLM score.
* :func:`compare_gate` -- CI rule (spec: "fails build on >2% regression"):
  any metric that dropped by more than GATE_PP absolute percentage points
  against the recorded baseline FAILS, with per-metric detail.
* :func:`run_suite` -- executes the golden set through a TutorService and
  aggregates all four metrics plus refusal precision/recall.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

GATE_PP = 2.0  # percentage points; spec: fail the build on >2% regression

_BENGALI_RE = re.compile(r"[\u0980-\u09ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DANDA = "।"  # danda -- the Bengali full stop
_SENTENCE_SPLIT = re.compile(r"[।\n]+")
# Mock/answer-structure scaffolding (providers/mock.py layout): the "[mock]"
# marker, "- " bullets and Bengali section labels ("সহজ ব্যাখ্যা:"-style).
# These are formatting, not content -- stripped before overlap/grammar scoring
# so the metric measures the answer text, not the template around it.
_MOCK_MARK_RE = re.compile(r"^\s*\[mock\]\s*")
_BULLET_RE = re.compile(r"^\s*[-•*]\s*")
_LABEL_RE = re.compile(r"^[ঃ।\u0980-\u09ff\s]*?:\s*")

_JUDGE_INSTRUCTION = (
    "You are a strict faithfulness judge for a Bangla tutoring system. "
    "Question, evidence excerpts from the approved textbook, and a candidate "
    "answer follow. Answer with a single number between 0 and 1: how much of "
    "the answer is supported by the evidence (1 = fully supported, "
    "0 = unsupported). No other text.\n\n"
)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def normalize_sentence(sentence: str) -> str:
    """Strip answer scaffolding (mock marker, bullet, section label)."""
    s = _MOCK_MARK_RE.sub("", sentence)
    s = _BULLET_RE.sub("", s)
    s = _LABEL_RE.sub("", s)
    return s.strip()


def _squash(text: str) -> str:
    """Whitespace-free form for tolerant sentence-in-evidence matching."""
    return re.sub(r"\s+", "", text)


def grammar_score(text: str) -> float:
    """Heuristic Bangla grammar/shape score in [0, 1] (see module docstring)."""
    sentences = [normalize_sentence(s) for s in split_sentences(text)]
    sentences = [s for s in sentences if s]
    if not sentences:
        return 0.0
    good = sum(1 for s in sentences if _BENGALI_RE.search(s) and not _LATIN_RE.search(s))
    score = good / len(sentences)
    # A danda- or question-mark closure is legitimate Bengali punctuation.
    if not text.rstrip().endswith((_DANDA, "?", "？")):
        score -= 1.0 / (len(sentences) + 1)
    return round(max(0.0, min(1.0, score)), 4)


def _overlap_fraction(answer: str, evidence: list[str]) -> float:
    """Fraction of answer sentences that appear in the evidence (deterministic)."""
    ev_text = _squash(" ".join(evidence))
    sentences = [normalize_sentence(s).strip(_DANDA + " ") for s in split_sentences(answer)]
    sentences = [s for s in sentences if s]
    if not sentences:
        return 0.0
    hits = sum(1 for s in sentences if _squash(s) in ev_text)
    return round(hits / len(sentences), 4)


async def faithfulness(answer: str, question: str, evidence: list[str], provider: Any) -> dict:
    """LLM-judge faithfulness, or the honest deterministic fallback (no provider)."""
    if provider is None:
        return {
            "mode": "local_overlap",
            "score": _overlap_fraction(answer, evidence),
        }
    joined = "\n".join(evidence)[:6000]
    prompt = (
        f"{_JUDGE_INSTRUCTION}QUESTION: {question}\nEVIDENCE:\n{joined}\nANSWER: {answer}\n\nScore:"
    )
    raw = await provider.generate(prompt)
    match = re.search(r"0(?:\.\d+)?|1(?:\.0+)?", raw)
    if match is None:  # judge returned junk -> score of record is 0 (never silent)
        return {"mode": "llm_judge", "score": 0.0, "raw": raw[:80]}
    return {"mode": "llm_judge", "score": min(1.0, float(match.group()))}


@dataclass
class SuiteMetrics:
    total: int
    grounded_rate: float  # matched / total (the single gate metric)
    coverage_true: float  # answered when the golden says answerable
    coverage_false: float  # refused when the golden says refuse
    precision_true: float  # refused precision over the refusal set
    faithfulness_avg: float
    faithfulness_mode: str
    grammar_avg: float
    failures: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "grounded_rate": self.grounded_rate,
            "coverage_true": self.coverage_true,
            "coverage_false": self.coverage_false,
            "precision_true": self.precision_true,
            "faithfulness_avg": self.faithfulness_avg,
            "faithfulness_mode": self.faithfulness_mode,
            "grammar_avg": self.grammar_avg,
        }


async def run_suite(tutor: Any, items: list[dict], judge_provider: Any = None) -> SuiteMetrics:
    """Run every golden item through the live tutor and aggregate metrics.

    ``items`` entries: {question, class_level, subject, expect} where expect
    is "answer" (retrieval+evidence expected) or "refuse" (insufficient
    evidence expected). Judge provider defaults to the deterministic overlap
    fallback (mock mode).
    """
    matched = 0
    true_total = answered_true = 0
    false_total = refused_false = 0
    answered_total = 0
    faith_sum = 0.0
    modes: set[str] = set()
    grammar_sum = 0.0
    failures: list[dict] = []
    for item in items:
        resp = await tutor.ask(item["question"], item["class_level"], item.get("subject") or None)
        expect = item["expect"]
        if expect == "answer":
            true_total += 1
            if resp.grounded:
                answered_true += 1
        else:
            false_total += 1
            if not resp.grounded:
                refused_false += 1
        ok = (resp.grounded and expect == "answer") or (not resp.grounded and expect == "refuse")
        if ok:
            matched += 1
        else:
            failures.append(
                {
                    "question": item["question"],
                    "class_level": item["class_level"],
                    "subject": item.get("subject"),
                    "expect": expect,
                    "got_grounded": resp.grounded,
                    "refused_reason": getattr(resp, "refused_reason", None),
                }
            )
        if resp.grounded:
            answered_total += 1
            # sources are SourceRef models (schemas.py, excerpt: str | None);
            # tolerate plain dicts too so test doubles can fake a response.
            evidence = [
                (s.get("excerpt") or "") if isinstance(s, dict) else (s.excerpt or "")
                for s in resp.sources or []
            ]
            faith = await faithfulness(resp.answer, item["question"], evidence, judge_provider)
            faith_sum += faith["score"]
            modes.add(faith["mode"])
            grammar_sum += grammar_score(resp.answer)
    return SuiteMetrics(
        total=len(items),
        grounded_rate=round(matched / len(items), 4) if items else 0.0,
        coverage_true=round(answered_true / true_total, 4) if true_total else 0.0,
        coverage_false=round(refused_false / false_total, 4) if false_total else 0.0,
        precision_true=round(answered_true / answered_total, 4) if answered_total else 0.0,
        faithfulness_avg=round(faith_sum / answered_total, 4) if answered_total else 0.0,
        faithfulness_mode="+".join(sorted(modes)) if modes else "none",
        grammar_avg=round(grammar_sum / answered_total, 4) if answered_total else 0.0,
        failures=failures,
    )


def compare_gate(baseline: dict, current: dict) -> tuple[bool, list[str]]:
    """Spec CI gate: FAIL if any metric regressed by more than GATE_PP points.

    Rates are 0..1 in both files; the threshold is applied on the percentage
    scale (drop > 0.02 absolute fails). Improvements always pass. Returns
    (passed, per-metric lines) so the CI log names the culprit.
    """
    lines: list[str] = []
    passed = True
    for key in (
        "grounded_rate",
        "coverage_true",
        "coverage_false",
        "precision_true",
        "faithfulness_avg",
        "grammar_avg",
    ):
        base, cur = float(baseline[key]), float(current[key])
        drop_pp = round((base - cur) * 100.0, 4)
        ok = drop_pp <= GATE_PP + 1e-9
        if not ok:
            passed = False
        lines.append(
            f"{key}: baseline={base:.4f} current={cur:.4f} drop={drop_pp:+.2f}pp "
            + ("PASS" if ok else f"FAIL(>{GATE_PP:.0f}pp)")
        )
    return passed, lines
