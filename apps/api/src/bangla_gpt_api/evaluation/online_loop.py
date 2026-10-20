"""A8-09 / AUD-A2-13: the online-loop logic -- feedback to trace to eval item.

The pure half of ``scripts/eval_loop.py``: join a rated tutor answer to its
trace record, build candidate evaluation items, fold low-coverage traces into a
privacy-safe curriculum-gap backlog, and turn human triage into golden-shaped
items. Nothing here touches the database or the filesystem beyond reading a
trace log, so every rule is unit testable; the script owns the DB access, the
corpus lookup and the CLI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

#: A retrieval trace below this coverage is a curriculum-gap signal.
LOW_COVERAGE_THRESHOLD = 0.5

#: Verdicts a triager may record for a candidate.
TRIAGE_VERDICTS = ("accept", "reject", "edit")


def question_fingerprint(question: str) -> str:
    """Stable pseudo-id for a question: correlate without storing the text."""
    return hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:12]


def split_of(question: str) -> str:
    """The golden generator's split rule (scripts/gen_golden_v2.py), reused."""
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()
    return "dev" if int(digest[:8], 16) % 100 < 70 else "test"


def load_trace_log(path: Path | None) -> list[dict]:
    """Read captured trace lines; tolerate non-JSON noise in the sink."""
    if path is None or not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("event") == "trace":
            records.append(payload)
    return records


def _source_keys(message_sources: list[dict]) -> list[tuple[str, str, Any]]:
    """(chapter, section, page) triples of an answer's citations, in order."""
    return [
        (str(source.get("chapter") or ""), str(source.get("section") or ""), source.get("page"))
        for source in message_sources
    ]


def _trace_keys(
    trace: dict, chunk_meta: dict[str, tuple[str, str, Any]]
) -> list[tuple[str, str, Any]] | None:
    """The same triples for a trace's retrieved ids, when the corpus maps them."""
    keys = []
    for chunk_id in trace.get("retrieved_ids") or []:
        meta = chunk_meta.get(str(chunk_id))
        if meta is None:
            return None
        keys.append(meta)
    return keys


def _is_ordered_subset(wanted: list, keys: list) -> bool:
    """True when ``wanted`` appears, in order, inside ``keys`` (A8-08).

    An answer attaches the passages it leans on, which is a subset of the
    trace's retrieved set, in retrieval order. The join stays exact by
    requiring uniqueness (see :func:`build_candidates`): a citation list that
    fits several unused traces is not joined on this rule.
    """
    if len(wanted) > len(keys):
        return False
    iterator = iter(keys)
    return all(any(key == item for key in iterator) for item in wanted)


def _unique_citation_join(
    wanted: list[tuple[str, str, Any]],
    retrieval_traces: list[dict],
    chunk_meta: dict[str, tuple[str, str, Any]],
    used: set[int],
) -> int | None:
    """The one unused trace whose retrieved ids contain ``wanted`` in order.

    ``None`` when no trace fits OR more than one does: the join is exact, so
    an ambiguous fit is not a join (the caller falls through to the weaker,
    labelled count rule).
    """
    if not wanted or not chunk_meta:
        return None
    matches = [
        index
        for index, trace in enumerate(retrieval_traces)
        if index not in used
        and (keys := _trace_keys(trace, chunk_meta)) is not None
        and _is_ordered_subset(wanted, keys)
    ]
    return matches[0] if len(matches) == 1 else None


def build_candidates(
    ratings: list[dict],
    traces: list[dict],
    chunk_meta: dict[str, tuple[str, str, Any]] | None = None,
) -> tuple[list[dict], list[str]]:
    """Candidates + notes; the trace join is explicit and never invented.

    Join order: (1) **citations** -- the answer's citation triples appear, in
    order, inside exactly one unused trace's retrieved ids (requires the
    corpus to map ids to metadata; A8-08 made the answer attach only the
    passages it leans on, so this is a subset rule with a uniqueness
    requirement, not an equality that the selection would always break);
    (2) **count** -- a unique unused retrieval trace with the same number of
    evidence chunks (weaker, labelled as such); (3) **unmatched**, with
    ``trace: null``.
    """
    chunk_meta = chunk_meta or {}
    retrieval_traces = [t for t in traces if t.get("stage") == "retrieval"]
    used: set[int] = set()
    candidates: list[dict] = []
    notes: list[str] = []
    for row in ratings:
        if not row["question"]:
            notes.append(f"feedback {row['feedback_id']}: no preceding user turn, skipped")
            continue
        method = "unmatched"
        joined: dict | None = None
        wanted = _source_keys(row["sources"])
        cited_index = _unique_citation_join(wanted, retrieval_traces, chunk_meta, used)
        if cited_index is not None:
            joined, method = retrieval_traces[cited_index], "citations"
            used.add(cited_index)
        if joined is None and wanted:
            same_count = [
                index
                for index, trace in enumerate(retrieval_traces)
                if index not in used and trace.get("evidence_chunks") == len(wanted)
            ]
            if len(same_count) == 1:
                joined, method = retrieval_traces[same_count[0]], "count"
                used.add(same_count[0])
        candidates.append(
            {
                "candidate_id": f"fb{row['feedback_id']}",
                "question": row["question"],
                "question_fingerprint": question_fingerprint(row["question"]),
                "class_level": row["class_level"],
                "subject": None,
                "chapter": (row["sources"][0].get("chapter") if row["sources"] else None),
                "expected": "answer",
                "answerability": "unknown_pending_triage",
                "synthetic": False,
                "needs_teacher_review": True,
                "split": split_of(row["question"]),
                "provenance": {
                    "kind": "student_feedback",
                    "feedback_id": row["feedback_id"],
                    "message_id": row["message_id"],
                    "rating": row["rating"],
                    "created_at": row["created_at"],
                    "comment_present": row["comment_present"],
                },
                "rated_answer": {
                    "grounded": row["grounded"],
                    "refused_reason": row["refused_reason"],
                    "sources": row["sources"],
                },
                "trace_join": method,
                "trace": (
                    {
                        "trace_id": joined.get("trace_id"),
                        "coverage": joined.get("coverage"),
                        "gate": joined.get("gate"),
                        "top_score": joined.get("top_score"),
                        "evidence_chunks": joined.get("evidence_chunks"),
                        "index_version": joined.get("index_version"),
                        "retrieved_ids": joined.get("retrieved_ids"),
                    }
                    if joined
                    else None
                ),
            }
        )
    return candidates, notes


def _low_coverage_traces(traces: list[dict]) -> list[dict]:
    low = []
    for trace in traces:
        coverage = trace.get("coverage")
        if (
            trace.get("stage") == "retrieval"
            and coverage is not None
            and coverage < LOW_COVERAGE_THRESHOLD
        ):
            low.append(trace)
    return low


def gap_backlog(
    traces: list[dict], chapter_of: dict[str, tuple[str, str, Any]] | None = None
) -> dict[str, Any]:
    """Privacy-safe curriculum-gap aggregates from low-coverage traces.

    Groups by (class_level, chapter) where the chapter is resolvable from the
    trace's retrieved ids through the corpus; otherwise ``chapter: null`` with
    the count kept. The question text never enters this artifact -- only a
    hashed fingerprint, so ops can count gaps without reading what children
    asked.
    """
    chapter_of = chapter_of or {}
    groups: dict[tuple[int | None, str | None], dict[str, Any]] = {}
    for trace in _low_coverage_traces(traces):
        class_level = trace.get("class_level")
        chapters = [
            chapter_of[str(chunk_id)][0]
            for chunk_id in trace.get("retrieved_ids") or []
            if str(chunk_id) in chapter_of and chapter_of[str(chunk_id)][0]
        ]
        chapter = chapters[0] if chapters else None
        key = (class_level, chapter)
        group = groups.setdefault(
            key,
            {"class_level": class_level, "chapter": chapter, "count": 0, "coverage_sum": 0.0},
        )
        group["count"] += 1
        group["coverage_sum"] += float(trace.get("coverage") or 0.0)
    rows = [
        {
            "class_level": group["class_level"],
            "chapter": group["chapter"],
            "count": group["count"],
            "mean_coverage": round(group["coverage_sum"] / group["count"], 4)
            if group["count"]
            else 0.0,
        }
        for group in groups.values()
    ]
    rows.sort(key=lambda row: (row["class_level"] or 0, row["chapter"] or ""))
    return {
        "threshold": LOW_COVERAGE_THRESHOLD,
        "low_coverage_traces": sum(row["count"] for row in rows),
        "rows": rows,
        "note": (
            "aggregates only: no question text, only counts and mean coverage; "
            "chapter is null when the retrieved ids are not resolvable in the corpus"
        ),
    }


def triage_file(candidates: list[dict]) -> dict[str, Any]:
    """The weekly triage sheet: one row per candidate, verdict columns empty."""
    return {
        "instructions": (
            "For each candidate: set verdict to accept|reject|edit, set answerability to "
            "in_corpus|out_of_corpus (it decides the expected behaviour), fill reviewer, and "
            "correct the question/expected fields when verdict is edit."
        ),
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "question": candidate["question"],
                "class_level": candidate["class_level"],
                "trace_join": candidate["trace_join"],
                "coverage": (candidate["trace"] or {}).get("coverage"),
                "verdict": "",
                "answerability": "",
                "expected": "",
                "corrected_question": "",
                "reviewer": "",
                "reviewed_at": "",
            }
            for candidate in candidates
        ],
    }


def triage_candidates(
    candidates: list[dict], decisions: dict[str, Any]
) -> tuple[list[dict], list[dict], list[str]]:
    """Turn decided candidates into golden-shaped items (accept/edit) or rejects."""
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    approved: list[dict] = []
    rejected: list[dict] = []
    problems: list[str] = []
    for row in decisions.get("candidates", []):
        verdict = (row.get("verdict") or "").strip()
        if not verdict:
            continue
        candidate = by_id.get(row["candidate_id"])
        if candidate is None:
            problems.append(f"{row['candidate_id']}: no such candidate")
            continue
        if verdict not in TRIAGE_VERDICTS:
            problems.append(f"{row['candidate_id']}: verdict {verdict!r} not in {TRIAGE_VERDICTS}")
            continue
        if not (row.get("reviewer") or "").strip():
            problems.append(f"{row['candidate_id']}: verdict without a reviewer")
            continue
        if verdict == "reject":
            rejected.append({**row, "question": candidate["question"]})
            continue
        answerability = (row.get("answerability") or "").strip()
        if answerability not in {"in_corpus", "out_of_corpus"}:
            problems.append(f"{row['candidate_id']}: answerability must be in_corpus|out_of_corpus")
            continue
        question = (row.get("corrected_question") or "").strip() or candidate["question"]
        expected = (row.get("expected") or "").strip() or (
            "answer" if answerability == "in_corpus" else "refuse"
        )
        approved.append(
            {
                "question": question,
                "class_level": candidate["class_level"],
                "subject": candidate["subject"],
                "expect": expected,
                "answerability": answerability,
                "stratum": "feedback",
                "synthetic": False,
                "chapter": candidate.get("chapter"),
                "section": None,
                "split": split_of(question),
                "provenance": candidate["provenance"],
                "reviewer": row["reviewer"].strip(),
                "reviewed_at": (row.get("reviewed_at") or "").strip(),
            }
        )
    return approved, rejected, problems
