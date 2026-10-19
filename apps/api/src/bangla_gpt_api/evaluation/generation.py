"""A8-04: generation-quality metric definitions and the judge-agreement harness.

The audit's A8-04 status was FAIL because the evaluation computed only
grounded-rate style aggregates: no citation precision/recall, no abstention
precision/recall, no response-language or format checks, and an unused LLM
judge with no versioning, no agreement study and no bias checks. This module
is the missing *definition* layer; :mod:`bangla_gpt_api.evaluation.cli` runs it
over the golden set (``--generation-report``).

Metric definitions (each pinned by a test on hand-built responses):

* ``citation_precision`` -- micro-averaged over sources the server attached to
  an answer: the share whose (chapter, section) equals the item's gold
  section. Sources are attached from the retrieved set, so this measures
  whether retrieval *selected* the right passage. ``citation_precision_chapter``
  is the same count at chapter granularity: a source from the right chapter
  but a neighbouring section is imprecise, not wrong, and both numbers are
  reported so neither reading is hidden.
* ``citation_recall`` -- macro-averaged over answered answerable items: the
  share that cite at least one gold source.
* ``abstention_precision`` -- of the refusals the system produced, the share
  on items that are genuinely unanswerable (the golden negatives: real-world,
  English, gibberish and personal-data questions whose key tokens are absent
  from the corpus).
* ``abstention_recall`` -- of the unanswerable items, the share refused.
* ``false_refusal_rate`` -- of the answerable items, the share refused (the
  cost side of abstention; the spec's ceiling is 5%).
* ``refusal_correctness_unsafe`` -- on the red-team set, the share refused.
* ``response_language_correctness`` -- the share of grounded answers that are
  Bangla-dominant (>= 50% of their letters Bengali) and free of mis-script
  characters (U+09F0/U+09F1, the Assamese ra/wa the corpus scanner removes).
* ``format_validity`` -- the share of grounded answers carrying the four
  section labels SYSTEM_PROMPT rule 6 requires *and* at least one source.

Judge usage is deliberately gated:

* the judge prompt lives in ``eval/judge_prompt_v1.md`` and its version is the
  digest of that file, so an edit cannot leave a stale version in a report;
* :func:`judge_agreement` reports raw agreement and Cohen's kappa against the
  owner's labels in ``eval/judge_agreement_sample.json`` and refuses to report
  a number below :data:`MIN_HUMAN_LABELS` labelled items;
* :func:`verbosity_bias` reports the judge-score/answer-length association and
  self-preference is flagged when judge and generator are the same model.

No humans exist in this environment: the sample ships with null labels and the
harness returns ``owner_action_required`` until the owner fills it -- that is
the honest state, not a placeholder score.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bangla_gpt_api.services.answer_structure import (
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
)

#: Minimum labelled items before an agreement number may be reported (spec:
#: "at least 50 human-labelled items").
MIN_HUMAN_LABELS = 50

#: Judge-human agreement floor for using the judge as a metric of record.
#: Kappa is chance-corrected; 0.4 is the bottom of the "moderate" band
#: (Landis & Koch), the lowest band a metric of record should sit in.
MIN_KAPPA = 0.4

#: Share of Bengali letters above which an answer counts as Bangla-dominant.
LANGUAGE_BANGLA_SHARE = 0.5

_REQUIRED_LABELS = (SECTION_SIMPLE, SECTION_EXAMPLE, SECTION_POINTS, SECTION_CHECK)

#: Assamese ra/wa -- never legitimate in the standard Bengali this product
#: teaches (the corpus scanner treats them as errors too).
_MIS_SCRIPT_CHARS = "\u09f0\u09f1"

_BENGALI_RE = re.compile(r"[\u0980-\u09ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def bangla_letter_share(text: str) -> float:
    """Share of Bengali letters among all letters in the text (0.0 = no letters)."""
    bengali = len(_BENGALI_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if bengali + latin == 0:
        return 0.0
    return bengali / (bengali + latin)


def has_mis_script(text: str) -> bool:
    """True when the text contains Assamese ra/wa (mis-script residue)."""
    return any(char in text for char in _MIS_SCRIPT_CHARS)


def language_ok(text: str) -> bool:
    """Bangla-dominant and free of mis-script characters."""
    return bangla_letter_share(text) >= LANGUAGE_BANGLA_SHARE and not has_mis_script(text)


def format_ok(answer: str, *, source_count: int) -> bool:
    """The four required section labels plus at least one attached source."""
    return all(label in answer for label in _REQUIRED_LABELS) and source_count >= 1


def _normalize(value: str | None) -> str:
    return " ".join((value or "").split())


def source_matches_gold(source: Any, *, chapter: str | None, section: str | None) -> bool:
    """A source matches the item's gold section when chapter and section agree.

    Whitespace-normalized identity on the pipeline's own corpus metadata (the
    golden items recorded the corpus' own strings): not a fuzzy match that
    could be tuned until the number looks right.
    """
    src_chapter = _normalize(getattr(source, "chapter", None))
    src_section = _normalize(getattr(source, "section", None))
    want_chapter = _normalize(chapter)
    want_section = _normalize(section)
    if want_section:
        return src_section == want_section
    return bool(want_chapter) and src_chapter == want_chapter


def source_matches_chapter(source: Any, *, chapter: str | None) -> bool:
    """Loose relevance: the source sits in the item's gold chapter."""
    want_chapter = _normalize(chapter)
    return bool(want_chapter) and _normalize(getattr(source, "chapter", None)) == want_chapter


def generation_metrics(
    rows: list[dict],
    *,
    refusal_correct_unsafe: int = 0,
    unsafe_total: int = 0,
) -> dict[str, Any]:
    """Aggregate the per-item rows :func:`run_generation_report` builds.

    Each row: ``{"expect", "grounded", "sources", "gold_chapter",
    "gold_section", "answer"}`` where ``sources`` is the list of SourceRef
    objects actually returned by the tutor.
    """
    cited_total = cited_gold = cited_chapter = 0
    answerable = answered_answerable = cited_answerable = 0
    unanswerable = refused_unanswerable = refusals_total = 0
    language_ok_count = format_ok_count = grounded_items = 0
    for row in rows:
        expect = row["expect"]
        grounded = bool(row["grounded"])
        if expect == "answer":
            answerable += 1
            if grounded:
                answered_answerable += 1
        else:
            unanswerable += 1
        if not grounded:
            refusals_total += 1
            refused_unanswerable += int(expect == "refuse")
            continue
        sources = list(row.get("sources") or [])
        cited_total += len(sources)
        matched = [
            source
            for source in sources
            if source_matches_gold(
                source, chapter=row.get("gold_chapter"), section=row.get("gold_section")
            )
        ]
        cited_gold += len(matched)
        cited_chapter += sum(
            1
            for source in sources
            if source_matches_chapter(source, chapter=row.get("gold_chapter"))
        )
        cited_answerable += int(expect == "answer" and bool(matched))
        grounded_items += 1
        answer = str(row.get("answer") or "")
        language_ok_count += int(language_ok(answer))
        format_ok_count += int(format_ok(answer, source_count=len(sources)))

    def rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    return {
        "items": len(rows),
        "citation_precision": rate(cited_gold, cited_total),
        "citation_precision_chapter": rate(cited_chapter, cited_total),
        "citation_recall": rate(cited_answerable, answered_answerable),
        "citations_total": cited_total,
        "abstention_precision": rate(refused_unanswerable, refusals_total),
        "abstention_recall": rate(refused_unanswerable, unanswerable),
        "false_refusal_rate": rate(answerable - answered_answerable, answerable),
        "refusal_correctness_unsafe": rate(refusal_correct_unsafe, unsafe_total),
        "response_language_correctness": rate(language_ok_count, grounded_items),
        "format_validity": rate(format_ok_count, grounded_items),
        "grounded_items": grounded_items,
        "refusals_total": refusals_total,
    }


async def run_generation_report(
    tutor: Any,
    items: list[dict],
    *,
    unsafe_items: list[dict] | None = None,
) -> dict[str, Any]:
    """Run every item through the tutor and aggregate the A8-04 metrics.

    ``unsafe_items`` (the red-team set) are run first and scored for refusal
    correctness only; they are never mixed into the golden-set counts.
    """
    rows: list[dict] = []
    for item in items:
        if item["expect"] == "refuse":
            row = {
                "expect": "refuse",
                "grounded": False,
                "sources": [],
                "gold_chapter": None,
                "gold_section": None,
                "answer": "",
            }
        else:
            row = {
                "expect": "answer",
                "grounded": False,
                "sources": [],
                "gold_chapter": item.get("chapter"),
                "gold_section": item.get("section"),
                "answer": "",
            }
        response = await tutor.ask(
            item["question"], item["class_level"], item.get("subject") or None
        )
        row["grounded"] = bool(getattr(response, "grounded", False))
        row["sources"] = list(getattr(response, "sources", None) or [])
        row["answer"] = str(getattr(response, "answer", "") or "")
        rows.append(row)
    refused_unsafe = 0
    unsafe_total = 0
    for item in unsafe_items or []:
        unsafe_total += 1
        response = await tutor.ask(
            item["question"], item["class_level"], item.get("subject") or None
        )
        refused_unsafe += int(not bool(getattr(response, "grounded", False)))
    report = generation_metrics(
        rows, refusal_correct_unsafe=refused_unsafe, unsafe_total=unsafe_total
    )
    report["unsafe_items"] = unsafe_total
    return report


def judge_prompt_path(api_root: Path) -> Path:
    return api_root / "eval" / "judge_prompt_v1.md"


#: The one fenced block in the prompt file is the prompt; the header and the
#: changelog around it are documentation, not part of the version.
_PROMPT_BLOCK_RE = re.compile(r"```text\n(.*?)```", re.DOTALL)


def load_judge_prompt(path: Path) -> str:
    """The exact prompt text from its versioned file (fails loudly if absent)."""
    text = path.read_text(encoding="utf-8")
    match = _PROMPT_BLOCK_RE.search(text)
    if match is None:
        raise ValueError(f"no ```text prompt block in {path.name}")
    return match.group(1)


def judge_prompt_version(path: Path) -> str:
    """Digest of the prompt *text* -- the version recorded in reports."""
    return "jp-" + hashlib.sha256(load_judge_prompt(path).encode("utf-8")).hexdigest()[:12]


def cohen_kappa(judge: Iterable[int], human: Iterable[int]) -> float:
    """Cohen's kappa for two binary raters over paired labels.

    Returns 0.0 when the expected agreement is 1.0 (both raters constant), so
    a degenerate sample cannot score as "perfect agreement".
    """
    pairs = list(zip(judge, human, strict=True))
    n = len(pairs)
    if n == 0:
        return 0.0
    observed = sum(1 for j, h in pairs if j == h) / n
    judge_yes = sum(1 for j, _h in pairs if j) / n
    human_yes = sum(1 for _j, h in pairs if h) / n
    expected = judge_yes * human_yes + (1 - judge_yes) * (1 - human_yes)
    if expected >= 1.0:
        return 0.0
    return round((observed - expected) / (1 - expected), 4)


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation; 0.0 when either series has no variance."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return round(num / den, 4) if den else 0.0


def verbosity_bias(scores: list[float], answer_chars: list[int]) -> dict[str, Any]:
    """Association between judge score and answer length (length-bias probe).

    Position bias is not measurable here by construction: this is a pointwise
    judge (one answer per prompt), so there is no answer order to swap. That
    statement travels with the number instead of being left implicit.
    """
    if len(scores) != len(answer_chars):
        raise ValueError("scores and answer_chars must be paired")
    correlation = pearson([float(count) for count in answer_chars], scores)
    return {
        "n": len(scores),
        "pearson_score_vs_chars": correlation,
        "position_bias": "not_applicable (pointwise judge: one answer per prompt)",
        "flagged": abs(correlation) >= 0.5,
    }


def judge_agreement(
    judge_scores: list[float],
    human_labels: list[Any],
    *,
    judge_model: str | None,
    generator_model: str | None,
) -> dict[str, Any]:
    """Agreement between the judge and the owner's human labels.

    Reports a number only when >= :data:`MIN_HUMAN_LABELS` paired items carry a
    human label; below that (including the shipped all-null template) the
    status is ``owner_action_required`` and no kappa is reported.
    """
    out: dict[str, Any] = {
        "judge_model": judge_model,
        "generator_model": generator_model,
        "self_preference_flag": bool(
            judge_model and generator_model and judge_model == generator_model
        ),
        "items_with_judge_score": len(judge_scores),
        "human_sample_rows": len(human_labels),
        "min_human_labels": MIN_HUMAN_LABELS,
    }
    if len(judge_scores) != len(human_labels):
        out["status"] = "input_error"
        out["note"] = "judge scores and human labels must be paired 1:1"
        return out
    pairs = [
        (1 if score >= 0.5 else 0, int(label))
        for score, label in zip(judge_scores, human_labels, strict=True)
        if label is not None
    ]
    out["human_labelled_items"] = len(pairs)
    if len(pairs) < MIN_HUMAN_LABELS:
        out["status"] = "owner_action_required"
        out["note"] = (
            "The human sample (eval/judge_agreement_sample.json) is not filled in: no "
            "agreement number is reported, and the judge must not be used as a metric "
            "of record until it is."
        )
        return out
    judge_binary = [judge for judge, _human in pairs]
    human_binary = [human for _judge, human in pairs]
    raw = sum(1 for j, h in zip(judge_binary, human_binary, strict=True) if j == h) / len(pairs)
    kappa = cohen_kappa(judge_binary, human_binary)
    # Both raters constant: kappa has no chance-corrected variance to divide
    # by, so the floor cannot be evaluated from this sample at all -- extend
    # it with the label class the sample is missing rather than reading the
    # raw agreement as "passed".
    degenerate = len(set(judge_binary)) <= 1 and len(set(human_binary)) <= 1
    out.update(
        {
            "status": "measured",
            "raw_agreement": round(raw, 4),
            "cohen_kappa": kappa,
            "kappa_floor": MIN_KAPPA,
            "kappa_degenerate": degenerate,
            "passes_floor": (not degenerate) and kappa >= MIN_KAPPA,
        }
    )
    if degenerate:
        out["note"] = (
            "every labelled item has the same label for both raters: kappa is "
            "undefined on this sample. Extend it with the missing label class "
            "before reading agreement."
        )
    return out


def build_judge_sample(items: list[dict], limit: int = MIN_HUMAN_LABELS) -> dict[str, Any]:
    """A deterministic, stratum-covering judge-agreement sample template.

    Round-robins over (class_level, subject, stratum) groups so a 50-item
    sample cannot be all class-6 science: the agreement study must be able to
    fail for a class the judge handles badly. The answer side is deliberately
    empty -- the owner runs the live judge over these items and fills
    ``judge_score`` and an independent ``human_label``.
    """
    groups: dict[tuple, list[dict]] = {}
    for position, item in enumerate(items):
        if item["expect"] != "answer":
            continue
        key = (item["class_level"], item["subject"], item["stratum"])
        groups.setdefault(key, []).append({"item_index": position, **item})
    ordered_keys = sorted(groups)
    picked: list[dict] = []
    cursor = 0
    while len(picked) < limit:
        progressed = False
        for key in ordered_keys:
            group = groups[key]
            if cursor < len(group) and len(picked) < limit:
                row = group[cursor]
                picked.append(
                    {
                        "item_index": row["item_index"],
                        "class_level": row["class_level"],
                        "subject": row["subject"],
                        "stratum": row["stratum"],
                        "split": row["split"],
                        "question": row["question"],
                        "judge_score": None,
                        "answer_chars": None,
                        "human_label": None,
                    }
                )
                progressed = True
        if not progressed:
            break
        cursor += 1
    return {
        "purpose": (
            "A8-04 judge-human agreement study. The judge must not be used as a "
            "metric of record until at least 50 rows carry a human label."
        ),
        "sampling_rule": (
            "round-robin over sorted (class_level, subject, stratum) groups of the "
            "golden set's answerable items, in file order (scripts regenerate it "
            "deterministically; see docs/evaluation/judge-agreement.md)"
        ),
        "owner_action": (
            "Run the judge prompt (eval/judge_prompt_v1.md) over each question with "
            "the deployed provider, record judge_score (0..1) and answer_chars, then "
            "label every answer independently as human_label 0 or 1."
        ),
        "judge_model": None,
        "generator_model": None,
        "items": picked,
    }


def load_judge_harness(api_root: Path) -> dict[str, Any]:
    """Read the shipped harness files and report their state without inventing data."""
    prompt_path = judge_prompt_path(api_root)
    sample_path = api_root / "eval" / "judge_agreement_sample.json"
    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    rows = payload["items"]
    scored = [row for row in rows if row.get("judge_score") is not None]
    report = judge_agreement(
        [float(row["judge_score"]) for row in scored],
        [row.get("human_label") for row in scored],
        judge_model=payload.get("judge_model"),
        generator_model=payload.get("generator_model"),
    )
    report["judge_prompt_version"] = judge_prompt_version(prompt_path)
    report["sample_file"] = sample_path.name
    report["template_items"] = len(rows)
    report["verbosity_bias"] = (
        verbosity_bias(
            [float(row["judge_score"]) for row in scored],
            [int(row.get("answer_chars") or 0) for row in scored],
        )
        if scored
        else None
    )
    return report
