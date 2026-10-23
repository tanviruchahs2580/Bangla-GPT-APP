"""The error envelope is a contract: every HTTPException carries a code.

``docs/API.md`` documents ``{"detail": {"code", "message"}}`` as the error
shape, and the frontend branches on ``detail.code`` (``errors.ts`` maps
codes to localized copy; a bare string falls through to the generic
"something went wrong"). The repository drifted anyway: 84 raises still used
``detail="some english string"``, so the same operation could answer in two
shapes — ``/auth/login`` returned ``{"code": "bad_credentials"}`` while
``/auth/change-password`` returned a bare string — and every
localisation/metrics-on-code consumer silently misclassified those paths.

This test scans the source tree so the drift cannot come back: it fails on
any ``detail="..."`` / ``detail=f"..."`` inside an HTTPException context, and
on any ``detail={...}`` literal that lacks a ``code`` key. The remaining
``detail=`` uses in the tree are ``StatusComponent`` payload fields (the
``/status`` page), which are data, not errors — deliberately out of scope.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bangla_gpt_api"

#: HTTPException raises in these files may name a non-code detail only if the
#: exception is raised with a structured dict — asserted below via AST.
_ALLOWED_STRING_DETAIL_FILES: frozenset[str] = frozenset()


def _iter_http_exception_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "HTTPException":
            continue
        for kw in node.keywords:
            if kw.arg == "detail":
                yield node.lineno, kw.value


def test_no_http_exception_uses_a_bare_string_detail() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in _ALLOWED_STRING_DETAIL_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, value in _iter_http_exception_calls(tree):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                offenders.append(f"{rel}:{lineno}: detail={value.value!r}")
            elif isinstance(value, ast.JoinedStr):
                offenders.append(f"{rel}:{lineno}: detail=<f-string>")
    assert not offenders, (
        "HTTPException with a bare-string detail — the client cannot branch "
        "on it and errors.ts falls back to the generic copy. Use "
        'detail={"code": ..., "message": ...}:\n' + "\n".join(offenders)
    )


def test_coded_details_actually_carry_a_code_key() -> None:
    """A dict detail without "code" is only marginals better than a string."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, value in _iter_http_exception_calls(tree):
            if not isinstance(value, ast.Dict):
                continue
            keys = {k.value for k in value.keys if isinstance(k, ast.Constant)}
            if "code" not in keys:
                offenders.append(f"{rel}:{lineno}")
    assert not offenders, "HTTPException with a dict detail missing the 'code' key:\n" + "\n".join(
        offenders
    )
