#!/usr/bin/env python3
"""Reprint every third-party image reference pinned by digest in this repo.

The audit (F9) found the supply-chain pinning strong for Python (2,117
hashes) and weak everywhere else: compose services, both Dockerfiles and the
CI scanner image all used floating tags, so the bytes that ship could change
under a rebuild with no commit. Everything is digest-pinned now — and that
creates the opposite problem: digests never move, so they need a deliberate
refresh. This script is that refresh, in one deterministic step.

Usage:
    python scripts/update_image_digests.py            # print current digests
    python scripts/update_image_digests.py --write    # rewrite pinned files

It pulls each reference, reads the digest the registry served, and (with
--write) replaces the `@sha256:...` suffix on the exact pinned line. Dependabot
does not understand `name:tag@digest` pins, so this script is the update path
for them; run it, and commit the result with the version bump in the comment.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: (file, regex with a named `ref` group that matches `name:tag@sha256:...`)
PIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "docker-compose.yml",
        re.compile(
            r"(?P<ref>(?:redis:7-alpine|postgres:16|node:24-alpine|nginx:1\.27-alpine"
            r"|caddy:2-alpine|prom/prometheus:v2\.53\.0|grafana/grafana:11\.1\.0"
            r"|prom/alertmanager:v0\.28\.1)@sha256:[0-9a-f]{64})"
        ),
    ),
    (
        ".github/workflows/ci.yml",
        re.compile(r"(?P<ref>aquasec/trivy:0\.58\.0@sha256:[0-9a-f]{64})"),
    ),
    (
        ".github/workflows/release.yml",
        re.compile(r"(?P<ref>aquasec/trivy:0\.58\.0@sha256:[0-9a-f]{64})"),
    ),
    ("apps/web/Dockerfile", re.compile(r"(?P<ref>node:24-alpine@sha256:[0-9a-f]{64})")),
    ("apps/web/Dockerfile", re.compile(r"(?P<ref>nginx:1\.27-alpine@sha256:[0-9a-f]{64})")),
    ("deploy/postgres/Dockerfile", re.compile(r"(?P<ref>postgres:16@sha256:[0-9a-f]{64})")),
]


def current_digest(name_tag: str) -> str:
    subprocess.run(["docker", "pull", "-q", name_tag], check=True, capture_output=True)
    out = subprocess.run(
        ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", name_tag],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out.split("@", 1)[1]


def main() -> int:
    write = "--write" in sys.argv
    changed = 0
    seen: set[str] = set()
    for rel, pattern in PIN_PATTERNS:
        path = REPO / rel
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            ref = match.group("ref")
            name_tag, old_digest = ref.split("@", 1)
            if ref in seen:
                continue
            seen.add(ref)
            new_digest = current_digest(name_tag)
            status = "current" if new_digest == old_digest else "UPDATE"
            print(f"{rel}: {name_tag} {status} {old_digest[:19]}… -> {new_digest[:19]}…")
            if write and new_digest != old_digest:
                text = text.replace(f"{name_tag}@{old_digest}", f"{name_tag}@{new_digest}")
                changed += 1
        if write:
            path.write_text(text, encoding="utf-8", newline="\n")
    if write:
        print(f"rewrote {changed} image reference(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
