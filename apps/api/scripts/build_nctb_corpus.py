"""NCTB corpus build CLI.

Usage (from apps/api, with the package venv active):
    python scripts/build_nctb_corpus.py --data-dir../../data/nctb \
        --subset ssc-science --delay 2.0

Stages:
    1. acquire — respectful download of officially linked PDFs
    2. process — extract pages + QC + chunking + JSONL artifacts
    3. classes — derived class detection stamped onto chunk files
    4. quality — per-chunk content QA gate; the build fails on a corpus
       that must not be indexed (report: <data-dir>/qa_report.json)

Subsets:
    ssc-science: Secondary বাংলা/ইংরেজি/গণিত/বিজ্ঞান-শাখা/ICT
    hsc-science: HSC পদার্থ/রসায়ন/জীববিজ্ঞান/উচ্চতর-গণিত
    all: every officially linked artifact (48)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import attach_detected_classes
from bangla_gpt_api.nctb import HSC_ARTIFACTS, SECONDARY_ARTIFACTS
from bangla_gpt_api.nctb.acquisition import acquire_many
from bangla_gpt_api.nctb.content_qa import qa_chunks
from bangla_gpt_api.nctb.corpus import (
    coverage_report,
    load_chunks_jsonl,
    load_manifest,
    process_source,
    prune_outputs,
)

SUBSETS = {
    "ssc-science": [
        "3ce5065b",  # বাংলা
        "afda21d8",  # ইংরেজি
        "be50d8af",  # গণিত ও উচ্চতর গণিত
        "e39c58d3",  # বিজ্ঞান শাখার বিষয়সমূহ
        "ca0d6bd8",  # আইসিটি ও ক্যারিয়ার এডুকেশন
    ],
    "hsc-science": [
        "28d03c59",  # পদার্থবিদ্যা
        "a5132033",  # রসায়ন
        "ca39e595",  # জীববিজ্ঞান
        "9c44bb8f",  # উচ্চতর গণিত
    ],
}


def _select(subset: str):
    if subset == "all":
        return list(SECONDARY_ARTIFACTS) + list(HSC_ARTIFACTS)
    prefixes = SUBSETS[subset]
    pool = {a.file_id[:8]: a for a in SECONDARY_ARTIFACTS}
    pool.update({a.file_id[:8]: a for a in HSC_ARTIFACTS})
    return [pool[p] for p in prefixes]


def _force_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/nctb"))
    parser.add_argument("--subset", choices=[*SUBSETS, "all"], default="ssc-science")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--skip-acquire", action="store_true")
    parser.add_argument(
        "--max-pages", type=int, default=None, help="limit extraction to first N pages (debug)"
    )
    parser.add_argument(
        "--only",
        default=None,
        help=(
            "process only sources whose id contains this substring "
            "(debug/re-extraction); pruning still considers every acquired source"
        ),
    )
    args = parser.parse_args()

    raw_dir = args.data_dir / "raw"
    manifest_path = args.data_dir / "manifests" / "acquisition_manifest.jsonl"
    out_extracted = args.data_dir / "extracted"
    out_normalized = args.data_dir / "normalized"
    report_path = args.data_dir / "quality_report.json"

    if not args.skip_acquire:
        from bangla_gpt_api.nctb.acquisition import fetch_url  # noqa: F401

        records = acquire_many(
            _select(args.subset), raw_dir, manifest_path, delay_seconds=args.delay
        )
        for record in records:
            print(f"{record.source_status:>18}  {record.source_id}  {record.subject_bn}")
    else:
        print("Skipping acquisition (--skip-acquire)")

    records = load_manifest(manifest_path)
    acquired = [r for r in records.values() if r.source_status == "acquired"]
    if not acquired:
        print(
            "No acquired sources in the manifest — the acquisition step did not "
            "produce raw PDFs, so there is nothing to build. Re-run without "
            "--skip-acquire (or fix the acquisition errors above).",
            file=sys.stderr,
        )
        return 1
    # Stale-output prune: derived artifacts of sources that are no longer
    # acquired must not stay indexable (AUD-A1-07). The loader globs every
    # *.chunks.jsonl that has a report row, so both the artifact and its
    # report row are removed here.
    pruned = prune_outputs(
        out_extracted, out_normalized, report_path, {r.source_id for r in acquired}
    )
    if pruned["sources"]:
        print(
            f"Pruned stale outputs of {len(pruned['sources'])} no-longer-acquired "
            f"source(s): {', '.join(pruned['sources'])}"
        )

    # --only re-processes a subset (debug/re-extraction) while pruning keeps
    # every acquired source, so a targeted rebuild can never evict the rest.
    to_process = [r for r in acquired if args.only is None or args.only in r.source_id]
    if args.only is not None:
        print(f"--only {args.only!r}: processing {len(to_process)}/{len(acquired)} sources")
    print(f"\nProcessing {len(to_process)} acquired sources ...")
    for record in to_process:
        summary = process_source(
            record,
            raw_dir,
            out_extracted,
            out_normalized,
            report_path,
            max_pages=args.max_pages,
        )
        print(
            f"{summary.get('subject_bn', '?')}: usable "
            f"{summary.get('usable_pages', 0)}/{summary.get('total_pages', 0)} pages, "
            f"chunks={summary.get('chunks', 0)}"
            + (f" ERROR={summary['error']}" if summary.get("error") else "")
        )

    detections = attach_detected_classes(out_extracted, out_normalized)
    print("\nDerived class detection:")
    for source_id, detected in detections.items():
        print(f"  {source_id}: {'class ' + str(detected) if detected else 'UNDETECTED'}")

    # Content QA gate: a corpus that fails the per-chunk QA must not be
    # indexed; the report lists every flagged chunk for investigation.
    qa_report_path = args.data_dir / "qa_report.json"
    quality = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    qa_report: dict[str, dict] = {}
    failed_sources: list[str] = []
    for path in sorted(out_normalized.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        rows = [
            {"chunk_id": chunk.chunk_id, "text": chunk.text} for chunk in load_chunks_jsonl(path)
        ]
        bangla_source = (
            float(quality.get(source_id, {}).get("bangla_char_ratio_on_usable", 0.0)) >= 0.5
        )
        report = qa_chunks(rows, bangla_source=bangla_source)
        qa_report[source_id] = report.to_dict()
        status = "pass" if report.passed else "FAIL"
        print(
            f"  qa {status}: {path.name} "
            f"({report.flagged_chunks}/{report.total_chunks} flagged, "
            f"issues={report.issues or 'none'})"
        )
        if not report.passed:
            failed_sources.append(path.name)
    qa_report_path.write_text(
        json.dumps(qa_report, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )
    print(f"\nContent QA report: {qa_report_path}")
    if failed_sources:
        print(
            "CONTENT QA GATE FAILED — do not index this corpus: " + ", ".join(failed_sources),
            file=sys.stderr,
        )
        return 1

    # Coverage report: what the corpus actually serves per class × subject ×
    # chapter, and which sources could not be assigned to a class. This is
    # the artifact the coverage-gated-refusal claim is read against
    # (AUD-A1-14) — gaps are listed, not inferred from absence of errors.
    coverage_path = args.data_dir / "coverage_report.json"
    coverage = coverage_report(out_normalized, report_path)
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )
    print(f"\nCoverage report: {coverage_path}")
    for class_level, subjects in coverage["classes"].items():
        for subject, entry in subjects.items():
            print(
                f"  class {class_level} {subject}: {entry['chunks']} chunks, "
                f"{entry['chapter_count']} chapters"
            )
    if coverage["unassigned_sources"]:
        print(f"  unassigned sources: {', '.join(coverage['unassigned_sources'])}")

    print(f"\nQuality report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
