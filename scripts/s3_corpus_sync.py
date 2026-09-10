"""S5.7 -- Sync the NCTB corpus between S3-compatible object storage and a
local directory (the corpus root the API indexes at startup).

The deployed web/API artifact stores question-paper PDFs by RENDERING them
from database rows on request (services/qp_pdf.py), so PDFs need no separate
backup target -- a DB restore restores the PDFs. The one bulk file asset is
the NCTB corpus, so this tool covers the "S3-compatible storage for
PDFs/corpus" requirement: keep the corpus in MinIO/R2/S3 and materialise it
locally before (re)indexing.

boto3 is an OPTIONAL runtime dependency: it is imported lazily inside the
sync function so the API process never requires it. Point S3_ENDPOINT_URL at
any S3-compatible service (MinIO, Cloudflare R2, ...).

Usage (cron/entrypoint before api start):
    export S3_BUCKET=bgpt-corpus S3_PREFIX=nctb/
    export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
    python scripts/s3_corpus_sync.py --dest /data/corpus [--endpoint http://minio:9000]

Keys that would escape --dest (absolute or containing '..') are refused, so
a hostile/misconfigured bucket cannot write outside the corpus root.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def sync_corpus(
    *,
    bucket: str,
    prefix: str,
    dest: Path,
    endpoint: str | None = None,
    region: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    client=None,  # injectable for tests (boto3 S3 client)
) -> int:
    if client is None:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "S3 corpus sync requires boto3 (pip install boto3); "
                "it is intentionally not an API dependency."
            ) from exc
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region or "auto",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key.removeprefix(prefix)
            rel = rel.lstrip("/")
            if not rel or rel.endswith("/"):
                continue  # directory marker / prefix object
            candidate = (dest / rel).resolve()
            if not candidate.is_relative_to(dest.resolve()):
                print(f"REFUSED unsafe key: {key!r}", file=sys.stderr)
                continue
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with open(candidate, "wb") as fh:
                client.download_fileobj(bucket, key, fh)
            written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", required=True, help="local corpus directory to populate")
    ap.add_argument("--bucket", default=os.environ.get("S3_BUCKET", ""))
    ap.add_argument("--prefix", default=os.environ.get("S3_PREFIX", "nctb/"))
    ap.add_argument("--endpoint", default=os.environ.get("S3_ENDPOINT_URL"))
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION"))
    args = ap.parse_args()
    if not args.bucket:
        print("FAIL: S3_BUCKET (or --bucket) is required", file=sys.stderr)
        return 2
    n = sync_corpus(
        bucket=args.bucket,
        prefix=args.prefix,
        dest=Path(args.dest),
        endpoint=args.endpoint,
        region=args.region,
        access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
        secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
    print(f"synced {n} objects from s3://{args.bucket}/{args.prefix} into {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
