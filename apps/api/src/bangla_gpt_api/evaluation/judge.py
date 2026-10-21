"""A8-04: the LLM-judge harness -- prompt versioning, agreement and bias.

Split out of ``evaluation/generation.py`` (C-03): the judge is a separate
concern from the generation metrics, with its own versioning story (the prompt
digest *is* the version) and its own failure mode (a judge nobody labelled).

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

#: A judge agreement number below this many labelled items is not reported.
MIN_HUMAN_LABELS = 50

#: Cohen's kappa floor below which the judge's agreement is not accepted as
#: usable evidence (landis-koch "moderate" starts at 0.41).
MIN_KAPPA = 0.4


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


def _binary_pairs(
    judge_scores: list[float], human_labels: list[Any]
) -> list[tuple[int, int]] | None:
    """(judge_binary, human_binary) pairs over labelled items; None on mismatch."""
    if len(judge_scores) != len(human_labels):
        return None
    return [
        (1 if score >= 0.5 else 0, int(label))
        for score, label in zip(judge_scores, human_labels, strict=True)
        if label is not None
    ]


def _agreement_verdict(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    """Raw agreement and kappa over >= MIN_HUMAN_LABELS paired labels.

    Both raters constant: kappa has no chance-corrected variance to divide by,
    so the floor cannot be evaluated from this sample at all -- the verdict
    says so rather than reading the raw agreement as "passed".
    """
    judge_binary = [judge for judge, _human in pairs]
    human_binary = [human for _judge, human in pairs]
    raw = sum(1 for j, h in zip(judge_binary, human_binary, strict=True) if j == h) / len(pairs)
    kappa = cohen_kappa(judge_binary, human_binary)
    degenerate = len(set(judge_binary)) <= 1 and len(set(human_binary)) <= 1
    verdict: dict[str, Any] = {
        "status": "measured",
        "raw_agreement": round(raw, 4),
        "cohen_kappa": kappa,
        "kappa_floor": MIN_KAPPA,
        "kappa_degenerate": degenerate,
        "passes_floor": (not degenerate) and kappa >= MIN_KAPPA,
    }
    if degenerate:
        verdict["note"] = (
            "every labelled item has the same label for both raters: kappa is "
            "undefined on this sample. Extend it with the missing label class "
            "before reading this sheet as evidence."
        )
    return verdict


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
    pairs = _binary_pairs(judge_scores, human_labels)
    if pairs is None:
        return {
            **out,
            "status": "input_error",
            "note": "judge scores and human labels must be paired 1:1",
        }
    out["human_labelled_items"] = len(pairs)
    if len(pairs) < MIN_HUMAN_LABELS:
        return {
            **out,
            "status": "owner_action_required",
            "note": (
                "The human sample (eval/judge_agreement_sample.json) is not filled in: no "
                "agreement number is reported, and the judge must not be used as a metric "
                "of record until it is."
            ),
        }
    out.update(_agreement_verdict(pairs))
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
