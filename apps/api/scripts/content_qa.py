"""Content QA CLI (S6.2): automatic quality report + human-sampling flow.

Usage (from apps/api, with the package venv active):
    python scripts/content_qa.py report  normalized/<src>.chunks.jsonl
    python scripts/content_qa.py report  normalized/<src>.chunks.jsonl \
        --out qa_report.json --threshold 0.02
    python scripts/content_qa.py sample  normalized/<src>.chunks.jsonl \
        --seed 20260906 --out review_sheet.jsonl
    python scripts/content_qa.py review  review_sheet.jsonl \
        --verdicts verdicts.jsonl --out review_summary.json

Exit codes: 0 = pass / ok, 3 = QA gate failed (do NOT index this corpus),
2 = usage/IO error. The sample command marks each row's automatic
``qa_issues`` so reviewers see machine findings next to their own read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bangla_gpt_api.nctb.content_qa import (
    DEFAULT_FLAGGED_THRESHOLD,
    build_review_sheet,
    qa_chunks,
    summarize_review,
)
from bangla_gpt_api.nctb.corpus import load_chunks_jsonl


def _chunks_dicts(path: Path) -> list[dict]:
    return [
        {"chunk_id": c.chunk_id, "chapter": c.chapter, "text": c.text}
        for c in load_chunks_jsonl(path)
    ]


def _read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def cmd_report(args: argparse.Namespace) -> int:
    report = qa_chunks(_chunks_dicts(Path(args.chunks)), threshold=args.threshold)
    payload = report.to_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.passed else 3


def cmd_sample(args: argparse.Namespace) -> int:
    chunks = _chunks_dicts(Path(args.chunks))
    sheet = build_review_sheet(chunks, seed=args.seed, fraction=args.fraction)
    _write_jsonl(Path(args.out), sheet)
    print(json.dumps({"sampled": len(sheet), "of": len(chunks), "seed": args.seed}))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    sheet = _read_jsonl(Path(args.sheet))
    verdicts = _read_jsonl(Path(args.verdicts))
    summary = summarize_review(sheet, verdicts)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rep = sub.add_parser("report", help="automatic QA report + gate")
    rep.add_argument("chunks", help="chunks JSONL file")
    rep.add_argument("--out", help="write report JSON here")
    rep.add_argument("--threshold", type=float, default=DEFAULT_FLAGGED_THRESHOLD)
    rep.set_defaults(func=cmd_report)

    smp = sub.add_parser("sample", help="build deterministic human-review sheet")
    smp.add_argument("chunks", help="chunks JSONL file")
    smp.add_argument("--seed", type=int, required=True)
    smp.add_argument("--fraction", type=float, default=0.10)
    smp.add_argument("--out", required=True)
    smp.set_defaults(func=cmd_sample)

    rev = sub.add_parser("review", help="summarize human verdicts for a sheet")
    rev.add_argument("sheet", help="review sheet JSONL")
    rev.add_argument("--verdicts", required=True, help="JSONL rows {chunk_id, verdict}")
    rev.add_argument("--out", help="write summary JSON here")
    rev.set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
