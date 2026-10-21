"""R3 / WS3 C-11: the persistence strategy is one strategy, pinned.

`docs/architecture.md` ("Deletion and retention strategy") states it: no soft
delete, explicit cascades, one retention sweep, opt-out flags are preferences.
These tests pin the claims that are checkable mechanically, so a partial
soft-delete implementation or a second sweeper cannot appear silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bangla_gpt_api"
DOC = Path(__file__).resolve().parents[3] / "docs" / "architecture.md"

SOFT_DELETE_NAMES = {"is_deleted", "deleted_at", "deleted", "trashed_at", "is_removed"}


def _model_columns() -> dict[str, set[str]]:
    """Column names declared per mapped class in the db/models package.

    The classes live in the package the former 978-line ``db/models.py`` was
    split into (C-03); every module of it is walked, so a soft-delete column
    cannot hide by moving to a sibling module.
    """
    out: dict[str, set[str]] = {}
    for path in sorted((SRC / "db" / "models").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            columns: set[str] = set()
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    columns.add(statement.target.id)
            out[node.name] = columns
    return out


def test_no_model_declares_a_soft_delete_column() -> None:
    offenders = {
        cls: sorted(SOFT_DELETE_NAMES & columns)
        for cls, columns in _model_columns().items()
        if SOFT_DELETE_NAMES & columns
    }
    assert not offenders, (
        "a soft-delete column appeared; the strategy in docs/architecture.md "
        f"('Deletion and retention strategy') says there is none: {offenders}. "
        "Either delete hard like every other model or update the strategy, the "
        "retention sweep and every query that would need the filter."
    )


def test_the_retention_sweep_is_a_single_policy_point() -> None:
    """Only retention.py deletes by age; no second sweeper grew next to it."""
    sweepers = []
    documented_erasers = {
        "routers/users.py",  # documented erasure cascade
        "services/users_erase.py",
    }
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SRC).as_posix()
        if path.name == "retention.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "retention" in text and "delete()" in text and "services" not in str(path):
            sweepers.append(rel)
        # A module deleting rows by an age predicate is a second policy point.
        if (
            ".delete()" in text
            and ("retention_days" in text or "days=" in text)
            and rel not in documented_erasers
        ):
            sweepers.append(rel)
    assert not sweepers, (
        f"a second age-based sweeper appeared outside services/retention.py: {sweepers}"
    )


def test_the_documented_strategy_still_exists() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert "### Deletion and retention strategy (C-11)" in doc
    assert "No soft delete anywhere" in doc
    assert "services/retention.py" in doc
    assert "Opt-out flags are preferences, not tombstones" in doc


def test_retention_module_remains_the_documented_sweeper() -> None:
    tree = ast.parse((SRC / "services" / "retention.py").read_text(encoding="utf-8"))
    funcs = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {"retention_report", "run_retention_sweep"} <= funcs, sorted(funcs)
