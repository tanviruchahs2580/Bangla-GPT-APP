#!/usr/bin/env python3
"""Check the relative links in every tracked Markdown file (audit finding J-04).

A documentation tree whose internal links are broken is worse than a small one:
the reader follows a path the author never walked. This guard walks it for
every `[...](target)` and every `[id]: target` definition in the tracked
Markdown, from the directory of the file that contains the link, and fails on
targets that do not exist.

Scope and deliberate limits
---------------------------

* **Tracked files only** (`git ls-files`). An untracked scratch file next to a
  document must not turn the guard red on one machine and green in CI; the
  same reasoning as `apps/api/scripts/check_doc_paths.py`.
* **Relative targets only.** `http:`, `https:`, `mailto:`, `tel:`, `data:`,
  protocol-relative `//host/...` and root-absolute `/...` links are outside
  the repository's control and are *listed*, not fetched. A repository-wide
  network check is flaky on purpose-verbose days and CI has no business
  depending on third-party uptime; `--external` does a single HEAD request per
  unique URL for an operator who asked for it, and reports any that do not
  answer 2xx/3xx (some sites reject HEAD; the flag says so in the output).
* **Anchors** (`file.md#section`) are validated only with `--anchors`, because
  the exact slug rules are GitHub's, not markdown's, and a checker that is
  subtly wrong about them gets deleted. If `--anchors` is given, a heading is
  matched by GitHub's algorithm (lowercase, punctuation dropped, spaces to
  hyphens, inline code/emphasis stripped, duplicate headings suffixed `-1`,
  `-2`, ...).
* Directories are accepted as targets (they are valid on GitHub when the
  directory has a README) but only when the directory exists.

Exit status is 0 when every checked link resolves, 1 otherwise. The output
ends with a summary that always states how many links were checked and how
many external URLs were left to the owner, so a green run still tells the
truth about what was not looked at.

Usage:

    python scripts/check_links.py [paths...] [--anchors] [--external]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Fenced code blocks are not links; neither are inline code spans. The scan
# strips both before looking for links (READMEs here show commands in fences).
FENCE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})")
# [text](target "title") / ![alt](target) / [text](<target with spaces>)
INLINE_RE = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^()\s]+)(?:\s+['\"][^'\"]*['\"])?\s*\)")
# [id]: target "title"
DEF_RE = re.compile(r"^[ \t]{0,3}\[([^\]^]+)\]:\s*(\S+)(?:\s+.+)?$")

EXTERNAL_SCHEMES = ("http:", "https:", "mailto:", "tel:", "data:", "ftp:")


def is_external(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith(EXTERNAL_SCHEMES) or lowered.startswith("//")


def is_repo_absolute(target: str) -> bool:
    """`/docs/x.md` resolves against the repository root on GitHub."""
    return target.startswith("/") and not target.startswith("//")


def strip_fences(text: str) -> list[tuple[int, str]]:
    """Yield (line_number, line) outside fenced code blocks, 1-based."""
    out: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        marker = FENCE_RE.match(line)
        if marker:
            token = marker.group(2)[0]
            if fence is None:
                fence = token
            elif token == fence:
                fence = None
            continue
        if fence is None:
            out.append((number, line))
    return out


def strip_inline_code(line: str) -> str:
    return re.sub(r"`[^`]*`", "", line)


def extract_targets(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, raw in strip_fences(text):
        line = strip_inline_code(raw)
        for match in INLINE_RE.finditer(line):
            target = match.group(1)
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            found.append((number, target.strip()))
        definition = DEF_RE.match(line)
        if definition:
            found.append((number, definition.group(2).strip()))
    return found


def github_slug(heading: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", heading)  # inline code keeps its text
    text = re.sub(r"\*\*?([^*]*)\*\*?", r"\1", text)  # bold/italic delimiters
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their text
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)  # drop punctuation
    return re.sub(r"\s+", "-", text)


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for _number, line in strip_fences(path.read_text(encoding="utf-8", errors="replace")):
        heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if not heading:
            continue
        slug = github_slug(heading.group(2))
        if not slug:
            continue
        seen = counts.get(slug, 0)
        counts[slug] = seen + 1
        anchors.add(slug if seen == 0 else f"{slug}-{seen}")
    return anchors


def tracked_markdown(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z", "*.md"],
            check=True,
            capture_output=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(REPO.rglob("*.md"))
    return [REPO / name for name in out.decode().split("\0") if name]


def check_target(source: Path, target: str, anchors: bool) -> str | None:
    """Return a failure description, or None when the link resolves."""
    if not target or target.startswith("#"):
        if anchors and target.startswith("#"):
            return check_anchor(source, "", target[1:])
        return None
    if is_external(target) or target.startswith("//"):
        return None
    path_part, _, anchor = target.partition("#")
    path_part = urllib.parse.unquote(path_part)
    if not path_part:
        return None
    if is_repo_absolute(path_part):
        destination = REPO / path_part.lstrip("/")
    else:
        destination = (source.parent / path_part).resolve()
    if not destination.exists():
        return f"missing target: {target}"
    if anchors and anchor and destination.is_file() and destination.suffix == ".md":
        return check_anchor(destination, target, anchor)
    return None


def check_anchor(destination: Path, target: str, anchor: str) -> str | None:
    if anchor not in markdown_anchors(destination):
        return f"missing anchor: {target}"
    return None


def head_status(url: str, timeout: float = 10.0) -> str:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "bgpt-link-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return f"{response.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - reported verbatim
        return f"error: {type(exc).__name__}: {exc}"


def display(path: Path) -> str:
    """Relative to the repository when possible, absolute otherwise (the test
    suite passes temporary trees outside the repository)."""
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="Markdown files to check (default: all tracked)")
    parser.add_argument("--anchors", action="store_true", help="also validate #anchors")
    parser.add_argument("--external", action="store_true", help="HEAD-check external URLs")
    args = parser.parse_args(argv)

    files = tracked_markdown(args.paths)
    broken: list[str] = []
    external: dict[str, list[str]] = {}
    checked = 0
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, target in extract_targets(text):
            if is_external(target):
                external.setdefault(target, []).append(f"{display(path)}:{number}")
                continue
            checked += 1
            failure = check_target(path, target, args.anchors)
            if failure:
                broken.append(f"{display(path)}:{number}: {failure}")

    for line in broken:
        print(line)
    print(f"\nrelative links checked: {checked} in {len(files)} files")
    if broken:
        print(f"broken: {len(broken)}")

    if args.external:
        print(f"\nexternal URLs (HEAD-checked, {len(external)} unique):")
        failures = 0
        for url in sorted(external):
            status = head_status(url)
            ok = status.startswith(("2", "3"))
            failures += 0 if ok else 1
            print(f"  {status:>22}  {url}")
            if not ok:
                print(f"      referenced at: {', '.join(external[url][:3])}")
        print("note: some hosts reject HEAD requests; a non-2xx/3xx line needs a manual look")
        if failures:
            print(f"external URLs not answering OK: {failures}")
    else:
        print(
            f"external URLs not checked (offline default): {len(external)} unique; "
            "run with --external to HEAD-check them"
        )
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
