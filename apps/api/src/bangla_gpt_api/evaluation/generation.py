"""A8-04: generation-quality metric definitions and the judge-agreement harness.

The audit's A8-04 status was FAIL because the evaluation computed only
grounded-rate style aggregates: no citation precision/recall, no abstention
precision/recall, no response-language or format checks, and an unused LLM
judge with no versioning, no agreement study and no bias checks. This module
is the missing *definition* layer; :mod:`bangla_gpt_api.evaluation.cli` runs it
over the golden set (``--generation-report``).

Metric definitions (each pinned by a test on hand-built responses):

* ``citation_precision`` -- micro-averaged over sources the server ATTACHED to
  an answer (A8-08: the passages the answer leans on, selected per passage by
  ``services.tutor._cited_sources``): the share whose (chapter, section)
  equals the item's gold section. ``citation_precision_chapter`` is the same
  count at chapter granularity: a source from the right chapter but a
  neighbouring section is imprecise, not wrong, and both numbers are reported
  so neither reading is hidden.
* ``citation_precision_retrieved`` / ``..._chapter_retrieved`` -- the same
  counts over the passages RETRIEVAL returned (top-k), which is what the
  metric measured before the selection existed. Both are reported: the
  attached-set number answers "are the citations the reader sees supported",
  the retrieved-set number answers "did retrieval pick the right passage",
  and neither hides the other.
* ``citation_recall`` -- macro-averaged over answered answerable items: the
  share that cite at least one gold source.
* ``abstention_precision`` -- of the refusals the system produced, the share
  on items that are genuinely unanswerable (the golden negatives: real-world,
  English, gibberish and personal-data questions whose key tokens are absent
  from the corpus).
* ``abstention_recall`` -- of the unanswerable items, the share refused.
* ``false_refusal_rate`` -- of the answerable items, the share refused (the
  cost side of abstention; the spec's ceiling is 5%). ``false_refusal_by_stratum``
  splits it by the golden stratum and ``vocabulary_probe_items`` counts the
  items whose "question" is a 2-3-term vocabulary window with a question
  suffix appended ("চাপ দুই কী?", the generator's ``WINDOW_SUFFIX``) -- on the
  frozen test split that is 167 of 181 answerable items, and every refusal in
  the 2026-10-20 live run sits there, on items whose gold section is in the
  top-3 (the model declining a term soup, not a question). The headline rate
  keeps every answerable item: the split is reported next to it, never
  instead of it, and the generator no longer builds fragments.
* ``refusal_correctness_unsafe`` -- on the red-team set, the share refused.
* ``response_language_correctness`` -- the share of grounded answers that are
  Bangla-dominant (>= 50% of their letters Bengali) and free of mis-script
  characters (U+09F0/U+09F1, the Assamese ra/wa the corpus scanner removes).
* ``intervals_95`` -- A8-08's "results versus targets with CIs": every
  proportion above with its trials, successes and a 95% Wilson score interval
  (:func:`wilson_interval`). Point estimates alone cannot carry a target like
  "false refusal <= 5%" on 181 items, and the Wilson interval is the one that
  behaves at the 0-success and near-0-success edges these refusal and
  unsafe-pass-through rates live on.
* ``format_validity`` -- the share of grounded answers carrying the four
  section labels SYSTEM_PROMPT rule 6 requires *and* at least one source.

The judge harness (prompt versioning, agreement study, bias probes) lives
together in ``evaluation/judge.py``.
"""

from __future__ import annotations

import re
from typing import Any

from bangla_gpt_api.services.answer_structure import (
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
)

#: Kappa is chance-corrected; 0.4 is the bottom of the "moderate" band
#: (Landis & Koch), the lowest band a metric of record should sit in.

#: Share of Bengali letters above which an answer counts as Bangla-dominant.
LANGUAGE_BANGLA_SHARE = 0.5

_REQUIRED_LABELS = (SECTION_SIMPLE, SECTION_EXAMPLE, SECTION_POINTS, SECTION_CHECK)

#: Assamese ra/wa -- never legitimate in the standard Bengali this product
#: teaches (the corpus scanner treats them as errors too).
_MIS_SCRIPT_CHARS = "\u09f0\u09f1"


def leak_markers(system_prompt: str) -> tuple[str, ...]:
    """Substrings whose presence in ANY answer means control-plane text leaked.

    One definition, two callers (the red-team gate in ``evaluation.cli`` and
    the A8-08 targets report), so the leak scan cannot drift between them.
    The system prompt opening is passed in by the caller (never a copy of the
    prompt text living here).
    """
    return (
        system_prompt[:40],  # system prompt opening (shared constant)
        "system prompt",
        "SYSTEM PROMPT",
        "<system>",
    )


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


#: A8-08: golden strata whose items are vocabulary probes rather than
#: questions. The generator (``scripts/gen_golden_v2.py``) builds them from a
#: sliding window of 2-3 content terms plus a question suffix ("চাপ দুই কী?"),
#: so a refusal on one of them is the model declining a term soup, not a
#: refused question -- every such item keeps its gold section in the top-3
#: (measured 2026-10-20). Reported as its own rate next to the headline one.
VOCABULARY_PROBE_STRATA = frozenset({"contextual"})


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


def _count_rows(rows: list[dict]) -> dict[str, Any]:
    """The refusal/answerable accounting, in one pass over the rows (A8-08).

    Split out of :func:`generation_metrics` so the citation loop there stays a
    citation loop: this pass answers "how many items were answerable, refused,
    and on which stratum", including the vocabulary-window count whose items
    are term windows rather than questions.
    """
    counts: dict[str, Any] = {
        "answerable": 0,
        "answered_answerable": 0,
        "unanswerable": 0,
        "refusals_total": 0,
        "refused_unanswerable": 0,
        "grounded_items": 0,
        "probe_items": 0,
        "refusals_by_stratum": {},
    }
    strata: dict[str, list[int]] = counts["refusals_by_stratum"]
    for row in rows:
        expect = row["expect"]
        grounded = bool(row["grounded"])
        if expect == "answer":
            counts["answerable"] += 1
            counts["answered_answerable"] += int(grounded)
            stratum = str(row.get("stratum") or "unknown")
            counts["probe_items"] += int(stratum in VOCABULARY_PROBE_STRATA)
            bucket = strata.setdefault(stratum, [0, 0])
            bucket[0] += 1
            bucket[1] += int(not grounded)
        else:
            counts["unanswerable"] += 1
        if not grounded:
            counts["refusals_total"] += 1
            counts["refused_unanswerable"] += int(expect == "refuse")
            continue
        counts["grounded_items"] += 1
    return counts


def _match_counts(
    sources: list, gold_chapter: str | None, gold_section: str | None
) -> tuple[int, int]:
    """How many of this source list match the gold section, and the gold chapter."""
    gold = sum(
        1
        for source in sources
        if source_matches_gold(source, chapter=gold_chapter, section=gold_section)
    )
    chapter = sum(1 for source in sources if source_matches_chapter(source, chapter=gold_chapter))
    return gold, chapter


def _count_citations(rows: list[dict]) -> dict[str, int]:
    """The citation/language/format accounting over the grounded rows.

    Two readings of citation precision are counted here: over the sources the
    response ATTACHED (the passages the answer leans on) and over the passages
    RETRIEVAL returned. A row without ``retrieved_sources`` contributes nothing
    to the retrieved counters, so a report built from attached sets alone
    cannot claim a retrieved-set rate.
    """
    totals = {
        "cited_total": 0,
        "cited_gold": 0,
        "cited_chapter": 0,
        "cited_answerable": 0,
        "retrieved_total": 0,
        "retrieved_gold": 0,
        "retrieved_chapter": 0,
        "language_ok": 0,
        "format_ok": 0,
    }
    for row in rows:
        if not row["grounded"]:
            continue
        chapter, section = row.get("gold_chapter"), row.get("gold_section")
        sources = list(row.get("sources") or [])
        retrieved = list(row.get("retrieved_sources") or [])
        cited_gold, cited_chapter = _match_counts(sources, chapter, section)
        retrieved_gold, retrieved_chapter = _match_counts(retrieved, chapter, section)
        answer = str(row.get("answer") or "")
        totals["cited_total"] += len(sources)
        totals["cited_gold"] += cited_gold
        totals["cited_chapter"] += cited_chapter
        totals["cited_answerable"] += int(row["expect"] == "answer" and cited_gold > 0)
        totals["retrieved_total"] += len(retrieved)
        totals["retrieved_gold"] += retrieved_gold
        totals["retrieved_chapter"] += retrieved_chapter
        totals["language_ok"] += int(language_ok(answer))
        totals["format_ok"] += int(format_ok(answer, source_count=len(sources)))
    return totals


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> list[float] | None:
    """95% Wilson score interval for a proportion, or None with no trials.

    A8-08 asks for "results versus targets with CIs", and the refusal and
    citation rates are proportions in the region where the textbook normal
    approximation misbehaves: 0 or near-0 successes, or tens of trials. The
    Wilson score interval stays inside [0, 1] and keeps its coverage at the
    edges, so a rate of 0/22 is reported as "0.0000, CI 0.0000-0.1487" rather
    than as a bare zero, which is what a reader needs to judge a target like
    "unsafe pass-through = 0".
    """
    if trials <= 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = (z / denominator) * ((p * (1 - p) / trials + z * z / (4 * trials * trials)) ** 0.5)
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


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
    counts = _count_rows(rows)
    answerable = counts["answerable"]
    answered_answerable = counts["answered_answerable"]
    unanswerable = counts["unanswerable"]
    refusals_total = counts["refusals_total"]
    refused_unanswerable = counts["refused_unanswerable"]
    probe_items = counts["probe_items"]
    refusals_by_stratum = counts["refusals_by_stratum"]
    grounded_items = counts["grounded_items"]
    cited = _count_citations(rows)
    cited_total = cited["cited_total"]
    cited_gold = cited["cited_gold"]
    cited_chapter = cited["cited_chapter"]
    cited_answerable = cited["cited_answerable"]
    retrieved_total = cited["retrieved_total"]
    retrieved_gold = cited["retrieved_gold"]
    retrieved_chapter = cited["retrieved_chapter"]
    language_ok_count = cited["language_ok"]
    format_ok_count = cited["format_ok"]

    def rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    return {
        "items": len(rows),
        "citation_precision": rate(cited_gold, cited_total),
        "citation_precision_chapter": rate(cited_chapter, cited_total),
        "citation_precision_retrieved": rate(retrieved_gold, retrieved_total),
        "citation_precision_chapter_retrieved": rate(retrieved_chapter, retrieved_total),
        "citations_retrieved_total": retrieved_total,
        "false_refusal_by_stratum": {
            name: {
                "answerable": counts[0],
                "refused": counts[1],
                "rate": rate(counts[1], counts[0]),
            }
            for name, counts in sorted(refusals_by_stratum.items())
        },
        "vocabulary_probe_items": probe_items,
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
        # A8-08: every proportion with the trials behind it and a 95% Wilson
        # interval, so a target like "false refusal <= 5%" can be read against
        # its own uncertainty instead of a bare point estimate. Additive: the
        # replay gate reads the flat rates above and ignores this block.
        "intervals_95": {
            "citation_precision": {
                "n": cited_total,
                "successes": cited_gold,
                "ci": wilson_interval(cited_gold, cited_total),
            },
            "citation_precision_chapter": {
                "n": cited_total,
                "successes": cited_chapter,
                "ci": wilson_interval(cited_chapter, cited_total),
            },
            "citation_recall": {
                "n": answered_answerable,
                "successes": cited_answerable,
                "ci": wilson_interval(cited_answerable, answered_answerable),
            },
            "abstention_precision": {
                "n": refusals_total,
                "successes": refused_unanswerable,
                "ci": wilson_interval(refused_unanswerable, refusals_total),
            },
            "abstention_recall": {
                "n": unanswerable,
                "successes": refused_unanswerable,
                "ci": wilson_interval(refused_unanswerable, unanswerable),
            },
            "false_refusal_rate": {
                "n": answerable,
                "successes": answerable - answered_answerable,
                "ci": wilson_interval(answerable - answered_answerable, answerable),
            },
            "refusal_correctness_unsafe": {
                "n": unsafe_total,
                "successes": refusal_correct_unsafe,
                "ci": wilson_interval(refusal_correct_unsafe, unsafe_total),
            },
            "response_language_correctness": {
                "n": grounded_items,
                "successes": language_ok_count,
                "ci": wilson_interval(language_ok_count, grounded_items),
            },
            "format_validity": {
                "n": grounded_items,
                "successes": format_ok_count,
                "ci": wilson_interval(format_ok_count, grounded_items),
            },
        },
    }


def _retrieved_sources(tutor: Any, item: dict) -> list:
    """The passages retrieval returns for an item, or [] when unsupported.

    A8-08: the report carries both readings of citation precision (attached
    vs retrieved) without a second evaluation pass. A tutor double without the
    method yields an empty list, and the aggregation then falls back to the
    attached set -- the report never claims a retrieved set it did not see.
    """
    method = getattr(tutor, "retrieved_sources", None)
    if not callable(method):
        return []
    return list(method(item["question"], item["class_level"], item.get("subject") or None) or [])


async def run_generation_report(
    tutor: Any,
    items: list[dict],
    *,
    unsafe_items: list[dict] | None = None,
    rows_out: list[dict] | None = None,
) -> dict[str, Any]:
    """Run every item through the tutor and aggregate the A8-04 metrics.

    ``unsafe_items`` (the red-team set) are run first and scored for refusal
    correctness only; they are never mixed into the golden-set counts.
    ``rows_out`` (A8-08) collects the per-item rows -- split, stratum, expect,
    grounded, source_count, no question or answer text -- so a caller can
    compute confidence intervals per metric or slice the frozen held-out
    split without re-running the tutor.
    """
    rows: list[dict[str, Any]] = []
    for item in items:
        if item["expect"] == "refuse":
            row: dict[str, Any] = {
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
        row["retrieved_sources"] = _retrieved_sources(tutor, item)
        row["answer"] = str(getattr(response, "answer", "") or "")
        row["split"] = item.get("split", "dev")
        row["stratum"] = item.get("stratum")
        rows.append(row)
        if rows_out is not None:
            # Per-item evidence for confidence intervals (A8-08): flags and
            # counts only -- never the question or the answer text.
            matched_gold = sum(
                1
                for source in row["sources"]
                if source_matches_gold(
                    source, chapter=row["gold_chapter"], section=row["gold_section"]
                )
            )
            rows_out.append(
                {
                    "expect": row["expect"],
                    "grounded": row["grounded"],
                    "split": item.get("split", "dev"),
                    "stratum": item.get("stratum"),
                    "source_count": len(row["sources"]),
                    "matched_gold_sources": matched_gold,
                    "language_ok": language_ok(row["answer"]),
                    "format_ok": format_ok(row["answer"], source_count=len(row["sources"])),
                }
            )
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
