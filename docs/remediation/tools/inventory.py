from __future__ import annotations

import ast
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".css",
    ".scss", ".html", ".sh", ".ps1", ".go", ".rs", ".java", ".kt", ".sql",
}
MANIFEST_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pyproject.toml",
    "constraints.txt", "requirements.txt", "requirements-dev.txt", "requirements.in",
    "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock", "composer.json", "composer.lock", "Gemfile",
    "Gemfile.lock", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock",
}


def tracked_paths() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / part.decode("utf-8", "surrogateescape") for part in raw.split(b"\0") if part]


def migration_heads(paths: list[Path]) -> list[str]:
    revisions: dict[str, str | tuple[str, ...] | None] = {}
    for path in paths:
        if path.parent.name != "versions" or path.parent.parent.name != "alembic":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            continue
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
                value = node.value
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    try:
                        values[target.id] = ast.literal_eval(value)
                    except (ValueError, TypeError):
                        pass
        revision = values.get("revision")
        down_revision = values.get("down_revision")
        if isinstance(revision, str):
            if down_revision is None or isinstance(down_revision, str):
                revisions[revision] = down_revision
            elif isinstance(down_revision, (tuple, list)) and all(isinstance(x, str) for x in down_revision):
                revisions[revision] = tuple(down_revision)
    parents = {
        parent
        for down in revisions.values()
        for parent in ((down,) if isinstance(down, str) else down or ())
    }
    return sorted(set(revisions) - parents)


def main() -> None:
    paths = tracked_paths()
    line_counts: Counter[str] = Counter()
    source_files: list[tuple[int, str]] = []
    nfc_changes: list[tuple[int, str]] = []
    manifest_paths: list[str] = []
    workflows: list[str] = []
    container_files: list[str] = []
    tracked_count = 0

    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        tracked_count += 1
        name = path.name.lower()
        if name in MANIFEST_NAMES or name.startswith("requirements") or name.startswith("constraints"):
            manifest_paths.append(rel)
        if rel.startswith(".github/workflows/"):
            workflows.append(rel)
        if name == "dockerfile" or name.startswith("dockerfile.") or name in {
            "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
        }:
            container_files.append(rel)
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = len(text.splitlines())
        line_counts[path.suffix.lower()] += lines
        source_files.append((lines, rel))
        occurrences = sum(
            unicodedata.normalize("NFC", match.group()) != match.group()
            for match in __import__("re").finditer(r"[\u0980-\u09ff\u0964\u0965\u200c\u200d]+", text)
        )
        if occurrences:
            nfc_changes.append((occurrences, rel))

    print(f"tracked_files={tracked_count}")
    print("source_lines_by_extension:")
    for suffix, lines in sorted(line_counts.items()):
        print(f"  {suffix}: {lines}")
    print("top_20_source_files_by_lines:")
    for lines, rel in sorted(source_files, reverse=True)[:20]:
        print(f"  {lines}\t{rel}")
    print("dependency_manifests_and_lockfiles:")
    for rel in sorted(manifest_paths):
        print(f"  {rel}")
    print("ci_workflows:")
    for rel in sorted(workflows):
        print(f"  {rel}")
    print("dockerfiles_and_compose_files:")
    for rel in sorted(container_files):
        print(f"  {rel}")
    print("alembic_heads_from_tracked_revision_graph=" + ",".join(migration_heads(paths)))
    print("baseline_non_nfc_bengali_runs_by_file:")
    if nfc_changes:
        for count, rel in sorted(nfc_changes, key=lambda item: item[1]):
            print(f"  {count}\t{rel}")
    else:
        print("  none")


if __name__ == "__main__":
    main()
