"""AUD-B-18: the write-on-GET set is frozen and documented.

The audit found three GET handlers committing analytics/audit rows and one of
them was accepted by design rather than changed; the government export then
gained an audit write on purpose (AUD-B-06). All four are documented in
``SECURITY.md`` ("Four GET handlers write rows, by design").

A fifth one must be a decision, not an accident, so this test enumerates GET
handlers whose body commits and compares the set to that documented
allowlist. It mirrors the audit's AST scan; it does not run the handlers.

The scan walks the routers package *recursively* and keys a handler by its
path relative to ``routers/``: the school surface became a package (C-03), and
a non-recursive glob would have silently stopped covering two of the four
allowlisted handlers.
"""

import ast
from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[1] / "src" / "bangla_gpt_api" / "routers"

#: (module under routers/, handler, route) -- keep in sync with SECURITY.md.
DOCUMENTED_WRITE_ON_GET = {
    ("parent.py", "parent_child_report", "/parents/me/children/{student_id}/report"),
    ("school/_analytics.py", "school_analytics", "/school/analytics"),
    ("school/_admin.py", "admin_report_aggregate", "/admin/reports/aggregate"),
    ("users.py", "export_me", "/users/me/export"),
}


def _module_name(path: Path) -> str:
    return path.relative_to(ROUTERS).as_posix()


def _write_on_get_handlers() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in sorted(ROUTERS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not ast.unparse(decorator.func).endswith("router.get"):
                    continue
                route = ast.literal_eval(decorator.args[0]) if decorator.args else "?"
                commits = [
                    call
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call) and ast.unparse(call.func).endswith(".commit")
                ]
                if commits:
                    found.add((_module_name(path), node.name, str(route)))
    return found


def test_every_documented_handler_is_still_scanned() -> None:
    """Guard the guard: a rename must not silently drop a handler from the scan."""
    found = _write_on_get_handlers()
    for module, handler, _route in DOCUMENTED_WRITE_ON_GET:
        assert any(entry[0] == module and entry[1] == handler for entry in found), (
            f"{module}:{handler} is allowlisted but no longer found by the scan"
        )


def test_no_undocumented_write_on_get_handler() -> None:
    """A new side-effecting GET must be an explicit, documented decision.

    The assertion is one-directional on purpose: *adding* a write-on-GET
    handler is the defect class this guards (it is crawler-reachable and was
    never argued for), so it fails. Removing or renaming a documented handler
    is a legitimate refactor -- the docs then want updating, but the security
    property this test protects has not changed.
    """
    found = _write_on_get_handlers()
    undocumented = found - DOCUMENTED_WRITE_ON_GET
    assert not undocumented, (
        "new write-on-GET handler(s) without a documented decision: "
        f"{sorted(undocumented)}. Either make the handler POST/read-only or add "
        "it to SECURITY.md and DOCUMENTED_WRITE_ON_GET in the same change."
    )
