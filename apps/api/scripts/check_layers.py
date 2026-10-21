#!/usr/bin/env python
"""Dependency rule + cycle enforcement (C-02), with an explicit rules table.

The audit (C-02 / AUD-CD-19) found the layered architecture of ADR-0001
("router -> service -> infrastructure") enforced by nothing but convention:
an AST scan showed zero import cycles *that day*, and no tool existed to keep
it that way. This checker is that tool. It is stdlib-only on purpose -- an
extra dependency for a 200-line AST walk would need its own justification --
and it is the primary gate; `import-linter` remains an acceptable alias once
the dev extra is extended (see `.audit/handoffs/pyproject-c2.md`).

Rules (all of them explicit in the tables below):

1. **Layers (``LAYERS``).** Every module of the package sits in a layer,
   lowest = most reusable. A module may import any module in its own layer or
   a *lower* one; importing a higher layer is a violation. Layers are matched
   by longest module prefix, so the small dependency-free "shared kernel"
   (config, schemas, the request-scoped trace context, ...) lives at layer 0
   even though some of it is filed under ``services/``.
2. **Named exceptions (``EXCEPTIONS``).** Every reverse edge that exists today
   is written down with the reason it is accepted. An exception is keyed by
   (importer prefix, imported prefix); it never blanket-approves a package.
3. **Transport is not a library.** ``bangla_gpt_api.routers`` may only be
   imported by ``routers``, ``initialize`` and ``main`` -- the composition
   surface. An application service importing a router is the classic
   cycle-in-waiting this rule exists for.
4. **Zero cycles, in two classes.** A cycle made of module-level imports is a
   load-order bug and is never allowed. A cycle whose every edge is
   function-local cannot fire at import time, so it is reported as a
   ``lazy-cycle`` violation unless the exact member set is registered in
   :data:`ALLOWED_LAZY_CYCLES` with a reason. Every component larger than one
   module is reported with its full member list either way.

Usage::

    python scripts/check_layers.py            # human report, exit 0/1
    python scripts/check_layers.py --json     # machine-readable report
    python scripts/check_layers.py --list     # print the rules table

Exit codes: 0 clean, 1 violation(s), 2 tooling/parse error.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

APP = Path(__file__).resolve().parents[1]  # apps/api
SRC = APP / "src"
PACKAGE = "bangla_gpt_api"

# --------------------------------------------------------------------------- #
# Rule tables (the "explicit rules table" C-02 asks for)
# --------------------------------------------------------------------------- #

#: module-prefix -> layer. Longest prefix wins. 0 is the shared kernel.
LAYERS: dict[str, int] = {
    # 0 -- shared kernel: dependency-free building blocks importable anywhere
    f"{PACKAGE}.config": 0,
    f"{PACKAGE}.logging_config": 0,
    f"{PACKAGE}.metrics": 0,
    f"{PACKAGE}.schemas": 0,
    f"{PACKAGE}.services.answer_structure": 0,
    f"{PACKAGE}.services.breached_passwords": 0,
    f"{PACKAGE}.services.context": 0,
    # the prompt-registry loader (A5-02): a stdlib-only file reader shared by
    # the kernel, the providers and the services, kept import-cycle-free by
    # design; its single upward edge (the AGE_RULE_SENTENCE constant) is in
    # EXCEPTIONS below. Filed under services/, so the longest-prefix fallback
    # would otherwise put it at layer 3 and break every layer-0 consumer.
    f"{PACKAGE}.services.prompt_registry": 0,
    f"{PACKAGE}.services.router": 0,
    f"{PACKAGE}.services.trace_meta": 0,
    f"{PACKAGE}.tracing": 0,
    # 1 -- domain vocabulary and persistence
    f"{PACKAGE}.curriculum": 1,
    f"{PACKAGE}.db": 1,
    f"{PACKAGE}.auth": 1,
    f"{PACKAGE}.security": 1,
    # 2 -- infrastructure adapters
    f"{PACKAGE}.caching": 2,
    f"{PACKAGE}.data": 2,
    f"{PACKAGE}.ingestion": 2,
    f"{PACKAGE}.nctb": 2,
    f"{PACKAGE}.providers": 2,
    f"{PACKAGE}.ratelimit": 2,
    f"{PACKAGE}.retrieval": 2,
    # safety screens text with the retrieval vocabulary (tokenize/light_stem),
    # so despite living in services/ it is an infrastructure-layer consumer.
    f"{PACKAGE}.services.safety": 2,
    # the malware-scan seam (A2-09) is a pure bytes-in/verdict-out adapter
    # consumed by the OCR adapter and the image contract: infrastructure
    # despite living in services/ (same shape as the safety note above).
    f"{PACKAGE}.services.malware_scan": 2,
    # 3 -- application layer
    f"{PACKAGE}.ai_jobs": 3,
    f"{PACKAGE}.jobs": 3,
    f"{PACKAGE}.services": 3,
    f"{PACKAGE}.evaluation": 3,
    # 4 -- composition surface
    f"{PACKAGE}.middleware": 4,
    f"{PACKAGE}.routers": 4,
    f"{PACKAGE}.initialize": 4,
    # 5 -- entrypoint
    f"{PACKAGE}.main": 5,
    # R4-wsC: `python -m bangla_gpt_api` / bgpt-api console script (D-12),
    # second thin entrypoint beside main.py, same downwards-only rule.
    f"{PACKAGE}.__main__": 5,
}

#: (importer prefix, imported prefix) -> why this reverse edge is accepted.
#: Keep this tiny: an entry here is a design decision, not a silence switch.
EXCEPTIONS: dict[tuple[str, str], str] = {
    (
        f"{PACKAGE}.services.prompt_registry",
        f"{PACKAGE}.services.safety",
    ): (
        "the registry substitutes {{age_rule}} from services.safety so the "
        "child-safety sentence keeps exactly one source; safety has no "
        "module-level internal imports, so this upward read is not a cycle -- "
        "it is the one documented edge of the shared-kernel loader"
    ),
    (
        f"{PACKAGE}.providers.mock",
        f"{PACKAGE}.services.generators",
    ): (
        "the deterministic mock provider renders the same generator payload "
        "formats as the real path, so dev/test fixtures cannot drift from the "
        "JSON contract the generators validate; read-only parsers, no DB access"
    ),
}

#: Modules allowed to import the transport layer (composition surface).
TRANSPORT_LAYER = f"{PACKAGE}.routers"
TRANSPORT_IMPORTERS = (
    f"{PACKAGE}.routers",
    f"{PACKAGE}.initialize",
    f"{PACKAGE}.main",
)

#: Import cycles made ONLY of function-local imports, keyed as
#: ``frozenset({module_a, module_b, ...})`` -> why it is accepted.
#:
#: Why this table exists at all: a cycle of *module-level* imports is a load
#: order bug (the interpreter can observe a half-initialised module) and is
#: never allowed. A cycle whose every edge is inside a function cannot fire at
#: import time -- each side is fully loaded before either function runs -- so
#: it is a coupling wart, not a bug. Those are still reported as violations
#: unless registered here with a reason, so nothing is silent.
ALLOWED_LAZY_CYCLES: dict[frozenset[str], str] = {
    frozenset({f"{PACKAGE}.logging_config", f"{PACKAGE}.tracing"}): (
        "the JSON log line needs the current OTel trace ids (tracing."
        "current_trace_ids) while the tracer needs the log redactor's key "
        "rules (logging_config.is_sensitive_key); both imports are inside "
        "functions, so neither module can be seen half-initialised. "
        "Removing it needs the redaction key rules extracted into a leaf "
        "module."
    ),
}


@dataclass(frozen=True)
class Violation:
    rule: str
    importer: str
    imported: str
    detail: str

    def render(self) -> str:
        return f"[{self.rule}] {self.importer} -> {self.imported}: {self.detail}"


# --------------------------------------------------------------------------- #
# Module graph
# --------------------------------------------------------------------------- #


def discover_modules(src: Path = SRC) -> dict[str, Path]:
    """Every module of the package: dotted name -> file."""
    root = src / PACKAGE
    modules: dict[str, Path] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def _split_import_from(module: str, is_package: bool, level: int, imported: str | None) -> str:
    """Resolve a (possibly relative) ``from`` target to a dotted name."""
    if not level:
        return imported or ""
    base = module.split(".")
    # ``from .x import y`` inside a module of package ``p`` targets ``p.x``;
    # inside ``p/__init__.py`` it targets ``p.x`` as well (level 1 == p).
    drop = level - 1 if not is_package else level
    base = base[: len(base) - drop] if drop else base
    if imported:
        base = [*base, *imported.split(".")]
    return ".".join(base)


def module_import_edges(
    module: str, path: Path, known: Iterable[str] | None = None
) -> dict[str, bool]:
    """Internal targets imported by one module, mapped to "is function-local".

    ``from package import submodule`` is resolved to the submodule when it
    exists, so layer checks see the real target. ``True`` means the import
    statement sits inside a function (this codebase places its deliberate lazy
    edges there), which is what separates a load-order cycle from a coupling
    wart -- see :data:`ALLOWED_LAZY_CYCLES`.
    """
    known_set = set(known) if known is not None else set()
    is_package = path.name == "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    lazy_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    lazy_nodes.add(id(inner))

    found: dict[str, bool] = {}
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets = [
                alias.name
                for alias in node.names
                if alias.name == PACKAGE or alias.name.startswith(f"{PACKAGE}.")
            ]
        elif isinstance(node, ast.ImportFrom):
            target = _split_import_from(module, is_package, node.level, node.module)
            if not (target == PACKAGE or target.startswith(f"{PACKAGE}.")):
                continue
            targets = [target]
            targets += [
                f"{target}.{alias.name}"
                for alias in node.names
                if f"{target}.{alias.name}" in known_set
            ]
        for target in targets:
            # The bare package name is a namespace, not a unit of behaviour.
            if target in (module, PACKAGE):
                continue
            # An edge is "lazy" only if every occurrence of it is function-local.
            found[target] = found.get(target, True) and id(node) in lazy_nodes
    return found


def module_imports(module: str, path: Path, known: Iterable[str] | None = None) -> set[str]:
    """Internal (``bangla_gpt_api.*``) targets imported by one module.

    Walks the whole tree, so function-local imports count: this codebase
    places its deliberate lazy edges inside functions, and a cycle through
    those is still reported (see :data:`ALLOWED_LAZY_CYCLES`).
    """
    return set(module_import_edges(module, path, known))


def build_graph(src: Path = SRC) -> dict[str, set[str]]:
    """Every internal import edge, module-level and function-local alike."""
    modules = discover_modules(src)
    known = set(modules)
    return {name: module_imports(name, path, known) for name, path in modules.items()}


def build_module_graph(src: Path = SRC) -> dict[str, set[str]]:
    """Only the module-level edges: the graph that decides import order."""
    modules = discover_modules(src)
    known = set(modules)
    return {
        name: {
            target for target, lazy in module_import_edges(name, path, known).items() if not lazy
        }
        for name, path in modules.items()
    }


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #


def layer_of(module: str, layers: dict[str, int] | None = None) -> int | None:
    """Longest-prefix layer for a module; None when unclassified.

    Unclassified is a *violation*, not a default: a new subpackage must be
    placed in the table deliberately instead of silently inheriting the
    weakest rule (the root ``__init__`` is the single namespace exception).
    """
    if module == PACKAGE:
        return 0
    table = LAYERS if layers is None else layers
    best: tuple[int, int] | None = None  # (prefix length, layer)
    for prefix, layer in table.items():
        matches = module == prefix or module.startswith(f"{prefix}.")
        if matches and (best is None or len(prefix) > best[0]):
            best = (len(prefix), layer)
    return None if best is None else best[1]


def _excepted(importer: str, imported: str) -> bool:
    for from_prefix, to_prefix in EXCEPTIONS:
        if (importer == from_prefix or importer.startswith(f"{from_prefix}.")) and (
            imported == to_prefix or imported.startswith(f"{to_prefix}.")
        ):
            return True
    return False


def check_layers(graph: dict[str, set[str]]) -> list[Violation]:
    violations: list[Violation] = []
    for importer, targets in sorted(graph.items()):
        importer_layer = layer_of(importer)
        if importer_layer is None:
            violations.append(
                Violation("unclassified", importer, "-", "module is not in the LAYERS table")
            )
            continue
        for imported in sorted(targets):
            imported_layer = layer_of(imported)
            if imported_layer is None:
                violations.append(
                    Violation("unclassified", importer, imported, "target not in the LAYERS table")
                )
                continue
            if _excepted(importer, imported):
                continue
            if imported_layer > importer_layer:
                violations.append(
                    Violation(
                        "layer",
                        importer,
                        imported,
                        f"layer {importer_layer} imports layer {imported_layer} "
                        "(ADR-0001: router -> service -> infrastructure)",
                    )
                )
    return violations


def check_transport(graph: dict[str, set[str]]) -> list[Violation]:
    violations: list[Violation] = []
    for importer, targets in sorted(graph.items()):
        if any(
            importer == allowed or importer.startswith(f"{allowed}.")
            for allowed in TRANSPORT_IMPORTERS
        ):
            continue
        for imported in sorted(targets):
            if imported == TRANSPORT_LAYER or imported.startswith(f"{TRANSPORT_LAYER}."):
                violations.append(
                    Violation(
                        "transport-import",
                        importer,
                        imported,
                        "only the composition surface (routers/, initialize/, main.py) "
                        "may import the transport layer",
                    )
                )
    return violations


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan SCCs; returns every component with more than one module."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal counter
        index[node] = low[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)
        for neighbour in sorted(graph.get(node, ())):
            if neighbour not in graph:  # import of a module outside the scan set
                continue
            if neighbour not in index:
                strongconnect(neighbour)
                low[node] = min(low[node], low[neighbour])
            elif neighbour in on_stack:
                low[node] = min(low[node], index[neighbour])
        if low[node] == index[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            components.append(component)

    for node in sorted(graph):
        if node not in index:
            strongconnect(node)
    return [sorted(c) for c in components if len(c) > 1]


def _cycle_violations(
    graph: dict[str, set[str]], module_graph: dict[str, set[str]]
) -> list[Violation]:
    """Cycles, split into the two classes the rule table distinguishes.

    * a component that is cyclic in the *module-level* graph is a load-order
      bug: hard violation, no exception possible;
    * a component that is cyclic only when function-local edges are counted is
      a coupling wart: still a violation, unless the exact member set is in
      :data:`ALLOWED_LAZY_CYCLES` with a reason.
    """
    strict = {frozenset(members) for members in find_cycles(module_graph)}
    violations: list[Violation] = []
    for members in find_cycles(graph):
        joined = " -> ".join(members)
        if frozenset(members) in strict:
            violations.append(
                Violation(
                    "cycle",
                    members[0],
                    members[-1],
                    f"module-level import cycle (load-order bug): {joined}",
                )
            )
        elif frozenset(members) not in ALLOWED_LAZY_CYCLES:
            violations.append(
                Violation(
                    "lazy-cycle",
                    members[0],
                    members[-1],
                    "function-local import cycle without a registered reason "
                    f"(add it to ALLOWED_LAZY_CYCLES, or remove the edge): {joined}",
                )
            )
    return violations


def all_violations(
    graph: dict[str, set[str]] | None = None, module_graph: dict[str, set[str]] | None = None
) -> list[Violation]:
    """Every violation of the rule tables, over the real tree by default.

    When a caller passes a synthetic ``graph`` without a ``module_graph``, the
    edges are treated as module-level: a synthetic cycle is then a hard one,
    which is what a caller building that graph by hand means by it.
    """
    if graph is None:
        full = build_graph()
        strict = build_module_graph() if module_graph is None else module_graph
    else:
        full = graph
        strict = graph if module_graph is None else module_graph
    return [*check_layers(full), *check_transport(full), *_cycle_violations(full, strict)]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _report(violations: list[Violation], graph: dict[str, set[str]], as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "modules": len(graph),
                    "edges": sum(len(t) for t in graph.values()),
                    "layers": LAYERS,
                    "exceptions": {f"{a} -> {b}": why for (a, b), why in EXCEPTIONS.items()},
                    "allowed_lazy_cycles": [" | ".join(sorted(c)) for c in ALLOWED_LAZY_CYCLES],
                    "violations": [v.__dict__ for v in violations],
                },
                indent=1,
                sort_keys=True,
            )
        )
    else:
        for violation in violations:
            print(violation.render())
        if not violations:
            print(
                f"[layers] ok -- {len(graph)} modules, "
                f"{sum(len(t) for t in graph.values())} internal imports, "
                "0 module-level cycles, "
                f"{len(ALLOWED_LAZY_CYCLES)} allowed function-local cycle(s), "
                f"{len(EXCEPTIONS)} named exception(s)"
            )
    return 1 if violations else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--list", action="store_true", help="print the rules table and exit")
    parser.add_argument("--src", type=Path, default=SRC, help="path to the import root")
    args = parser.parse_args(argv)

    if args.list:
        print("# layers (low -> high)")
        for prefix, layer in sorted(LAYERS.items(), key=lambda kv: (kv[1], kv[0])):
            print(f"{layer}  {prefix}")
        print("# named exceptions")
        for (importer, imported), why in EXCEPTIONS.items():
            print(f"{importer} -> {imported}: {why}")
        print("# allowed function-local cycles")
        for members, why in ALLOWED_LAZY_CYCLES.items():
            print(f"{' | '.join(sorted(members))}: {why}")
        return 0

    try:
        graph = build_graph(args.src)
        module_graph = build_module_graph(args.src)
    except SyntaxError as exc:  # a file that does not parse is a tooling failure
        print(f"ERROR: cannot parse {exc.filename}: {exc}", file=sys.stderr)
        return 2
    return _report(all_violations(graph, module_graph), graph, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
