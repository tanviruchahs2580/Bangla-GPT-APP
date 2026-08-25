"""Manifest records for acquired NCTB artifacts (JSONL, append-safe).

The manifest is the provenance ledger required by the master prompt:
source URL, parent page, retrieval timestamp, content hash and edition
metadata exactly as published. It never stores derived guesses.
"""

from __future__ import annotations

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
