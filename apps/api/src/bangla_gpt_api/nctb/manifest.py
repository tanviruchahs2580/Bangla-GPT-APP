"""Manifest records for acquired NCTB artifacts (JSONL, append-safe).

The manifest is the provenance ledger required by the master prompt:
source URL, parent page, retrieval timestamp, content hash and edition
metadata exactly as published. It never stores derived guesses.

``corpus_manifest.json`` (see :func:`write_corpus_manifest_record`) is the
derived-artifact counterpart: it pins the tool fingerprint that produced the
chunks, the raw-source hashes they were built from, and the digests of the
tracked reports, so a committed report can be tied to the build that made it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class SourceRecord:
    source_id: str
    source_url: str
    parent_url: str
    retrieved_at: str  # ISO-8601 UTC
    content_hash: str  # sha256 hex of the raw file
    file_name: str
    file_type: str
    file_size: int
    level: str  # secondary | hsc
    subject_bn: str
    book: str  # official link title (subject); refined post-extraction if verified
    curriculum_year: str  # "2012" for the secondary page edition heading, else UNKNOWN
    edition: str  # as published on the listing page, else UNKNOWN
    language: str = "bn"
    source_status: str = "acquired"  # acquired | failed | skipped-duplicate
    license_notes: str = (
        "Official NCTB public download; copyright NCTB/Government of Bangladesh. "
        "Use restricted to curriculum-grounded tutoring research/product."
    )
    processing_version: str = "v1"
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> SourceRecord:
        data = json.loads(line)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def load_manifest(path: Path) -> dict[str, SourceRecord]:
    """Load manifest keyed by source_id; last record wins."""
    records: dict[str, SourceRecord] = {}
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = SourceRecord.from_json(line)
        records[record.source_id] = record
    return records


def append_record(path: Path, record: SourceRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.to_json() + "\n")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def make_record(
    *,
    artifact_source_id: str,
    url: str,
    parent_url: str,
    content_hash: str,
    file_name: str,
    file_type: str,
    file_size: int,
    level: str,
    subject_bn: str,
    curriculum_year: str,
    status: str,
    error: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        source_id=artifact_source_id,
        source_url=url,
        parent_url=parent_url,
        retrieved_at=now_iso(),
        content_hash=content_hash,
        file_name=file_name,
        file_type=file_type,
        file_size=file_size,
        level=level,
        subject_bn=subject_bn,
        book=subject_bn,
        curriculum_year=curriculum_year,
        edition=("প্রকাশকাল ২০১২" if level == "secondary" else "UNKNOWN"),
        source_status=status,
        error=error,
    )


# --- Derived-artifact manifest (corpus_manifest.json) ----------------------

#: Tracked file that pins the derived-artifact build (not the source ledger).
CORPUS_MANIFEST_NAME = "corpus_manifest.json"
CORPUS_MANIFEST_VERSION = 1

#: Modules that turn raw PDFs into chunk artifacts and index entries. Their
#: content hashes are the manifest's "tool version": editing any of them
#: invalidates a committed manifest until the artifacts are rebuilt, which is
#: exactly the drift this file exists to surface. Provenance plumbing
#: (acquisition, this module) stays outside the set so a helper added there
#: does not force a corpus rebuild.
_FINGERPRINTED_MODULES = (
    "nctb/bijoy.py",
    "nctb/chunking.py",
    "nctb/corpus.py",
    "nctb/extract.py",
    "nctb/normalize.py",
    "data/nctb_loader.py",
)

#: Edition statement the manifest records. The secondary listing page prints
#: "প্রকাশকাল -২০১২"; the HSC listing prints no year, so the HSC edition stays
#: UNKNOWN rather than borrowing the secondary one.
EDITION_SECONDARY = "প্রকাশকাল ২০১২"
EDITION_HSC = "UNKNOWN"


def sha256_file(path: Path) -> str:
    """Hex sha256 of a file, read in blocks (corpus files run to megabytes)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_hex(data: str | bytes) -> str:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()


def pipeline_code_fingerprint() -> str:
    """``sha256:<hex>`` over the ordered pipeline module contents."""
    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for relative in _FINGERPRINTED_MODULES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(package_root / relative).encode("ascii"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def read_json(path: Path) -> dict:
    payload: dict = json.loads(path.read_text(encoding="utf-8"))
    return payload


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def corpus_manifest_path(corpus_root: Path) -> Path:
    return corpus_root / "manifests" / CORPUS_MANIFEST_NAME


def verify_corpus_manifest(
    corpus_root: Path,
    *,
    index_chunks: int | None = None,
    check_code_fingerprint: bool = True,
    check_files: bool = True,
) -> tuple[dict | None, list[str]]:
    """Compare a corpus directory against its tracked manifest.

    Returns ``(manifest, problems)``; an absent manifest is reported as one
    problem so callers can decide whether that is fatal (the CLI check) or a
    loud warning (boot, where an untracked corpus directory still has to
    serve). Checks, in order: manifest shape, the engineered tool fingerprint,
    every declared chunk file's digest (``check_files=False`` skips the file
    digests when the caller only has the tracked metadata, e.g. CI without the
    corpus), the chunk totals, and -- when the caller built an index -- the
    served index size.
    """
    path = corpus_manifest_path(corpus_root)
    if not path.exists():
        return None, [f"no corpus manifest at {path}"]
    manifest = read_json(path)
    problems: list[str] = []
    if manifest.get("manifest_version") != CORPUS_MANIFEST_VERSION:
        problems.append(
            f"manifest_version {manifest.get('manifest_version')!r} != {CORPUS_MANIFEST_VERSION}"
        )
    if not manifest.get("sources"):
        problems.append("manifest lists no sources")
    pipeline = manifest.get("pipeline") or {}
    fingerprint = pipeline.get("code_fingerprint")
    if not fingerprint:
        problems.append("manifest records no pipeline code fingerprint")
    elif check_code_fingerprint:
        current = pipeline_code_fingerprint()
        if fingerprint != current:
            problems.append(
                f"pipeline code fingerprint {fingerprint} != current {current}; "
                "the corpus was not built by the code in this tree"
            )
    total_chunks = 0
    for source in manifest.get("sources", []):
        source_id = source.get("source_id", "<unnamed>")
        declared_chunks = source.get("chunks")
        if isinstance(declared_chunks, int):
            total_chunks += declared_chunks
        normalized = corpus_root / "normalized" / f"{source_id}.chunks.jsonl"
        declared_digest = source.get("normalized_sha256")
        if normalized.exists():
            if declared_digest and sha256_file(normalized) != declared_digest:
                problems.append(f"{source_id}: chunk file digest differs from the manifest")
        elif declared_chunks:
            problems.append(
                f"{source_id}: manifest declares {declared_chunks} chunks, file missing"
            )
    totals = manifest.get("totals") or {}
    if totals.get("chunks") is not None and int(totals["chunks"]) != total_chunks:
        problems.append(
            f"totals.chunks {totals.get('chunks')} != sum of per-source chunks {total_chunks}"
        )
    derived = manifest.get("derived") or {}
    if (
        index_chunks is not None
        and derived.get("index_chunks") is not None
        and int(derived["index_chunks"]) != int(index_chunks)
    ):
        problems.append(
            f"served index has {index_chunks} chunks, manifest records {derived['index_chunks']}"
        )
    return manifest, problems
