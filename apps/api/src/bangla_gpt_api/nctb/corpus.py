"""End-to-end corpus construction: extract → QC → chunk → JSONL artifacts.

Outputs (data/nctb/):
    extracted/<source_id>.pages.json     per-page raw text
    normalized/<source_id>.chunks.jsonl  retrieval chunks with provenance
    quality_report.json                  per-source extraction QC metrics

Only pages whose text passes the corruption heuristics are chunked;
everything is reported, nothing is silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from bangla_gpt_api.nctb.chunking import RawChunk, chunk_pages, dedupe_chunks
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
    }
    if not pdf_path.exists():
        summary["error"] = "raw file missing"
        _write_report(report_path, summary)
        return summary

    result = extract_pdf(pdf_path, max_pages=max_pages)
    if not result.ok:
        summary["error"] = result.error
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
    chunks = chunk_pages(result.pages, source_id=source_id)
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
    summary["content_version"] = f"{record.processing_version}:{record.content_hash[:12]}"
    summary["built_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _write_report(report_path, summary)
    return summary


def _write_report(report_path: Path, summary: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    reports: dict[str, dict] = {}
    if report_path.exists():
        reports = json.loads(report_path.read_text(encoding="utf-8"))
    key = summary.pop("source_id")
    reports[key] = summary
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")


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
    "load_chunks_jsonl",
    "load_manifest",
    "process_source",
]
