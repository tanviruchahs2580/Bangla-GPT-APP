"""End-to-end corpus construction: extract → QC → chunk → JSONL artifacts.

Outputs (data/nctb/):
    extracted/<source_id>.pages.json per-page raw text
    normalized/<source_id>.chunks.jsonl retrieval chunks with provenance
    quality_report.json per-source extraction QC metrics

Only pages whose text passes the corruption heuristics are chunked;
everything is reported, nothing is silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from bangla_gpt_api.nctb.chunking import (
    MAX_TOKENS,
    MIN_TOKENS,
    TARGET_TOKENS,
    TARGET_WORDS,
    RawChunk,
    chunk_pages,
    dedupe_chunks,
)
from bangla_gpt_api.nctb.extract import ExtractionResult, extract_pdf, qc_pages
from bangla_gpt_api.nctb.manifest import SourceRecord, load_manifest


def process_source(
    record: SourceRecord,
    raw_dir: Path,
    out_extracted: Path,
    out_normalized: Path,
    report_path: Path,
    *,
    max_pages: int | None = None,
) -> dict:
    source_id = record.source_id
    pdf_path = raw_dir / record.file_name
    summary: dict = {
        "source_id": source_id,
        "subject_bn": record.subject_bn,
        "level": record.level,
        "content_hash": record.content_hash,
        "status": record.source_status,
        # Edition/provenance from the acquisition ledger: the loader and the
        # served metadata read the year from here instead of falling back to
        # the build year for sources whose edition IS published (AUD-A1-05).
        "curriculum_year": record.curriculum_year,
        "edition": record.edition,
        "rights": rights_summary(record),
    }
    if not pdf_path.exists():
        summary["error"] = "raw file missing"
        # A source that cannot be reprocessed must not leave its previous
        # chunks behind: a stale artifact is exactly the state AUD-A1-07
        # describes (removed/renamed raw file, old index still serving).
        _drop_stale_outputs(out_normalized, out_extracted, source_id)
        _write_report(report_path, summary)
        return summary

    result = extract_pdf(pdf_path, max_pages=max_pages)
    if not result.ok:
        summary["error"] = result.error
        _drop_stale_outputs(out_normalized, out_extracted, source_id)
        _write_report(report_path, summary)
        return summary

    out_extracted.mkdir(parents=True, exist_ok=True)
    (out_extracted / f"{source_id}.pages.json").write_text(
        json.dumps(
            {"source_id": source_id, "pages": [asdict(p) for p in result.pages]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    qc = qc_pages(result.pages)
    chunk_stats: dict = {}
    chunks = chunk_pages(result.pages, source_id=source_id, stats=chunk_stats)
    # RAG-001: dedupe identical passages (reprints/overlapping pages) and
    # stamp version + build time so staleness is answerable per artifact.
    chunks, duplicates_removed = dedupe_chunks(chunks)

    out_normalized.mkdir(parents=True, exist_ok=True)
    with (out_normalized / f"{source_id}.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    summary.update(qc)
    summary["chunks"] = len(chunks)
    summary["duplicates_removed"] = duplicates_removed
    summary["short_blocks_merged"] = chunk_stats.get("short_blocks_merged", 0)
    summary["chunk_word_lengths"] = chunk_stats.get("chunk_word_lengths", [])
    # A3-01: chunk sizing is measured in tokens with the configured counter;
    # the artifact records the unit, the counter and the token histogram, so a
    # sizing change is visible in the report and not only in chunking.py.
    summary["chunk_token_lengths"] = chunk_stats.get("chunk_token_lengths", [])
    summary["chunk_sizing"] = {
        "unit": chunk_stats.get("sizing_unit", ""),
        "token_counter": chunk_stats.get("token_counter", ""),
        "target_tokens": TARGET_TOKENS,
        "min_tokens": MIN_TOKENS,
        "max_tokens": MAX_TOKENS,
        "target_words_fallback": TARGET_WORDS,
    }
    # A2-04e: table rows and formula lines preserved verbatim as units.
    summary["table_rows_preserved"] = chunk_stats.get("table_rows_preserved", 0)
    summary["formula_units_preserved"] = chunk_stats.get("formula_units_preserved", 0)
    # A2-05: per-chunk content hashes live in the report row (the chunk
    # manual's per-chunk checksum analogue of the per-document sha256 the
    # acquisition manifest already carries) — every survivor of dedupe.
    summary["chunk_hashes_sha256"] = [chunk.content_hash for chunk in chunks]
    summary["content_version"] = f"{record.processing_version}:{record.content_hash[:12]}"
    summary["built_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _write_report(report_path, summary)
    return summary


def _drop_stale_outputs(out_normalized: Path, out_extracted: Path, source_id: str) -> None:
    """Remove a failed source's derived artifacts so nothing stale is served."""
    for path in (
        out_normalized / f"{source_id}.chunks.jsonl",
        out_extracted / f"{source_id}.pages.json",
    ):
        if path.exists():
            path.unlink()


def prune_outputs(
    out_extracted: Path,
    out_normalized: Path,
    report_path: Path,
    keep_source_ids: set[str],
) -> dict[str, list[str]]:
    """Delete derived artifacts + report rows of sources no longer acquired.

    The build iterates the manifest's *currently acquired* sources only; a
    manifest record that flips to failed/skipped (or disappears) left its
    previous ``*.chunks.jsonl`` and ``quality_report.json`` row in place, and
    the loader globs every chunk file with a report row — so a deleted or
    renamed source stayed indexable (AUD-A1-07). Returns what was pruned.
    """
    pruned: dict[str, list[str]] = {"sources": [], "artifacts": []}
    for path in sorted(out_normalized.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        if source_id in keep_source_ids:
            continue
        path.unlink()
        pruned["artifacts"].append(str(path))
        pruned["sources"].append(source_id)
        pages = out_extracted / f"{source_id}.pages.json"
        if pages.exists():
            pages.unlink()
            pruned["artifacts"].append(str(pages))
    if report_path.exists():
        reports = json.loads(report_path.read_text(encoding="utf-8"))
        stale = [key for key in reports if key not in keep_source_ids]
        if stale:
            for key in stale:
                reports.pop(key)
                if key not in pruned["sources"]:
                    pruned["sources"].append(key)
            report_path.write_text(
                json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    return pruned


def coverage_report(chunks_dir: Path, quality_report_path: Path | None = None) -> dict:
    """Class × subject × chapter coverage of the built corpus (AUD-A1-14).

    Backs the coverage-gated-refusal claim with an artifact instead of an
    assertion: every (class_level, subject) rectangle the corpus actually
    serves, its chapter count, chunk count and — for classes declared by a
    source's level range — the chapters present. Sources whose level is
    unknown are listed under ``unassigned`` rather than guessed into a class.
    """
    reports: dict[str, dict] = {}
    if quality_report_path is not None and quality_report_path.exists():
        reports = json.loads(quality_report_path.read_text(encoding="utf-8"))
    from bangla_gpt_api.data.nctb_loader import LEVEL_CLASS_RANGE, SUBJECT_KEYS

    rows: dict[int, dict[str, dict]] = {}
    unassigned: list[str] = []
    for path in sorted(chunks_dir.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        report = reports.get(source_id, {})
        level = report.get("level")
        if level not in LEVEL_CLASS_RANGE:
            unassigned.append(source_id)
            continue
        low, high = LEVEL_CLASS_RANGE[level]
        subject = SUBJECT_KEYS.get(report.get("subject_bn", ""), "general")
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        stamped = next(
            (
                int(data["detected_class"])
                for data in records
                if data.get("detected_class") is not None
                and low <= int(data["detected_class"]) <= high
            ),
            None,
        )
        classes = [stamped] if stamped is not None else list(range(low, high + 1))
        for class_level in classes:
            entry = rows.setdefault(class_level, {}).setdefault(
                subject,
                {"chapters": set(), "chunks": 0, "sources": set()},
            )
            entry["chunks"] += len(records)
            entry["sources"].add(source_id)
            for data in records:
                if data.get("chapter"):
                    entry["chapters"].add(str(data["chapter"]))
    return {
        "classes": {
            str(class_level): {
                subject: {
                    "chapters": sorted(entry["chapters"]),
                    "chapter_count": len(entry["chapters"]),
                    "chunks": entry["chunks"],
                    "sources": sorted(entry["sources"]),
                }
                for subject, entry in sorted(subjects.items())
            }
            for class_level, subjects in sorted(rows.items())
        },
        "unassigned_sources": sorted(unassigned),
    }


def rights_summary(record: SourceRecord) -> dict:
    """Per-document rights/permission status (AUD-A1-16).

    Records what is actually known per artifact — the official public
    download page and the licence note — instead of one boilerplate string
    shared by every source. ``redistribution`` is the honest answer for
    NCTB curriculum documents: publicly downloadable, not granted in
    writing for redistribution; derived artifacts stay gitignored.
    """
    return {
        "public_download_url": record.source_url,
        "parent_page": record.parent_url,
        "license_notes": record.license_notes,
        "permission_status": "official-public-download",
        "redistribution": "not-granted-in-writing",
        "derived_artifacts": "gitignored (data/nctb/raw|extracted|normalized)",
    }


def _write_report(report_path: Path, summary: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    reports: dict[str, dict] = {}
    if report_path.exists():
        reports = json.loads(report_path.read_text(encoding="utf-8"))
    key = summary.pop("source_id")
    reports[key] = summary
    report_path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_chunks_jsonl(path: Path) -> list[RawChunk]:
    from dataclasses import fields

    chunks: list[RawChunk] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            data = json.loads(line)
            known = {f.name for f in fields(RawChunk)}
            chunks.append(RawChunk(**{k: v for k, v in data.items() if k in known}))
    return chunks


__all__ = [
    "ExtractionResult",
    "coverage_report",
    "load_chunks_jsonl",
    "load_manifest",
    "process_source",
    "prune_outputs",
    "rights_summary",
]
