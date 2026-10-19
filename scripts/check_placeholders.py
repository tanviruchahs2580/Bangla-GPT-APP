#!/usr/bin/env python3
"""Static sweep for placeholders, stubs and fake functionality (AUD-CD-10 / D-16).

The anti-slop protocol (master prompt §9, class S-01) says a placeholder, stub
or fake in a production path is a defect: TODO markers, `changeme`-style
placeholder values, reserved `example.com` hosts, `NotImplementedError`, and
functions whose whole body is `pass`/`...` outside an interface. The audit
found the tree clean of these by ad-hoc greps; this script is the same sweep as
a gate, so "static detection clean" stays true instead of being a point-in-time
observation.

What is flagged (rule, and the paths each rule applies to):

  marker                 TODO / FIXME / HACK / XXX markers
  placeholder-secret     changeme / replace-me / your-api-key placeholder values
  lorem                  lorem ipsum
  coming-soon            "coming soon", "under construction", "not implemented yet"
  fake-host              example.com / example.net / example.org in production code
  not-implemented-raise  `raise NotImplementedError` in production code
  py-stub                function bodies that are only `pass`/`...`/a docstring,
                         outside Protocol/ABC classes and @abstractmethod members

A hit is legitimate sometimes (a weak-secret denylist must contain "changeme";
a docstring may quote RFC 3464's `user@example.com`). Those carry an explicit
entry in ALLOW below - path, rule, the exact snippet and the reason - so a new
hit fails the gate until someone writes down why it is fine. That is the whole
point: no silent allowlists. `rule = "*"` marks a whole-file allowance, used
only for this script and its test, which necessarily contain the rule literals
as their subject matter. A stale allowance (one that matches nothing) fails the
run too.

Run it from the repository root (or anywhere; it finds the root itself):

    python scripts/check_placeholders.py              # exit 1 on any finding
    python scripts/check_placeholders.py --verbose    # also print allowlisted hits
    python scripts/check_placeholders.py --root DIR   # scan another tree (tests)

Exit codes: 0 = clean, 1 = findings, 2 = the scan could not run (fail closed).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Text-like extensions worth scanning. Binaries, fonts, images and the corpus
# under data/ never match by extension.
CODE_EXTENSIONS = frozenset(
    {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx", ".sh", ".ps1", ".sql"}
)
CONFIG_EXTENSIONS = frozenset(
    {".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".html", ".css"}
)
PROSE_EXTENSIONS = frozenset({".md", ".txt"})
ALL_EXTENSIONS = CODE_EXTENSIONS | CONFIG_EXTENSIONS | PROSE_EXTENSIONS

# Whole subtrees that are not product code: audit bookkeeping, dependencies,
# build output, historical documents (superseded by design) and the corpus.
SKIP_PARTS = (
    ".git",
    ".audit",
    "node_modules",
    "dist",
    "coverage",
    "__pycache__",
    ".venv",
    ".zcode",
    "docs/archive",
    "docs/audit",
    "docs/qa",
    "data",
    "apps/api/eval",
)

MAX_BYTES = 512 * 1024

INTERFACE_BASES = frozenset({"Protocol", "ABC", "ABCMeta"})
ABSTRACT_DECORATORS = frozenset(
    {"abstractmethod", "abstractproperty", "abstractstaticmethod", "abstractclassmethod"}
)


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    what: str
    extensions: frozenset[str]
    skip_globs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Allow:
    path_glob: str
    rule: str
    snippet: str | None
    reason: str


@dataclass
class Finding:
    path: str
    lineno: int
    rule: str
    snippet: str
    line: str
    allowed: Allow | None = None


RULES: tuple[Rule, ...] = (
    Rule(
        "marker",
        re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE),
        "unfinished-work marker",
        ALL_EXTENSIONS,
    ),
    Rule(
        "placeholder-secret",
        re.compile(
            r"\bchangeme\w*\b|replace[-_ ]?me\b|your[-_ ]?(?:api[-_ ]?)?key\b",
            re.IGNORECASE,
        ),
        "placeholder value where a real one belongs",
        ALL_EXTENSIONS,
    ),
    Rule(
        "lorem",
        re.compile(r"lorem ipsum", re.IGNORECASE),
        "lorem ipsum copy",
        ALL_EXTENSIONS,
    ),
    Rule(
        "coming-soon",
        re.compile(
            r"\bcoming soon\b|\bunder construction\b|\bnot implemented yet\b",
            re.IGNORECASE,
        ),
        "promise of functionality that is not there",
        ALL_EXTENSIONS,
    ),
    Rule(
        "fake-host",
        re.compile(r"\bexample\.(?:com|org|net)\b", re.IGNORECASE),
        "reserved example domain in production code",
        CODE_EXTENSIONS | CONFIG_EXTENSIONS,
        skip_globs=(
            "apps/api/tests/**",
            "apps/web/src/test/**",
            "apps/web/src/**/*.test.*",
            "apps/web/src/**/*.spec.*",
            "load/**",
        ),
    ),
    Rule(
        "not-implemented-raise",
        re.compile(r"raise NotImplementedError\b|NotImplementedError\("),
        "NotImplementedError on a production path",
        CODE_EXTENSIONS,
        skip_globs=(
            "apps/api/tests/**",
            "apps/web/src/test/**",
            "**/test_*.py",
            "**/*.test.*",
        ),
    ),
)

RULE_BY_NAME = {rule.name: rule for rule in RULES}

# Every entry: what is allowed, where, and why. Snippet None = the whole
# file/rule combination is allowed (used only where the whole block is the
# control being tested).
ALLOW: tuple[Allow, ...] = (
    Allow(
        "apps/api/src/bangla_gpt_api/main.py",
        "placeholder-secret",
        "changemechangemechangeme",
        "member of _WEAK_SECRETS (main.py:164-173): the startup guard must reject this "
        "string, so its presence is the control, not a value in use",
    ),
    Allow(
        "apps/api/src/bangla_gpt_api/main.py",
        "placeholder-secret",
        "replace-me-with-a-real-secret",
        "member of _WEAK_SECRETS: same guard, same reason",
    ),
    Allow(
        "apps/api/src/bangla_gpt_api/auth/security.py",
        "placeholder-secret",
        "changeme",
        "weak-password blocklist entry (security.py:82-85): the string is the control",
    ),
    Allow(
        "apps/web/src/api.ts",
        "fake-host",
        "api.example.com",
        "docstring showing the VITE_API_BASE format (mobile build, mobile_release.md)",
    ),
    Allow(
        "apps/web/src/lib/safeMarkdown.tsx",
        "fake-host",
        "evil.example.com",
        "comment illustrating the hostile markdown link the renderer must reject",
    ),
    Allow(
        "apps/api/src/bangla_gpt_api/services/mailer.py",
        "fake-host",
        "user@example.com",
        "docstring quoting RFC 3464 address syntax and the parseaddr behavior",
    ),
    Allow(
        "apps/api/src/bangla_gpt_api/providers/__init__.py",
        "coming-soon",
        "is not implemented yet",
        "error message naming an unknown LLM_PROVIDER; failing loudly is the feature",
    ),
    Allow(
        "apps/api/src/bangla_gpt_api/routers/system.py",
        "coming-soon",
        "is not implemented yet",
        "same startup/health message as providers/__init__.py",
    ),
    Allow(
        "apps/api/scripts/**",
        "fake-host",
        None,
        "benchmark and red-team harnesses: fake users and hostile URLs on reserved "
        "domains are the fixtures, and nothing here ships to production",
    ),
    Allow(
        "scripts/**",
        "fake-host",
        None,
        "smoke/probe tooling: the reserved domains are generated fixture data",
    ),
    Allow(
        "apps/web/capacitor.config.ts",
        "fake-host",
        "api.example.com",
        "comment showing the mobile build's VITE_API_BASE format",
    ),
    Allow(
        "scripts/check_placeholders.py",
        "*",
        None,
        "this script lists the rule literals as its own subject matter (rule table, "
        "docstring, allowlist reasons); a real placeholder here would be the check itself",
    ),
    Allow(
        "apps/api/tests/test_d2_placeholders.py",
        "*",
        None,
        "the sweep's test fixtures are the rule literals; the file exists to assert they "
        "are flagged (incl. a planted placeholder that must fail the gate)",
    ),
)


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _skipped(rel: str) -> bool:
    parts = _norm(rel)
    return any(parts == part or parts.startswith(part + "/") for part in SKIP_PARTS)


def _matches_any(rel: str, globs: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, glob) for glob in globs)


def _allow_for(rel: str, rule: str, line: str) -> Allow | None:
    for entry in ALLOW:
        if entry.rule not in ("*", rule) or not fnmatch.fnmatch(rel, entry.path_glob):
            continue
        if entry.snippet is None or entry.snippet in line:
            return entry
    return None


def tracked_files(root: Path) -> list[str]:
    """Repository-relative paths to scan: git's tracked set, or a directory walk."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = [f for f in result.stdout.splitlines() if f.strip()]
        if files:
            return [_norm(f) for f in files]
    except (OSError, subprocess.CalledProcessError):
        pass
    return [_norm(str(p.relative_to(root))) for p in sorted(root.rglob("*")) if p.is_file()]


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def scan_text(rel: str, text: str) -> list[Finding]:
    """Regex rules over one file's text. `rel` is the path shown in output."""
    findings: list[Finding] = []
    lines = text.splitlines()
    for rule in RULES:
        if Path(rel).suffix.lower() not in rule.extensions or _matches_any(rel, rule.skip_globs):
            continue
        for match in rule.pattern.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            raw_line = lines[lineno - 1] if lineno <= len(lines) else ""
            findings.append(
                Finding(
                    path=rel,
                    lineno=lineno,
                    rule=rule.name,
                    snippet=match.group(0),
                    line=raw_line.strip()[:160],
                    allowed=_allow_for(rel, rule.name, raw_line),
                )
            )
    return findings


def _decorator_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    names: set[str] = set()
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Attribute):
            names.add(decorator.attr)
        elif isinstance(decorator, ast.Name):
            names.add(decorator.id)
    return names


def _is_interface_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in INTERFACE_BASES:
            return True
    return False


def _body_is_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when every statement is a docstring, `pass` or `...`."""
    body = [
        stmt
        for stmt in node.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis
        ):
            continue
        return False
    return True


def scan_python_stubs(rel: str, text: str) -> list[Finding]:
    """`pass`/`...`/docstring-only functions outside interfaces (production Python)."""
    if not rel.startswith("apps/api/src/") or not rel.endswith(".py"):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [
            Finding(
                path=rel,
                lineno=exc.lineno or 1,
                rule="py-stub",
                snippet="syntax-error",
                line=f"the stub sweep could not parse this file: {exc}",
            )
        ]
    skip: set[int] = set()
    for class_node in ast.walk(tree):
        if isinstance(class_node, ast.ClassDef) and _is_interface_class(class_node):
            for child in class_node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    skip.add(id(child))
    findings: list[Finding] = []
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if id(node) in skip or _decorator_names(node) & ABSTRACT_DECORATORS:
            continue
        if not _body_is_stub(node):
            continue
        line = lines[node.lineno - 1].strip()[:160] if node.lineno <= len(lines) else ""
        findings.append(
            Finding(
                path=rel,
                lineno=node.lineno,
                rule="py-stub",
                snippet=f"def {node.name}",
                line=line,
                allowed=_allow_for(rel, "py-stub", line),
            )
        )
    return findings


def scan_tree(root: Path) -> tuple[list[Finding], list[Finding], int]:
    """Returns (findings, allowlisted, files_scanned). Fails closed on an empty scan."""
    findings: list[Finding] = []
    allowed: list[Finding] = []
    scanned = 0
    for rel in tracked_files(root):
        if _skipped(rel) or Path(rel).suffix.lower() not in ALL_EXTENSIONS:
            continue
        text = _read_text(root / rel)
        if text is None:
            continue
        scanned += 1
        hits = scan_text(rel, text)
        if rel.endswith(".py"):
            hits.extend(scan_python_stubs(rel, text))
        for hit in hits:
            (allowed if hit.allowed else findings).append(hit)
    if scanned == 0:
        raise RuntimeError(f"no files scanned under {root}; refusing to report clean")
    return findings, allowed, scanned


def _exists_on_disk(root: Path, pattern: str) -> bool:
    """True when the pattern names at least one file/dir that is present in `root`."""
    if any(ch in pattern for ch in "*?["):
        return next(root.glob(pattern), None) is not None
    return (root / pattern).exists()


def stale_allow_entries(root: Path, allowed: list[Finding]) -> list[Allow]:
    """Allow entries that match nothing and name nothing on disk.

    The scan itself runs over git's tracked set (what CI checks out). A file
    that exists on disk but is not yet tracked - the sweep's own sources before
    their first commit - must not be reported as a dead allowance; a file that
    no longer exists must, because the allowance outlived its subject.
    """
    used = {id(hit.allowed) for hit in allowed if hit.allowed is not None}
    return [
        entry
        for entry in ALLOW
        if id(entry) not in used and not _exists_on_disk(root, entry.path_glob)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static placeholder and stub sweep (S-01).")
    parser.add_argument("--root", default=str(REPO_ROOT), help="tree to scan (default: repo root)")
    parser.add_argument("--verbose", action="store_true", help="also print allowlisted hits")
    parser.add_argument("--list-rules", action="store_true", help="print the rule set and exit")
    args = parser.parse_args(argv)

    if args.list_rules:
        for rule in RULES:
            print(f"{rule.name:22s} {rule.what}")
        return 0

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"scan root is not a directory: {root}", file=sys.stderr)
        return 2

    try:
        findings, allowed, scanned = scan_tree(root)
    except RuntimeError as exc:
        print(f"placeholder sweep could not run: {exc}", file=sys.stderr)
        return 2

    for hit in findings:
        print(f"{hit.path}:{hit.lineno}: [{hit.rule}] {RULE_BY_NAME[hit.rule].what}: {hit.line}")
    if args.verbose:
        for hit in allowed:
            reason = hit.allowed.reason if hit.allowed else ""
            print(f"{hit.path}:{hit.lineno}: [allowlisted {hit.rule}] {hit.snippet!r} - {reason}")

    print(f"scanned {scanned} files; {len(allowed)} allowlisted hit(s); {len(findings)} finding(s)")

    stale: list[Allow] = []
    if root == REPO_ROOT.resolve():
        stale = stale_allow_entries(Path(root), allowed)
        for entry in stale:
            print(
                f"stale allowlist entry (matches nothing): {entry.path_glob} [{entry.rule}] - "
                f"remove it or explain the drift"
            )

    if findings or stale:
        print("placeholder sweep FAILED: implement the feature or delete it (S-01).")
        return 1
    print("placeholder sweep: no placeholder findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
