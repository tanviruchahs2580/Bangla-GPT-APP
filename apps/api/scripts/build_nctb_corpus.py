"""NCTB corpus build CLI.

Usage (from apps/api, with the package venv active):
    python scripts/build_nctb_corpus.py --data-dir ../../data/nctb \
        --subset ssc-science --delay 2.0

Stages:
    1. acquire — respectful download of officially linked PDFs
    2. process — extract pages + QC + chunking + JSONL artifacts
    3. classes — derived class detection stamped onto chunk files
    4. report — cross-source duplicate statistics + corpus manifest

The build is reproducible: the same raw PDFs and the same pipeline code
produce byte-identical chunk files, and the manifest records the code
fingerprint, source hashes and artifact digests that prove it. After a build,
run scripts/evaluate_nctb_retrieval.py (which finalizes the manifest's derived
digests) and scripts/check_corpus_manifest.py (which fails on any drift).

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
from bangla_gpt_api.nctb.corpus import (
    build_corpus_manifest,
    load_manifest,
    process_source,
    record_cross_source_report,
)
from bangla_gpt_api.nctb.manifest import CORPUS_MANIFEST_NAME

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


def _run_content_gate(normalized_dir: Path, *, allow_fail: bool) -> bool:
    """Run ``content_qa`` over every source and report a pass/fail verdict.

    Returns True when every source is inside its flagged-chunk budget. Also
    reports the NBT-001 reph invariant, which no gate used to state: a Bangla
    word cannot close with ``র`` + halant, so any count above zero means the
    converter regressed.
    """
    from bangla_gpt_api.nctb.content_qa import DEFAULT_FLAGGED_THRESHOLD, qa_chunks
    from bangla_gpt_api.nctb.corpus import load_chunks_jsonl
    from bangla_gpt_api.nctb.reph import word_final_reph_count

    print(f"\nContent gate (threshold {DEFAULT_FLAGGED_THRESHOLD} flagged ratio):")
    files = sorted(normalized_dir.glob("nctb-*.chunks.jsonl"))
    if not files:
        print("  ERROR no chunk files found — nothing was built", file=sys.stderr)
        return False

    failures: list[str] = []
    reph_total = 0
    for path in files:
        chunks = load_chunks_jsonl(path)
        rows = [{"chunk_id": c.chunk_id, "chapter": c.chapter, "text": c.text} for c in chunks]
        report = qa_chunks(rows, threshold=DEFAULT_FLAGGED_THRESHOLD)
        reph_total += sum(word_final_reph_count(c.text) for c in chunks)
        status = "pass" if report.passed else "FAIL"
        print(
            f"  {status}  {path.stem}: flagged {report.flagged_chunks}/{report.total_chunks} "
            f"({report.flagged_ratio:.4f})"
        )
        for code, count in sorted((report.issues or {}).items()):
            print(f"          {code}: {count}")
        if not report.passed:
            failures.append(path.stem)

    print(f"  reph invariant: word-final reph occurrences = {reph_total} (must be 0)")
    if reph_total:
        failures.append(f"reph-invariant({reph_total})")

    if not failures:
        print("  content gate: PASS")
        return True

    print(f"  content gate: FAIL — {', '.join(failures)}", file=sys.stderr)
    if allow_fail:
        print(
            "  --allow-failing-content-gate was passed: continuing anyway, and the "
            "manifest will record that the content gate failed.",
            file=sys.stderr,
        )
        return True
    return False


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
        "--allow-failing-content-gate",
        action="store_true",
        help=(
            "debug only: produce artifacts and a manifest even though content_qa "
            "failed. The failure is still printed and is not waived for CI."
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

    cross = record_cross_source_report(report_path, out_normalized)
    print("\nCross-source duplicates (quality_report._cross_source):")
    print(
        f"  chunks={cross['total_chunks']} unique_texts={cross['unique_texts']} "
        f"duplicate_chunks={cross['duplicate_chunks']} "
        f"cross_source_texts={cross['cross_source_texts']} "
        f"cross_source_duplicate_chunks={cross['cross_source_duplicate_chunks']}"
    )

    reports = json.loads(report_path.read_text(encoding="utf-8"))
    empty_chapter = [
        source_id
        for source_id, row in reports.items()
        if source_id != "_cross_source" and row.get("chunks") and not row.get("chunks_with_chapter")
    ]
    print("\nChapter coverage:")
    for source_id, row in sorted(reports.items()):
        if source_id == "_cross_source" or not row.get("chunks"):
            continue
        print(
            f"  {source_id}: {row.get('chunks_with_chapter')}/{row.get('chunks')} "
            f"({row.get('chapter_coverage')})"
        )
    if empty_chapter:
        # A source with no chapter metadata is a fact to record, not a silent
        # hole: chapter-scoped filters and metrics are blind there (F-081).
        print(
            "  WARNING no chapter headings detected in: "
            + ", ".join(sorted(empty_chapter))
            + " — chapter filters are unavailable for those documents"
        )

    # Content gate BEFORE the manifest is written (audit finding NBT-004).
    #
    # `content_qa.py` has always existed and has always exited 3 with the
    # message "do NOT index this corpus" — but the build never called it, no
    # workflow called it, no Make target called it, and pre-commit did not
    # call it. Measured on the corpus that shipped: 301 of 852 chunks
    # (35.33%) were flagged, 17.7x over the 2% budget, with `pua_char` on
    # every one of the nine sources. A gate nothing runs is a comment.
    #
    # It sits here, not after, on purpose: a manifest is provenance evidence
    # that a corpus was built by this code, and provenance for a corpus that
    # must not be indexed is not worth writing. `--allow-failing-content-gate`
    # exists so an operator can still produce the artifacts they need to see
    # *why* it failed; it prints the bypass loudly and the manifest records it.
    gate_ok = _run_content_gate(out_normalized, allow_fail=args.allow_failing_content_gate)
    if not gate_ok:
        print(
            "\nBUILD STOPPED: the content gate failed, so no manifest was written.\n"
            "  Inspect:  python scripts/content_qa.py report <chunks.jsonl>\n"
            "  Sample:   python scripts/content_qa.py sample <chunks.jsonl> "
            "--seed 20260906 --out review_sheet.jsonl\n"
            "  This corpus must not be indexed until the flagged sources pass.",
            file=sys.stderr,
        )
        return 3

    manifest = build_corpus_manifest(
        args.data_dir,
        records,
        report_path=report_path,
        extracted_dir=out_extracted,
        normalized_dir=out_normalized,
    )
    manifest_path = args.data_dir / "manifests" / CORPUS_MANIFEST_NAME
    print(f"\nCorpus manifest: {manifest_path}")
    print(f"  chunks={manifest['totals']['chunks']}")
    print(f"  pipeline fingerprint: {manifest['pipeline']['code_fingerprint']}")
    print(
        "  next: scripts/evaluate_nctb_retrieval.py "
        f"{args.data_dir} (finalizes the manifest), then "
        "scripts/check_corpus_manifest.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
