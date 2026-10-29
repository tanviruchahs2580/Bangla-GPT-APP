"""Evaluation v2 -- metric layer for the golden-set CI regression gate.

Four spec metrics, all deterministic under the mock provider so the gate is
reproducible without any external model (a real LLM-judge run is a human
input once a provider is configured -- see:func:`faithfulness`):

*:func:`grammar_score` -- heuristic 0..1 for "clean Bengali prose": each
  sentence contributes its share of Bengali letters (Latin loanwords cost
  proportionally instead of zeroing the sentence), and the answer must
  close with the Bengali full stop (danda). The heuristic definition is
  pinned by unit tests (never silently lowered).
*:func:`faithfulness` -- with a configured provider the judge is an LLM
  asked to grade whether every answer claim is supported by the given
  evidence; without one it returns the deterministic evidence-overlap
  fraction and reports mode="local_overlap" so no run can fake an LLM score.
*:func:`compare_gate` -- CI rule (spec: "fails build on >2% regression"):
  any metric that dropped by more than GATE_PP absolute percentage points
  against the recorded baseline FAILS, with per-metric detail.
*:func:`run_suite` -- executes the golden set through a TutorService and
  aggregates all four metrics plus refusal precision/recall.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bangla_gpt_api.evaluation.stats import interval_report, paired_bootstrap

GATE_PP = 2.0  # percentage points; spec: fail the build on >2% regression

#: Bootstrap seed for the paired comparison against the committed baseline.
#: Fixed, not random: a gate that reports different numbers on identical input
#: is not a gate.
COMPARISON_SEED = 20261029

_BENGALI_RE = re.compile(r"[\u0980-\u09ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
#: Assamese letters that share the Bangla block and must never appear in an
#: answer to a Bangla-medium student (RAG-21; the repo's bn_scan gate uses the
#: same two codepoints for tracked text).
_ASSAMESE_RE = re.compile(r"[\u09f0\u09f1]")
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


def _sentence_bengali_share(sentence: str) -> float:
    """Share of Bengali letters among all letters (Latin penalty, A22).

    A single Latin loanword used to zero out an otherwise Bengali sentence;
    the penalty is now proportional to the Latin letter share. A sentence
    with no letters at all contributes 0.
    """
    bengali = len(_BENGALI_RE.findall(sentence))
    latin = len(_LATIN_RE.findall(sentence))
    if latin == 0:
        return 1.0 if bengali > 0 else 0.0
    return bengali / (bengali + latin)


def grammar_score(text: str) -> float:
    """Heuristic Bangla grammar/shape score in [0, 1] (see module docstring)."""
    sentences = [normalize_sentence(s) for s in split_sentences(text)]
    sentences = [s for s in sentences if s]
    if not sentences:
        return 0.0
    score = sum(_sentence_bengali_share(s) for s in sentences) / len(sentences)
    # A danda- or question-mark closure is legitimate Bengali punctuation.
    if not text.rstrip().endswith((_DANDA, "?", "？")):
        score -= 1.0 / (len(sentences) + 1)
    return round(max(0.0, min(1.0, score)), 4)


def bengali_letter_share(text: str) -> float:
    """Bengali share of all Bengali-or-Latin characters in ``text``.

    Script, not language: the Bengali block (letters and digits alike) counts
    on one side and ASCII letters on the other, so a Bangla sentence with
    numbers is still Bangla and a Latin sentence is not. Deterministic,
    mock-capable, pinned by unit tests; 0.0 when the text has neither.
    """
    bengali = len(_BENGALI_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if bengali + latin == 0:
        return 0.0
    return round(bengali / (bengali + latin), 4)


def assamese_letters(text: str) -> int:
    """Count of U+09F0/U+09F1 in ``text`` (must be 0 in served answers)."""
    return len(_ASSAMESE_RE.findall(text))


def language_verdict(question: str, answer: str, *, min_share: float = 0.5) -> dict:
    """Deterministic language-integrity verdict for one answer (RAG-21).

    ``consistent`` is False when a Bangla-script question (share >= 0.5) is
    answered with a mostly non-Bangla reply, and ``assamese`` counts letters
    that the repo's own unicode gate forbids in shipped text. Both legs run
    under the mock provider; the register/fluency legs stay a human/model
    judgement and are reported as UNVERIFIED-LIVE by the CLI.
    """
    question_share = bengali_letter_share(question)
    answer_share = bengali_letter_share(answer)
    bengali_question = question_share >= min_share
    return {
        "bengali_question": bengali_question,
        "answer_bengali_share": answer_share,
        "consistent": (not bengali_question) or answer_share >= min_share,
        "assamese": assamese_letters(answer),
    }


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
    # Anchor to the reply tail: a mid-sentence "1" (e.g. "10 of 12 claims
    # unsupported ... 0.17") must not score as a perfect 1.0.
    match = re.search(r"(0(?:\.\d+)?|1(?:\.0+)?)\s*(?:/\s*1\.0)?\s*$", raw)
    if match is None:  # judge returned junk -> score of record is 0 (never silent)
        return {"mode": "llm_judge", "score": 0.0, "raw": raw[:80]}
    return {"mode": "llm_judge", "score": min(1.0, float(match.group(1)))}


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
    #: 0/1 per item, in run order: the paired-bootstrap input. Equal to
    #: ``grounded_rate * total`` but per item, which is what pairing needs.
    item_scores: list[int] = field(default_factory=list)
    #: Raw counts behind the four proportions (Wilson intervals need k and n).
    counts: dict[str, int] = field(default_factory=dict)
    #: Per-stratum match counts keyed by the item's own labels
    #: (split, question_type, query_form, negative_kind, class_subject).
    strata: dict[str, dict] = field(default_factory=dict)
    #: RAG-21 deterministic language-integrity legs: rate of consistent
    #: answers to Bangla questions and the count of Assamese letters seen.
    language_consistency: float = 1.0
    assamese_letter_violations: int = 0
    language_violations: list[dict] = field(default_factory=list)

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
            "language_consistency": self.language_consistency,
            "assamese_letter_violations": self.assamese_letter_violations,
        }

    def intervals(self) -> dict[str, dict]:
        """Wilson 95% intervals for every proportion the report prints."""
        counts = self.counts
        return {
            "grounded_rate": interval_report(counts.get("matched", 0), counts.get("total", 0)),
            "coverage_true": interval_report(
                counts.get("answered_true", 0), counts.get("true_total", 0)
            ),
            "coverage_false": interval_report(
                counts.get("refused_false", 0), counts.get("false_total", 0)
            ),
            "precision_true": interval_report(
                counts.get("answered_true", 0), counts.get("answered_total", 0)
            ),
        }


#: Item labels the suite stratifies by, when the golden items carry them.
STRATA_FIELDS = ("split", "question_type", "query_form", "negative_kind")


async def run_suite(
    tutor: Any,
    items: list[dict],
    judge_provider: Any = None,
    responses: list[tuple[dict, Any]] | None = None,
) -> SuiteMetrics:
    """Run every golden item through the live tutor and aggregate metrics.

    ``items`` entries: {question, class_level, subject, expect} where expect
    is "answer" (retrieval+evidence expected) or "refuse" (insufficient
    evidence expected). Judge provider defaults to the deterministic overlap
    fallback (mock mode). When ``responses`` is a list, the per-item
    ``(item, response)`` pairs are appended so callers (e.g. the redteam
    leak scan) can reuse the answers instead of re-asking the suite (A18).
    """
    matched = 0
    true_total = answered_true = 0
    false_total = refused_false = 0
    answered_total = 0
    faith_sum = 0.0
    modes: set[str] = set()
    grammar_sum = 0.0
    failures: list[dict] = []
    item_scores: list[int] = []
    strata: dict[str, dict[str, dict[str, int]]] = {field_name: {} for field_name in STRATA_FIELDS}
    strata.setdefault("class_subject", {})
    language_violations: list[dict] = []
    language_judged = language_consistent = 0
    assamese_violations = 0
    for item in items:
        resp = await tutor.ask(item["question"], item["class_level"], item.get("subject") or None)
        if responses is not None:
            responses.append((item, resp))
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
        item_scores.append(1 if ok else 0)
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
        labels = {
            **{field_name: item.get(field_name) for field_name in STRATA_FIELDS},
            "class_subject": f"{item['class_level']}:{item.get('subject') or '-'}",
        }
        for field_name, value in labels.items():
            if value is None:
                continue
            bucket = strata[field_name].setdefault(str(value), {"n": 0, "matched": 0})
            bucket["n"] += 1
            bucket["matched"] += 1 if ok else 0
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
        verdict = language_verdict(item["question"], resp.answer)
        if verdict["bengali_question"]:
            language_judged += 1
            language_consistent += 1 if verdict["consistent"] else 0
            if not verdict["consistent"]:
                language_violations.append(
                    {
                        "question": item["question"],
                        "rule": "language_consistency",
                        "answer_bengali_share": verdict["answer_bengali_share"],
                    }
                )
        if verdict["assamese"]:
            assamese_violations += verdict["assamese"]
            language_violations.append(
                {
                    "question": item["question"],
                    "rule": "assamese_letters",
                    "count": verdict["assamese"],
                }
            )
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
        item_scores=item_scores,
        counts={
            "total": len(items),
            "matched": matched,
            "true_total": true_total,
            "answered_true": answered_true,
            "false_total": false_total,
            "refused_false": refused_false,
            "answered_total": answered_total,
        },
        strata=strata,
        language_consistency=(
            round(language_consistent / language_judged, 4) if language_judged else 1.0
        ),
        assamese_letter_violations=assamese_violations,
        language_violations=language_violations,
    )


def retrieval_hit_at_k(
    index: Any,
    items: list[dict],
    *,
    k: int = 3,
    chapter_key: str = "chapter",
) -> dict:
    """Retrieval hit@k against each item's expected chapter (F-050/RAG-23).

    The golden items that expect an answer carry the chapter their evidence
    lives in; ``hit@k`` asks whether the served index returned a chunk of that
    chapter inside the top ``k``. Refusal-expectation items are excluded: they
    have no chapter to hit by construction (their absence is what family C /
    the red-team set measure). Deterministic and model-free — it measures the
    retrieval lane CI gates, not generation.
    """
    looked_up = [item for item in items if item.get("expect") == "answer" and item.get(chapter_key)]
    missed: list[dict] = []
    for item in looked_up:
        hits = index.search(
            item["question"],
            class_level=item["class_level"],
            subject=item.get("subject") or None,
            top_k=k,
        )
        wanted = str(item[chapter_key]).strip()
        if not any(str(hit.chunk.meta.chapter).strip() == wanted for hit in hits):
            missed.append({"question": item["question"], "chapter": wanted})
    total = len(looked_up)
    hit = total - len(missed)
    return {
        "k": k,
        "n": total,
        "hit": hit,
        "hit_rate": round(hit / total, 4) if total else 0.0,
        "misses": missed,
    }


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


def compare_gate_with_intervals(
    baseline: dict,
    current: SuiteMetrics,
    *,
    baseline_scores: list[int] | None = None,
    seed: int = COMPARISON_SEED,
) -> tuple[bool, list[str]]:
    """``compare_gate`` plus Wilson intervals and a paired bootstrap.

    The pass/fail rule is unchanged (the spec's fixed 2pp threshold); what is
    added is the evidence needed to read the numbers: n, a Wilson 95% interval
    per proportion, and -- when the baseline carries per-item scores -- a
    paired bootstrap of the difference. A delta whose interval covers zero
    prints as "no measurable difference" so a claim of improvement cannot be
    read into noise.
    """
    passed, lines = compare_gate(baseline, current.as_dict())
    intervals = current.intervals()
    for key, interval in intervals.items():
        lines.append(
            f"{key}: n={interval['n']} rate={interval['rate']:.4f} "
            f"wilson95=[{interval['ci95_low']:.4f}, {interval['ci95_high']:.4f}]"
        )
    if baseline_scores is not None and len(baseline_scores) == len(current.item_scores):
        bootstrap = paired_bootstrap(baseline_scores, current.item_scores, seed=seed)
        if bootstrap["significant"]:
            verdict = "measurable difference"
        else:
            verdict = "no measurable difference"
        lines.append(
            f"grounded_rate paired bootstrap (seed={seed}, n={bootstrap['n']}): "
            f"delta={bootstrap['mean_diff']:+.4f} "
            f"95% CI [{bootstrap['ci_low']:+.4f}, {bootstrap['ci_high']:+.4f}] -> {verdict}"
        )
    elif baseline_scores is not None:
        lines.append(
            "grounded_rate paired bootstrap: skipped (baseline has "
            f"{len(baseline_scores)} item scores, current run {len(current.item_scores)})"
        )
    return passed, lines
