"""Verify the tracked NCTB corpus artifacts against the corpus manifest.

    python scripts/check_corpus_manifest.py --data-dir ../../data/nctb
    python scripts/check_corpus_manifest.py --data-dir ../../data/nctb \
        --rebuild-dir ../../.qa-work/tmp/rebuild
    python scripts/check_corpus_manifest.py --corpus-dir ../../data/nctb

Exit code 0 = every checked number agrees; 1 = at least one disagreement,
printed with the leg that produced it.

Tracked-artifact legs (no PDFs needed, so this runs in CI):

1. shape + pipeline code fingerprint -- the corpus was built by the code in
   this tree;
2. provenance chain: the acquisition manifest still lists every source with
   the recorded content hash, file name, level and subject;
3. quality_report.json agrees with the manifest, and its digest is the one
   the manifest recorded;
4. retrieval_eval.json agrees with the manifest, and its digest is the one
   the manifest recorded.

Optional legs, where the corpus itself is present:

* ``--corpus-dir DIR``: the chunk files ARE the ones the manifest describes,
  and the loader builds exactly the recorded number of index chunks. This leg
  fails when the served corpus is stale or hand-edited; run it against the
  directory a deployment actually mounts.
* ``--rebuild-dir DIR``: a fresh build (the output of build_nctb_corpus.py)
  matches the tracked manifest field by field -- per-source content hash,
  chunk counts, artifact digests, totals, tool fingerprint. This is the leg
  that fails when the tracked reports disagree with a rebuild.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_provenance(data_dir: Path, manifest: dict, problems: list[str]) -> None:
    acquisition_path = data_dir / "manifests" / "acquisition_manifest.jsonl"
    recorded = (manifest.get("acquisition_manifest") or {}).get("sha256")
    from bangla_gpt_api.nctb.manifest import sha256_file

    if not acquisition_path.exists():
        problems.append("acquisition manifest is missing")
        return
    if recorded and sha256_file(acquisition_path) != recorded:
        problems.append("acquisition manifest digest differs from the one the manifest recorded")
    acquisition: dict[str, dict] = {}
    for line in acquisition_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            acquisition[record["source_id"]] = record
    for source in manifest.get("sources", []):
        source_id = source.get("source_id")
        record = acquisition.get(source_id)
        if record is None:
            problems.append(f"{source_id}: not in the acquisition manifest")
            continue
        for field in ("content_hash", "file_name", "file_size", "level", "subject_bn"):
            if source.get(field) != record.get(field):
                problems.append(
                    f"{source_id}: {field} manifest {source.get(field)!r} != "
                    f"acquisition {record.get(field)!r}"
                )
        # curriculum_year is provenance (the listing's edition statement), so
        # it is checked against the acquisition ledger, not the derived report.
        if source.get("curriculum_year") != record.get("curriculum_year"):
            problems.append(
                f"{source_id}: curriculum_year manifest {source.get('curriculum_year')!r} != "
                f"acquisition {record.get('curriculum_year')!r}"
            )


def _check_reports(data_dir: Path, manifest: dict, problems: list[str]) -> None:
    from bangla_gpt_api.nctb.manifest import sha256_file

    report_path = data_dir / "quality_report.json"
    eval_path = data_dir / "retrieval_eval.json"
    derived = manifest.get("derived") or {}
    if not report_path.exists():
        problems.append("quality_report.json is missing")
    else:
        if derived.get("quality_report_sha256") != sha256_file(report_path):
            problems.append(
                "quality_report.json digest differs from the manifest's record "
                "(the report was regenerated without the manifest)"
            )
        reports = _read(report_path)
        for source in manifest.get("sources", []):
            source_id = source.get("source_id")
            row = reports.get(source_id)
            if row is None:
                problems.append(f"{source_id}: not in quality_report.json")
                continue
            for field in ("chunks", "total_pages", "usable_pages", "chunks_with_chapter"):
                if source.get(field) != row.get(field):
                    problems.append(
                        f"{source_id}: {field} manifest {source.get(field)!r} != "
                        f"report {row.get(field)!r}"
                    )
        declared_total = (manifest.get("totals") or {}).get("chunks")
        report_total = sum(
            int((row or {}).get("chunks") or 0)
            for key, row in reports.items()
            if key != "_cross_source"
        )
        if declared_total is not None and int(declared_total) != report_total:
            problems.append(
                f"quality_report totals {report_total} chunks != manifest {declared_total}"
            )
    if not eval_path.exists():
        problems.append("retrieval_eval.json is missing")
        return
    if derived.get("retrieval_eval_sha256") != sha256_file(eval_path):
        problems.append(
            "retrieval_eval.json digest differs from the manifest's record "
            "(the eval was rerun without regenerating the manifest)"
        )
    retrieval = _read(eval_path)
    if derived.get("index_chunks") is not None and retrieval.get("corpus_chunks") != derived.get(
        "index_chunks"
    ):
        problems.append(
            f"retrieval_eval.corpus_chunks {retrieval.get('corpus_chunks')} != "
            f"manifest index_chunks {derived.get('index_chunks')}"
        )


def _check_corpus_tree(corpus_dir: Path, manifest: dict, problems: list[str]) -> None:
    """The chunk files on disk are the manifest's, and the loader agrees."""
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
    from bangla_gpt_api.nctb.manifest import verify_corpus_manifest

    _manifest, file_problems = verify_corpus_manifest(
        corpus_dir, check_code_fingerprint=False, check_files=True
    )
    problems.extend(f"served corpus: {problem}" for problem in file_problems)
    chunks = load_nctb_corpus(
        corpus_dir / "normalized",
        quality_report_path=corpus_dir / "quality_report.json",
        verify_manifest=False,
    )
    derived = manifest.get("derived") or {}
    if derived.get("index_chunks") is not None and len(chunks) != int(derived["index_chunks"]):
        problems.append(
            f"loader builds {len(chunks)} index chunks, manifest records {derived['index_chunks']}"
        )


def _check_rebuild(rebuild_dir: Path, manifest: dict, problems: list[str]) -> None:
    """A fresh build directory matches the tracked manifest field by field."""
    from bangla_gpt_api.nctb.manifest import CORPUS_MANIFEST_NAME, read_json

    rebuild_manifest_path = rebuild_dir / "manifests" / CORPUS_MANIFEST_NAME
    if not rebuild_manifest_path.exists():
        problems.append(f"rebuild has no manifest at {rebuild_manifest_path}")
        return
    rebuild = read_json(rebuild_manifest_path)
    if rebuild.get("pipeline", {}).get("code_fingerprint") != manifest.get("pipeline", {}).get(
        "code_fingerprint"
    ):
        problems.append("rebuild used a different pipeline code fingerprint")
    if rebuild.get("totals") != manifest.get("totals"):
        problems.append(
            f"rebuild totals {rebuild.get('totals')} != tracked {manifest.get('totals')}"
        )
    tracked_sources = {source["source_id"]: source for source in manifest.get("sources", [])}
    for source in rebuild.get("sources", []):
        source_id = source.get("source_id")
        tracked = tracked_sources.get(source_id)
        if tracked is None:
            problems.append(f"{source_id}: present in the rebuild, absent from the manifest")
            continue
        for field in (
            "content_hash",
            "chunks",
            "chunks_with_chapter",
            "chapter_coverage",
            "extracted_sha256",
            "normalized_sha256",
            "extractor",
        ):
            if source.get(field) != tracked.get(field):
                problems.append(
                    f"{source_id}: {field} rebuild {source.get(field)!r} != tracked {tracked.get(field)!r}"
                )
    for source_id in tracked_sources:
        if source_id not in {source.get("source_id") for source in rebuild.get("sources", [])}:
            problems.append(f"{source_id}: in the tracked manifest but missing from the rebuild")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("../../data/nctb"))
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="also verify a served corpus directory against the manifest",
    )
    parser.add_argument(
        "--rebuild-dir",
        type=Path,
        default=None,
        help="also compare a fresh build directory against the manifest",
    )
    args = parser.parse_args()

    from bangla_gpt_api.nctb.manifest import CORPUS_MANIFEST_NAME, read_json

    manifest_path = args.data_dir / "manifests" / CORPUS_MANIFEST_NAME
    problems: list[str] = []
    if not manifest_path.exists():
        print(f"FAIL: no corpus manifest at {manifest_path}")
        return 1
    manifest = read_json(manifest_path)
    print(f"corpus manifest: {manifest_path}")
    print(
        f"  chunks={manifest.get('totals', {}).get('chunks')} "
        f"index_chunks={(manifest.get('derived') or {}).get('index_chunks')} "
        f"built_at={manifest.get('built_at')}"
    )
    print(f"  pipeline fingerprint: {manifest.get('pipeline', {}).get('code_fingerprint')}")

    from bangla_gpt_api.nctb.manifest import verify_corpus_manifest

    _manifest, shape_problems = verify_corpus_manifest(
        args.data_dir, check_files=False, check_code_fingerprint=True
    )
    problems.extend(shape_problems)

    _check_provenance(args.data_dir, manifest, problems)
    _check_reports(args.data_dir, manifest, problems)

    corpus_dir = args.corpus_dir
    if corpus_dir is not None:
        if (corpus_dir / "normalized").is_dir():
            print(f"served corpus: {corpus_dir}")
            _check_corpus_tree(corpus_dir, manifest, problems)
        else:
            problems.append(f"corpus dir {corpus_dir} has no normalized/ directory")
    if args.rebuild_dir is not None:
        print(f"rebuild: {args.rebuild_dir}")
        _check_rebuild(args.rebuild_dir, manifest, problems)

    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nOK: tracked corpus artifacts agree with the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
