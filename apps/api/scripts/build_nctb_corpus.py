"""NCTB corpus build CLI.

Usage (from apps/api, with the package venv active):
    python scripts/build_nctb_corpus.py --data-dir ../../data/nctb \
        --subset ssc-science --delay 2.0

Stages:
    1. acquire   — respectful download of officially linked PDFs
    2. process   — extract pages + QC + chunking + JSONL artifacts
    3. classes   — derived class detection stamped onto chunk files

Subsets:
    ssc-science : Secondary বাংলা/ইংরেজি/গণিত/বিজ্ঞান-শাখা/ICT
    hsc-science : HSC পদার্থ/রসায়ন/জীববিজ্ঞান/উচ্চতর-গণিত
    all         : every officially linked artifact (48)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bangla_gpt_api.data.nctb_loader import attach_detected_classes
from bangla_gpt_api.nctb import HSC_ARTIFACTS, SECONDARY_ARTIFACTS
from bangla_gpt_api.nctb.acquisition import acquire_many
from bangla_gpt_api.nctb.corpus import load_manifest, process_source

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
    print(f"\nProcessing {len(acquired)} acquired sources ...")
    for record in acquired:
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

    print(f"\nQuality report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
