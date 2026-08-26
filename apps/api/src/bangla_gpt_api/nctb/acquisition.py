"""Respectful, idempotent downloader for officially linked NCTB PDFs.

Rules implemented (master prompt §8):
- fixed politeness delay between HTTP requests
- identifying User-Agent
- retry with exponential backoff, bounded
- content-type validation (application/pdf)
- sha256 hashing + size recording
- hash-based duplicate detection across artifacts
- resume capability: already-acquired artifacts are skipped via manifest
No CAPTCHA/auth/rate-limit bypass of any kind is implemented.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bangla_gpt_api.nctb.manifest import SourceRecord, append_record, load_manifest, make_record
from bangla_gpt_api.nctb.sources import NctbArtifact

USER_AGENT = "BanglaGptResearch/1.0 (+curriculum tutoring research; contact: repo issues)"
DEFAULT_DELAY_SECONDS = 2.0
MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0


class AcquisitionError(RuntimeError):
    pass


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_url(url: str, *, timeout: float = 60.0) -> tuple[bytes, str]:
    """GET a URL and return (body, content_type). Raises AcquisitionError."""
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise AcquisitionError(f"Refusing non-HTTP(S) URL: {url}")
    last_error: Exception | None = None
    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            # Scheme allowlisted above; official-source downloads only.
            with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
            return body, content_type
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
    raise AcquisitionError(f"Failed to fetch {url}: {last_error}") from last_error


def acquire_artifact(
    artifact: NctbArtifact,
    raw_dir: Path,
    manifest_path: Path,
    *,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    curriculum_year: str = "UNKNOWN",
    seen_hashes: dict[str, str] | None = None,
    fetcher=fetch_url,
) -> SourceRecord:
    """Acquire one artifact; skip cleanly when already acquired/duplicate.

    Returns the (possibly pre-existing) manifest record.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    existing = load_manifest(manifest_path)
    record = existing.get(artifact.source_id)
    target = raw_dir / f"{artifact.source_id}.pdf"

    if record is not None and record.source_status == "acquired" and target.exists():
        return record  # resume capability: nothing to do

    time.sleep(delay_seconds)
    try:
        body, content_type = fetcher(artifact.url)
    except AcquisitionError as exc:
        failed = make_record(
            artifact_source_id=artifact.source_id,
            url=artifact.url,
            parent_url=artifact.parent_page,
            content_hash="",
            file_name=target.name,
            file_type="application/pdf",
            file_size=0,
            level=artifact.level,
            subject_bn=artifact.subject_bn,
            curriculum_year=curriculum_year,
            status="failed",
            error=str(exc),
        )
        append_record(manifest_path, failed)
        return failed

    if "application/pdf" not in content_type.lower():
        failed = make_record(
            artifact_source_id=artifact.source_id,
            url=artifact.url,
            parent_url=artifact.parent_page,
            content_hash="",
            file_name=target.name,
            file_type=content_type or "unknown",
            file_size=len(body),
            level=artifact.level,
            subject_bn=artifact.subject_bn,
            curriculum_year=curriculum_year,
            status="failed",
            error=f"Unexpected content-type: {content_type!r}",
        )
        append_record(manifest_path, failed)
        return failed

    digest = hashlib.sha256(body).hexdigest()

    if seen_hashes is None:
        seen_hashes = {}
    if digest not in seen_hashes:
        # Rebuild from the manifest so duplicates are caught across runs.
        for prior in load_manifest(manifest_path).values():
            if prior.content_hash:
                seen_hashes.setdefault(prior.content_hash, prior.source_id)
    duplicate_of = seen_hashes.get(digest)

    if duplicate_of is not None:
        status = "skipped-duplicate"
        error = f"Identical content already acquired as {duplicate_of}"
        target.write_bytes(body)
    else:
        status = "acquired"
        error = None
        target.write_bytes(body)
        seen_hashes[digest] = artifact.source_id

    record = make_record(
        artifact_source_id=artifact.source_id,
        url=artifact.url,
        parent_url=artifact.parent_page,
        content_hash=digest,
        file_name=target.name,
        file_type="application/pdf",
        file_size=len(body),
        level=artifact.level,
        subject_bn=artifact.subject_bn,
        curriculum_year=curriculum_year,
        status=status,
        error=error,
    )
    append_record(manifest_path, record)
    return record


def acquire_many(
    artifacts: list[NctbArtifact],
    raw_dir: Path,
    manifest_path: Path,
    *,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    fetcher=fetch_url,
) -> list[SourceRecord]:
    seen_hashes: dict[str, str] = {}
    records: list[SourceRecord] = []
    for artifact in artifacts:
        year = "2012" if artifact.level == "secondary" else "UNKNOWN"
        records.append(
            acquire_artifact(
                artifact,
                raw_dir,
                manifest_path,
                delay_seconds=delay_seconds,
                curriculum_year=year,
                seen_hashes=seen_hashes,
                fetcher=fetcher,
            )
        )
    return records
