"""End-to-end corpus construction: extract → QC → chunk → JSONL artifacts.

Outputs (data/nctb/):
    extracted/<source_id>.pages.json per-page raw text
    normalized/<source_id>.chunks.jsonl retrieval chunks with provenance
    quality_report.json per-source extraction QC metrics
    manifests/corpus_manifest.json derived-artifact manifest (source hashes,
        tool fingerprint, report digests; finalized by evaluate_nctb_retrieval)

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
from bangla_gpt_api.nctb.manifest import (
    CORPUS_MANIFEST_NAME,
    CORPUS_MANIFEST_VERSION,
    EDITION_HSC,
    EDITION_SECONDARY,
    SourceRecord,
    load_manifest,
    pipeline_code_fingerprint,
    sha256_file,
    sha256_hex,
    write_json,
)

#: Reserved key under which corpus-level (cross-source) duplicate statistics
#: live inside quality_report.json. Per-source rows describe one book; they
#: cannot see a passage reprinted across books.
CROSS_SOURCE_KEY = "_cross_source"


def _extractor_version() -> str:
    """pypdf version that produced the extracts, recorded for reproducibility.

    ``total_chars_on_usable`` moved between pypdf versions (F-080: 108827
    committed vs 108822 re-measured), so a report without the extractor
    version cannot be diffed across environments.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"pypdf-{version('pypdf')}"
    except PackageNotFoundError:  # pragma: no cover - pypdf is a hard dependency
        return "pypdf-UNKNOWN"


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
        "extractor": _extractor_version(),
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
        newline="\n",
    )

    qc = qc_pages(result.pages)
    chunks = chunk_pages(result.pages, source_id=source_id)
    # RAG-001: dedupe identical passages (reprints/overlapping pages) and
    # stamp version + build time so staleness is answerable per artifact.
    chunks, duplicates_removed = dedupe_chunks(chunks)
    chunks_with_chapter = sum(1 for chunk in chunks if chunk.chapter)

    out_normalized.mkdir(parents=True, exist_ok=True)
    # newline="\n": chunk files are hashed into the manifest and compared
    # across machines, so the platform's line ending must not leak in.
    with (out_normalized / f"{source_id}.chunks.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    summary.update(qc)
    summary["chunks"] = len(chunks)
    summary["duplicates_removed"] = duplicates_removed
    # Chapter coverage is a first-class QC number, not a footnote: two of the
    # nine acquired documents print numbered sections instead of chapter
    # headings, so their chapter metadata is legitimately absent and any
    # chapter-scoped metric over them would be blind (F-081).
    summary["chunks_with_chapter"] = chunks_with_chapter
    summary["chapter_coverage"] = round(chunks_with_chapter / len(chunks), 4) if chunks else 0.0
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
    report_path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def content_hash(text: str) -> str:
    """Normalized-text hash used for duplicate detection at build and load."""
    return sha256_hex(" ".join(text.split()))


def cross_source_duplicates(
    normalized_dir: Path,
) -> tuple[dict, dict[str, dict[str, int]]]:
    """Corpus-level duplicate statistics over the built chunk files.

    Returns ``(summary, per_source)``. ``summary`` counts texts by how many
    sources carry them; ``per_source`` counts, for each source, how many of
    its chunks share a text with at least one other source. The per-source
    ``duplicates_removed`` field cannot see this: dedupe runs per book, so a
    preamble reprinted in every volume stayed in the report as zero removed
    while occupying one index entry per book (F-012).
    """
    texts_by_source: dict[str, list[str]] = {}
    sources_by_text: dict[str, set[str]] = {}
    chunks_by_text: dict[str, int] = {}
    for path in sorted(normalized_dir.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        digests: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest = content_hash(json.loads(line)["text"])
            digests.append(digest)
            sources_by_text.setdefault(digest, set()).add(source_id)
            chunks_by_text[digest] = chunks_by_text.get(digest, 0) + 1
        texts_by_source[source_id] = digests

    per_source: dict[str, dict[str, int]] = {}
    for source_id, digests in texts_by_source.items():
        shared = [d for d in digests if len(sources_by_text[d]) > 1]
        per_source[source_id] = {
            "chunks": len(digests),
            "shared_texts": len(set(shared)),
            "shared_chunks": len(shared),
        }

    cross_groups = {d: sorted(s) for d, s in sources_by_text.items() if len(s) > 1}
    total_chunks = sum(len(d) for d in texts_by_source.values())
    summary = {
        "sources": len(texts_by_source),
        "total_chunks": total_chunks,
        "unique_texts": len(chunks_by_text),
        "duplicate_chunks": total_chunks - len(chunks_by_text),
        "duplicate_texts": sum(1 for n in chunks_by_text.values() if n > 1),
        "cross_source_texts": len(cross_groups),
        "cross_source_duplicate_chunks": sum(len(s) - 1 for s in cross_groups.values()),
        "cross_source_sources": sorted({s for sources in cross_groups.values() for s in sources}),
        "per_source": per_source,
    }
    return summary, per_source


def record_cross_source_report(report_path: Path, normalized_dir: Path) -> dict:
    """Write the cross-source duplicate statistics and stamp the chunk rows.

    Two artifacts carry the fact: ``_cross_source`` in the quality report (what
    was duplicated, per source and as a whole) and ``shared_sources`` on every
    chunk row whose text another source also carries. The stamp is what keeps
    the *attribution* intact when the index build collapses the duplicates into
    one entry per class level: the surviving row can name every book the
    passage is printed in, and the loader logs the merged list.
    """
    summary, per_source = cross_source_duplicates(normalized_dir)
    for path in sorted(normalized_dir.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        digests = [content_hash(row["text"]) for row in rows]
        # Which other sources carry each digest: read the sibling chunk files,
        # not just this one, because that is exactly what the per-file report
        # could not see.
        other_sources_by_digest: dict[str, set[str]] = {}
        for other in sorted(normalized_dir.glob("*.chunks.jsonl")):
            other_id = other.name.removesuffix(".chunks.jsonl")
            if other_id == source_id:
                continue
            for line in other.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    digest = content_hash(json.loads(line)["text"])
                    other_sources_by_digest.setdefault(digest, set()).add(other_id)
        changed = False
        for row, digest in zip(rows, digests, strict=True):
            shared = sorted(other_sources_by_digest.get(digest, set()))
            if shared and row.get("shared_sources") != shared:
                row["shared_sources"] = shared
                changed = True
        if changed:
            # newline="\n": chunk files are hashed into the manifest.
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    reports = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    for source_id, stats in per_source.items():
        if source_id in reports:
            reports[source_id]["shared_text_chunks_with_other_sources"] = stats["shared_chunks"]
    reports[CROSS_SOURCE_KEY] = summary
    write_json(report_path, reports)
    return summary


def build_corpus_manifest(
    data_dir: Path,
    records: dict[str, SourceRecord],
    *,
    report_path: Path,
    extracted_dir: Path,
    normalized_dir: Path,
) -> dict:
    """Assemble the derived-artifact manifest for the built corpus.

    ``derived`` digests are filled in by the evaluation step
    (``scripts/evaluate_nctb_retrieval.py``) once ``retrieval_eval.json``
    exists; until then they are null and ``check_corpus_manifest.py`` fails,
    which is the intended signal that the reports were not regenerated
    together with the corpus.
    """
    reports = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    cross = reports.get(CROSS_SOURCE_KEY, {})
    sources: list[dict] = []
    totals = {
        "sources": 0,
        "processed_sources": 0,
        "chunks": 0,
        "chunks_with_chapter": 0,
        "characters_on_usable": 0,
    }
    for source_id in sorted(records):
        record = records[source_id]
        report = reports.get(source_id, {})
        extracted_path = extracted_dir / f"{source_id}.pages.json"
        normalized_path = normalized_dir / f"{source_id}.chunks.jsonl"
        entry = {
            "source_id": source_id,
            "file_name": record.file_name,
            "content_hash": record.content_hash,
            "file_size": record.file_size,
            "source_status": record.source_status,
            "level": record.level,
            "subject_bn": record.subject_bn,
            "curriculum_year": record.curriculum_year,
            "edition": record.edition,
            "processing_version": record.processing_version,
            "retrieved_at": record.retrieved_at,
            "total_pages": report.get("total_pages"),
            "usable_pages": report.get("usable_pages"),
            "bangla_char_ratio_on_usable": report.get("bangla_char_ratio_on_usable"),
            "chunks": report.get("chunks"),
            "duplicates_removed": report.get("duplicates_removed"),
            "chunks_with_chapter": report.get("chunks_with_chapter"),
            "chapter_coverage": report.get("chapter_coverage"),
            "extractor": report.get("extractor"),
            "extracted_sha256": sha256_file(extracted_path) if extracted_path.exists() else None,
            "normalized_sha256": sha256_file(normalized_path) if normalized_path.exists() else None,
        }
        sources.append(entry)
        totals["sources"] += 1
        if report.get("chunks") is not None:
            totals["processed_sources"] += 1
        totals["chunks"] += int(report.get("chunks") or 0)
        totals["chunks_with_chapter"] += int(report.get("chunks_with_chapter") or 0)
        totals["characters_on_usable"] += int(report.get("total_chars_on_usable") or 0)

    manifest_path = data_dir / "manifests" / CORPUS_MANIFEST_NAME
    previous: dict = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest = {
        "manifest_version": CORPUS_MANIFEST_VERSION,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "edition": {
            "secondary": EDITION_SECONDARY,
            "hsc": EDITION_HSC,
            "curriculum_year_secondary": "2012",
            "curriculum_year_hsc": "UNKNOWN",
            "source_listings": {
                "secondary": "https://nctb.gov.bd/pages/files/6922db5b933eb65569e09a2c",
                "hsc": "https://nctb.gov.bd/pages/files/6922dbc6933eb65569e0c702",
            },
        },
        "pipeline": {
            "processing_version": "v1",
            "code_fingerprint": pipeline_code_fingerprint(),
            "extractor": _extractor_version(),
            "python": _python_version(),
            "chunker": _chunker_fingerprint(),
        },
        "acquisition_manifest": {
            "path": "manifests/acquisition_manifest.jsonl",
            "sha256": sha256_file(data_dir / "manifests" / "acquisition_manifest.jsonl")
            if (data_dir / "manifests" / "acquisition_manifest.jsonl").exists()
            else None,
        },
        "sources": sources,
        "totals": totals,
        "cross_source": cross,
        "derived": previous.get("derived")
        or {
            "quality_report_sha256": None,
            "retrieval_eval_sha256": None,
            "index_chunks": None,
            "index_id_hash": None,
            "embedder": None,
        },
    }
    if report_path.exists():
        manifest["derived"]["quality_report_sha256"] = sha256_file(report_path)
    write_json(manifest_path, manifest)
    return manifest


def _python_version() -> str:
    import platform

    return f"{platform.python_version()}-{platform.python_implementation()}"


def _chunker_fingerprint() -> dict:
    """Chunker/normalizer parameters the manifest pins alongside the code."""
    from bangla_gpt_api.nctb import chunking

    return {
        "unit": chunking.SIZE_UNIT,
        "target": chunking.TARGET_TOKENS,
        "min": chunking.MIN_TOKENS,
        "max": chunking.MAX_TOKENS,
        "normalizer": chunking.NORMALIZER_NAME,
    }


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
    "CROSS_SOURCE_KEY",
    "ExtractionResult",
    "build_corpus_manifest",
    "content_hash",
    "cross_source_duplicates",
    "load_chunks_jsonl",
    "load_manifest",
    "process_source",
    "record_cross_source_report",
]
