"""T-11: generate the first-pass route classification from the routers.

Reads every router module's AST: for each @router.<method> decorator, records
path, operation function name, and the dependency aliases used in the handler
signature (CurrentUser, TeacherOrAdminUser, ParentUser, AdminUser,
SchoolStaffUser, optional auth, public). Emits JSON to stdout for the
classification file; a human (this task) reviews and corrects before it is
checked in. Stdlib only.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[3] / "apps/api/src/bangla_gpt_api/routers"
SKIP = {"deps.py", "__init__.py", "_error_contract.py"}

METHODS = {"get", "post", "put", "patch", "delete"}

SIG_ALIASES = {
    "CurrentUser": "authenticated",
    "TeacherOrAdminUser": "role-restricted:teacher,admin,school_admin",
    "ParentUser": "role-restricted:parent",
    "AdminUser": "role-restricted:admin",
    "SchoolStaffUser": "role-restricted:teacher,school_admin,admin",
    # require_ai_budget wraps TeacherOrAdminUser + the per-user AI budget cap
    "AIGenerationUser": "role-restricted:teacher,admin,school_admin",
    "OptionalCurrentUser": "optional-auth",
}

out = []
for mod in sorted(ROUTERS.glob("*.py")):
    if mod.name in SKIP:
        continue
    tree = ast.parse(mod.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in METHODS:
                continue
            path = ast.literal_eval(dec.args[0]) if dec.args else "?"
            params = []
            for arg in node.args.args:
                ann = arg.annotation
                name = ast.unparse(ann) if ann is not None else ""
                # unwrap Annotated[...] -> first arg is the type alias
                if name.startswith("Annotated"):
                    name = name.split("[", 1)[1].split(",", 1)[0].strip()
                params.append((arg.arg, name))
            deps = sorted({SIG_ALIASES[p[1]] for p in params if p[1] in SIG_ALIASES})
            ids = [p[0] for p in params if p[0].endswith("_id") and p[0] != "school_id"]
            out.append(
                {
                    "path": path,
                    "method": dec.func.attr.upper(),
                    "function": f"{mod.name}:{node.name}",
                    "auth": deps or ["unclassified"],
                    "owned_params": ids,
                }
            )

out.sort(key=lambda r: (r["path"], r["method"]))
print(json.dumps({"operations": out, "count": len(out)}, indent=1))
