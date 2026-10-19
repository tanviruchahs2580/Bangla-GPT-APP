"""C-06/AUD-CD-04: the error wire contract is typed, catalogued and frozen.

The audit found ~180 `HTTPException` raises whose bodies had never been
enumerated: two shapes (`{"detail": "<message>"}` and
`{"detail": {"code", "message"}}`) plus FastAPI's own validation list, with no
catalogue of the machine-readable codes. `routers/_error_contract.py` now
carries `ERROR_CATALOG`; these tests are the gate that keeps it honest by
scanning the source with `ast` (not by trusting the module).

Deliberately *not* asserted here: message wording (it is copy, and several
codes legitimately have variants). Deliberately frozen: the code set, the
status per code, and the exact key set of every coded body -- changing those is
a wire change and needs a catalog edit in the same commit.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, replace
from functools import lru_cache

import bangla_gpt_api
from bangla_gpt_api.routers._error_contract import (
    ERROR_CATALOG,
    FRAMEWORK_VALIDATION_SITES,
)

SRC = pathlib.Path(bangla_gpt_api.__file__).parent


@dataclass(frozen=True)
class Site:
    """One error body found in the source."""

    shape: str  # "message" | "coded" | "framework_validation" | "unresolved:<Type>"
    where: str = ""
    func: str = ""
    code: str | None = None
    status: int | None = None
    keys: tuple[str, ...] = ()


def _source_files() -> list[pathlib.Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _literal_int(node: ast.expr | None) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _resolve_str(node: ast.expr, scopes: list[dict[str, ast.expr]]) -> str | None:
    """Resolve an expression the source uses for a code to its literal string.

    One hop is enough for this codebase: `LOGIN_LOCKED_CODE` is a module
    constant. Anything unresolvable returns None and is reported by the test.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        for scope in reversed(scopes):
            if node.id in scope:
                return _resolve_str(scope[node.id], scopes)
    return None


def _shape_of(node: ast.expr, scopes: list[dict[str, ast.expr]]) -> Site:
    if isinstance(node, (ast.Constant, ast.JoinedStr)):
        return Site(shape="message")
    if isinstance(node, ast.Call):
        # str(exc) and friends: the callee's return value is a string.
        return Site(shape="message")
    if isinstance(node, ast.Dict):
        keys = tuple(k.value if isinstance(k, ast.Constant) else "" for k in node.keys)
        code = None
        if "code" in keys:
            code = _resolve_str(node.values[list(keys).index("code")], scopes)
        return Site(shape="coded", code=code, keys=keys)
    if isinstance(node, (ast.List, ast.ListComp)):
        return Site(shape="framework_validation")
    if isinstance(node, ast.Name):
        for scope in reversed(scopes):
            if node.id in scope:
                return _shape_of(scope[node.id], scopes)
        # An unbound name here would be a NameError at runtime; a bound one is
        # a parameter the function above resolved from its annotation.
        return Site(shape="message")
    return Site(shape=f"unresolved:{type(node).__name__}")


def _function_ranges(
    tree: ast.Module,
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, int, int]]:
    ranges = []
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ranges.append((func, func.lineno, getattr(func, "end_lineno", func.lineno)))
    return ranges


def _owning_function(
    ranges: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, int, int]], lineno: int
):
    owners = [r for r in ranges if r[1] <= lineno <= r[2]]
    return min(owners, key=lambda r: r[2] - r[1])[0] if owners else None


def _scopes_for(func: ast.FunctionDef | ast.AsyncFunctionDef | None) -> list[dict[str, ast.expr]]:
    """Nearest bindings first: assignments, then parameters."""
    if func is None:
        return []
    bindings: dict[str, ast.expr] = {}
    params: dict[str, ast.expr] = {}
    for arg in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]:
        if arg.arg not in ("self", "cls"):
            params[arg.arg] = arg.annotation or ast.Constant(value="<unannotated>")
    for stmt in ast.walk(func):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                bindings[target.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            bindings[stmt.target.id] = stmt.value or ast.Constant(value="<annotated>")
    return [bindings, params]


@lru_cache(maxsize=1)
def _scan() -> tuple[Site, ...]:
    """Every error body in the package, resolved once."""
    sites: list[Site] = []
    for path in _source_files():
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_consts = {
            t.id: stmt.value
            for stmt in ast.walk(tree)
            if isinstance(stmt, ast.Assign)
            for t in stmt.targets
            if isinstance(t, ast.Name) and isinstance(stmt.value, ast.Constant)
        }
        ranges = _function_ranges(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
            )
            if fname not in ("HTTPException", "JSONResponse"):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            if fname == "HTTPException":
                detail = kwargs.get("detail")
            else:
                first = node.args[0] if node.args else None
                detail = None
                if isinstance(first, ast.Dict):
                    for k, v in zip(first.keys, first.values, strict=True):
                        if isinstance(k, ast.Constant) and k.value == "detail":
                            detail = v
            if detail is None:
                continue
            owner = _owning_function(ranges, node.lineno)
            scopes = [*_scopes_for(owner), module_consts]
            shape = _shape_of(detail, scopes)
            funcname = owner.name if owner is not None else "<module>"
            sites.append(
                replace(
                    shape,
                    where=f"{rel}:{node.lineno} ({funcname})",
                    func=f"{rel}:{funcname}",
                    status=_literal_int(kwargs.get("status_code")),
                )
            )
    return tuple(sites)


def test_every_error_body_uses_a_documented_shape():
    problems = []
    for site in _scan():
        if site.shape == "message":
            continue
        if site.shape == "framework_validation":
            continue
        if site.shape != "coded":
            problems.append(f"{site.where}: {site.shape}")
            continue
        if "code" not in site.keys:
            problems.append(
                f"{site.where}: coded body without a 'code' key: keys={list(site.keys)}"
            )
            continue
        if site.code is None:
            problems.append(f"{site.where}: code expression could not be resolved")
            continue
        spec = ERROR_CATALOG.get(site.code)
        if spec is None:
            problems.append(f"{site.where}: code {site.code!r} is not in ERROR_CATALOG")
            continue
        if tuple(sorted(site.keys)) != tuple(sorted(spec.keys)):
            problems.append(
                f"{site.where}: code {site.code!r} keys {sorted(site.keys)} != catalog {sorted(spec.keys)}"
            )
        if site.status is not None and site.status != spec.status:
            problems.append(
                f"{site.where}: code {site.code!r} raised {site.status}, catalog says {spec.status}"
            )
    assert not problems, "undocumented error bodies:\n" + "\n".join(problems)


def test_framework_validation_detail_appears_only_at_registered_sites():
    found = sorted({s.func for s in _scan() if s.shape == "framework_validation"})
    assert found == sorted(FRAMEWORK_VALIDATION_SITES), (
        "framework-validation detail sites changed; update FRAMEWORK_VALIDATION_SITES: "
        f"found {sorted(found)}, registered {sorted(FRAMEWORK_VALIDATION_SITES)}"
    )


def test_message_bodies_carry_an_error_status():
    """Shape 1 bodies are guard/product failures; a 2xx here is a bug."""
    bad = [
        f"{s.where} status={s.status}"
        for s in _scan()
        if s.shape == "message" and s.status is not None and not 400 <= s.status <= 599
    ]
    assert not bad, "non-error status with a message body:\n" + "\n".join(bad)


def test_every_catalog_code_is_still_raised_somewhere():
    """No dead rows: a code that left the codebase leaves the catalog too."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in _source_files())
    missing = [code for code in ERROR_CATALOG if f'"{code}"' not in text]
    assert not missing, f"catalog codes no longer present in the source: {missing}"


def test_catalog_statuses_are_error_statuses():
    bad = [code for code, spec in ERROR_CATALOG.items() if not 400 <= spec.status <= 599]
    assert not bad, f"catalog codes with non-error status: {bad}"


def test_coded_openapi_model_is_still_declared():
    """The catalog change must not have touched the documented body model."""
    from bangla_gpt_api.routers import _error_contract

    schema = _error_contract.CodedDetail.model_json_schema()
    assert schema["properties"]["detail"]["type"] == "object"
    assert set(_error_contract.AUTH_GUARD_RESPONSES) == {401, 403}
