#!/usr/bin/env python
"""Drift report: query topics versus corpus coverage and staleness (AUD-A2-13).

Two drifts matter for a curriculum-grounded tutor:

* **topic drift** -- what students ask about versus what the corpus covers.
  A topic with demand and no coverage is a curriculum-gap backlog item; a
  covered topic nobody asks about is a candidate for thinning.
* **corpus staleness** -- the corpus was built from a specific edition of the
  textbook; when the manifest records a newer curriculum year/edition for a
  subject than the corpus chunks carry, the answers are grounded in a
  superseded book.

Privacy: student question text is never read here. The topic distribution
comes from the frozen evaluation dataset (a labelled proxy) and, optionally,
from an operator-exported aggregate file with no free text:

    {"class_level": 6, "subject": "science", "chapter": "কোষ", "count": 12}

Run from ``apps/api``:

    python scripts/drift_report.py
    python scripts/drift_report.py --previous drift_report.json --out drift_report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bangla_gpt_api.curriculum.models import Chunk  # noqa: E402 (path set above)

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_DIR = REPO_ROOT / "data" / "nctb"
DEFAULT_EVAL = API_ROOT / "eval" / "golden_v2.json"
#: Coverage the product claims (README: classes 6-10, science/mathematics/bangla).
CLAIMED_CLASSES = (6, 7, 8, 9, 10)
CLAIMED_SUBJECTS = ("science", "mathematics", "bangla")


def _load_chunks(corpus_dir: Path) -> tuple[list[Chunk], str, str | None]:
    """Load the corpus; returns (chunks, source_label, note)."""
    normalized = corpus_dir / "normalized"
    quality = corpus_dir / "quality_report.json"
    if normalized.is_dir():
        from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

        chunks = load_nctb_corpus(
            normalized, quality_report_path=quality if quality.is_file() else None
        )
        if chunks:
            return chunks, f"nctb:{corpus_dir}", None
        note = f"corpus dir {corpus_dir} exists but yielded no chunks; used the bundled sample"
    else:
        note = f"corpus dir {corpus_dir} not found; used the bundled sample"
    from bangla_gpt_api.data.loader import load_sample_corpus

    return load_sample_corpus(), "bundled-sample", note


def _grid(chunks: list[Chunk]) -> dict[str, dict[str, Any]]:
    """class×subject grid with chapter counts and a stable corpus fingerprint."""
    cells: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        key = f"{chunk.meta.class_level}:{chunk.meta.subject}"
        cell = cells.setdefault(
            key,
            {
                "class_level": chunk.meta.class_level,
                "subject": chunk.meta.subject,
                "chunks": 0,
                "chapters": set(),
                "curriculum_years": set(),
            },
        )
        cell["chunks"] += 1
        cell["chapters"].add(chunk.meta.chapter)
        cell["curriculum_years"].add(chunk.meta.curriculum_year)
    for cell in cells.values():
        cell["chapters"] = sorted(cell["chapters"])
        cell["chapter_count"] = len(cell["chapters"])
        cell["curriculum_years"] = sorted(cell["curriculum_years"])
    return cells


def _coverage_gaps(cells: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    gaps = []
    for class_level in CLAIMED_CLASSES:
        for subject in CLAIMED_SUBJECTS:
            cell = cells.get(f"{class_level}:{subject}")
            if cell is None:
                gaps.append({"class_level": class_level, "subject": subject, "chunks": 0})
    return gaps


def _topic_counts(eval_path: Path, extra: Path | None) -> tuple[Counter, str, str | None]:
    """Query-topic distribution from the eval proxy and/or an aggregate file."""
    counts: Counter = Counter()
    sources = []
    note: str | None = None
    if eval_path.is_file():
        dataset = json.loads(eval_path.read_text(encoding="utf-8"))
        items = dataset.get("items", dataset if isinstance(dataset, list) else [])
        for item in items:
            counts[f"{item.get('class_level')}:{item.get('subject')}"] += 1
        sources.append(f"eval-proxy:{eval_path.name}({len(items)} items)")
    else:
        note = f"eval dataset {eval_path} not found; topic distribution is corpus-only"
    if extra is not None:
        rows = 0
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            counts[f"{row.get('class_level')}:{row.get('subject')}"] += int(row.get("count", 1))
            rows += 1
        sources.append(f"aggregate-queries:{extra.name}({rows} rows)")
    return counts, "+".join(sources) or "none", note


def _manifest_records(manifest_dir: Path) -> list[dict[str, Any]]:
    """Read every manifest file: JSONL (one record per line) or one JSON document."""
    records: list[dict[str, Any]] = []
    for path in sorted(manifest_dir.glob("*")):
        if path.suffix not in {".json", ".jsonl"}:
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
            continue
        payload = json.loads(text)
        rows = payload.get("sources", payload) if isinstance(payload, dict) else payload
        if isinstance(rows, dict):
            rows = list(rows.values())
        records.extend(row for row in rows or [] if isinstance(row, dict))
    return records


def _staleness(corpus_dir: Path, cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Corpus edition versus the newest manifest edition, plus hash integrity."""
    manifest_dir = corpus_dir / "manifests"
    newest_year: int | None = None
    manifest_rows = 0
    stale_sources: list[dict[str, Any]] = []
    for record in _manifest_records(manifest_dir) if manifest_dir.is_dir() else []:
        manifest_rows += 1
        year_raw = str(record.get("curriculum_year", "")).strip()
        try:
            year = int(year_raw)
        except ValueError:
            continue
        newest_year = year if newest_year is None else max(newest_year, year)
        status = record.get("source_status", "acquired")
        if status != "acquired":
            stale_sources.append({"source_id": record.get("source_id"), "status": status})
    corpus_years = sorted({year for cell in cells.values() for year in cell["curriculum_years"]})
    stale = bool(newest_year is not None and corpus_years and max(corpus_years) < newest_year)
    return {
        "manifest_rows": manifest_rows,
        "newest_manifest_curriculum_year": newest_year,
        "corpus_curriculum_years": corpus_years,
        "corpus_older_than_manifest": stale,
        "non_acquired_sources": stale_sources,
    }


def build_report(corpus_dir: Path, eval_path: Path, queries: Path | None) -> dict[str, Any]:
    chunks, source_label, note = _load_chunks(corpus_dir)
    cells = _grid(chunks)
    topics, topic_source, topic_note = _topic_counts(eval_path, queries)
    corpus_fingerprint = hashlib.sha256(
        "|".join(sorted(chunk.id for chunk in chunks)).encode()
    ).hexdigest()[:16]
    uncovered_demand = sorted(key for key in topics if key not in cells and topics[key] > 0)
    idle_coverage = sorted(key for key in cells if topics.get(key, 0) == 0)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": {
            "source": source_label,
            "note": note,
            "chunks": len(chunks),
            "fingerprint": corpus_fingerprint,
            "grid": cells,
            "claim": {
                "classes": list(CLAIMED_CLASSES),
                "subjects": list(CLAIMED_SUBJECTS),
            },
            "coverage_gaps": _coverage_gaps(cells),
        },
        "query_topics": {
            "source": topic_source,
            "note": topic_note,
            "counts": dict(sorted(topics.items())),
            "uncovered_demand": uncovered_demand,
            "covered_but_never_asked": idle_coverage,
        },
        "curriculum_staleness": _staleness(corpus_dir, cells),
    }
    return report


def _diff_against(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev_grid = set(previous.get("corpus", {}).get("grid", {}))
    now_grid = set(current["corpus"]["grid"])
    return {
        "coverage_cells_lost": sorted(prev_grid - now_grid),
        "coverage_cells_gained": sorted(now_grid - prev_grid),
        "previous_fingerprint": previous.get("corpus", {}).get("fingerprint"),
        "fingerprint_changed": previous.get("corpus", {}).get("fingerprint")
        != current["corpus"]["fingerprint"],
        "previous_generated_at": previous.get("generated_at"),
    }


def to_markdown(report: dict[str, Any]) -> str:
    corpus = report["corpus"]
    topics = report["query_topics"]
    stale = report["curriculum_staleness"]
    lines = [
        "# Corpus / query drift report",
        "",
        f"Generated: {report['generated_at']}",
        f"Corpus: `{corpus['source']}` ({corpus['chunks']} chunks, "
        f"fingerprint `{corpus['fingerprint']}`)",
    ]
    if corpus["note"]:
        lines.append(f"Note: {corpus['note']}")
    lines += ["", "## Coverage (class:subject)", ""]
    lines.append("| cell | chunks | chapters | curriculum years |")
    lines.append("|---|---:|---:|---|")
    for key, cell in sorted(corpus["grid"].items(), key=lambda kv: kv[0]):
        lines.append(
            f"| {key} | {cell['chunks']} | {cell['chapter_count']} | "
            f"{', '.join(str(y) for y in cell['curriculum_years'])} |"
        )
    lines += ["", "## Gaps against the product claim", ""]
    if corpus["coverage_gaps"]:
        for gap in corpus["coverage_gaps"]:
            lines.append(f"- MISSING {gap['class_level']}:{gap['subject']}")
    else:
        lines.append("- none: every claimed class×subject cell has chunks")
    lines += ["", "## Query topics", "", f"Source: {topics['source']}"]
    if topics["note"]:
        lines.append(f"Note: {topics['note']}")
    lines.append("")
    for key, count in sorted(topics["counts"].items()):
        lines.append(f"- {key}: {count}")
    if topics["uncovered_demand"]:
        lines += ["", "Demand with no coverage (curriculum-gap backlog):"]
        lines += [f"- {key}" for key in topics["uncovered_demand"]]
    if topics["covered_but_never_asked"]:
        lines += ["", "Covered but never asked (thinning candidates):"]
        lines += [f"- {key}" for key in topics["covered_but_never_asked"]]
    lines += [
        "",
        "## Staleness",
        "",
        f"- manifest rows: {stale['manifest_rows']}",
        f"- newest manifest curriculum year: {stale['newest_manifest_curriculum_year']}",
        f"- corpus curriculum years: {stale['corpus_curriculum_years']}",
        f"- corpus older than the manifest: {stale['corpus_older_than_manifest']}",
    ]
    if report.get("diff"):
        lines += ["", "## Diff against the previous report", ""]
        for key, value in report["diff"].items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus coverage and query-topic drift report.")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL, dest="eval_path")
    parser.add_argument("--queries", type=Path, help="optional aggregate query-topic JSONL")
    parser.add_argument("--previous", type=Path, help="previous report JSON for a diff")
    parser.add_argument("--out", type=Path, help="write the JSON report here")
    parser.add_argument("--markdown", type=Path, help="write the markdown summary here")
    parser.add_argument("--quiet", action="store_true", help="do not print the markdown")
    args = parser.parse_args(argv)

    report = build_report(args.corpus_dir, args.eval_path, args.queries)
    if args.previous and args.previous.is_file():
        report["diff"] = _diff_against(
            json.loads(args.previous.read_text(encoding="utf-8")), report
        )
    markdown = to_markdown(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    if not args.quiet:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
