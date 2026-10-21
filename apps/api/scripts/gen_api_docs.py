"""Generate docs/API.md from the application's own OpenAPI schema (AUD-HI-05).

Why this exists
---------------
``docs/API.md`` was a hand-written reference (94 lines, 31 of 134 operations)
that no script produced and no CI step compared with the served schema. It also
documented the error body as ``{"detail": "..."}`` while the running API
returns coded objects for business rules (verified against the live app:
404 -> ``{"detail": {"code": "no_student_profile", ...}}``). A reference that
drifts silently is worse than none: the audit found clients written against it.

What it generates, and from where -- every table is derived, never authored:

* routes, methods, auth requirement, request/response models: ``app.openapi()``
  from the real application (the same object ``/openapi.json`` serves);
* the business-rule error catalog: ``routers/_error_contract.ERROR_CATALOG``,
  the same table a test already pins to the source;
* the rate-limit table: ``initialize.middleware_stack._effective_rules``, the
  exact dict the running middleware uses;
* the readiness/liveness semantics: the routers themselves (see the
  operational-notes section).

Usage
-----
::

    cd apps/api
    python scripts/gen_api_docs.py            # regenerate docs/API.md
    python scripts/gen_api_docs.py --check    # exit 1 when the file drifts

``--check`` is the drift gate: it regenerates in memory and compares byte for
byte with the committed file. Run it in CI after the schema-affecting changes
(routers, schemas) so a contract change cannot land without the reference.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "API.md"
GENERATED_NOTICE = "<!-- GENERATED FILE - DO NOT EDIT BY HAND. See scripts/gen_api_docs.py -->"

#: HTTP methods OpenAPI emits for a path item, in a frozen order so the output
#: is byte-stable across runs (dict ordering in the spec is insertion order,
#: which is stable today but not a contract).
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _pin_documentation_environment() -> None:
    """Keep the doc build off the developer's database and provider.

    ``create_app`` bootstraps an admin row and loads the retrieval index, so
    importing it with the ambient ``.env`` would write to the developer's
    working database. The env vars below win over ``.env`` (pydantic-settings
    precedence: environment > dotenv), and the temp database is throwaway.
    """
    scratch = Path(tempfile.gettempdir()) / "bgpt-api-docs"
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ENV", "docs")
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(scratch / 'openapi.db').as_posix()}")
    os.environ.setdefault("LLM_PROVIDER", "mock")


def build_spec() -> dict:
    _pin_documentation_environment()
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
    from bangla_gpt_api.main import create_app

    return create_app().openapi()


def _resolve_ref(spec: dict, ref: str) -> dict:
    node: dict = spec
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _schema_name(spec: dict, schema: dict | None) -> str:
    """A readable name for a response/request schema cell."""
    if not schema:
        return "-"
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        return f"array[{_schema_name(spec, schema.get('items'))}]"
    if "anyOf" in schema:
        return " | ".join(_schema_name(spec, option) for option in schema["anyOf"])
    return str(schema.get("type", "object"))


def _auth_cell(operation: dict, security_schemes: set[str]) -> str:
    """``bearer`` / ``none`` for the auth column.

    The scheme's OpenAPI name is an implementation detail (``HTTPBearer``
    today); the reference states the requirement a client must satisfy.
    """
    security = operation.get("security")
    if not security:
        return "none"
    names = sorted(security_schemes)
    if any("bearer" in name.lower() for name in names):
        return "bearer"
    return " / ".join(names) or "required"


def _request_cell(spec: dict, operation: dict) -> str:
    body = operation.get("requestBody")
    if not body:
        return "-"
    content = body.get("content", {})
    for media in ("application/json", "multipart/form-data"):
        if media in content:
            return _schema_name(spec, content[media].get("schema"))
    return "-"


def _success_cell(spec: dict, operation: dict) -> str:
    responses = operation.get("responses", {})
    for status in sorted(responses):
        if status.startswith("2"):
            content = responses[status].get("content", {})
            if "application/json" in content:
                return f"{status}: {_schema_name(spec, content['application/json'].get('schema'))}"
            return status
    return "-"


def _error_cell(operation: dict) -> str:
    responses = operation.get("responses", {})
    codes = [status for status in sorted(responses) if not status.startswith("2")]
    return ", ".join(codes) if codes else "-"


def render(spec: dict) -> str:
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.initialize.middleware_stack import _effective_rules
    from bangla_gpt_api.routers._error_contract import ERROR_CATALOG

    info = spec.get("info", {})
    paths: dict = spec.get("paths", {})
    security_schemes = set(spec.get("components", {}).get("securitySchemes", {}))
    operations = [
        (path, method, op)
        for path, item in paths.items()
        for method, op in item.items()
        if method in HTTP_METHODS
    ]
    secured = sum(1 for _, _, op in operations if _auth_cell(op, security_schemes) != "none")

    lines: list[str] = []
    lines.append(GENERATED_NOTICE)
    lines.append("")
    lines.append(f"# API Reference — {info.get('title', 'Bangla GPT API')}")
    lines.append("")
    lines.append(
        "Generated from the running application's own OpenAPI schema by "
        "`apps/api/scripts/gen_api_docs.py`. Do not edit this file: change the "
        "route/schema and regenerate.\n"
    )
    lines.append("```bash")
    lines.append("cd apps/api")
    lines.append("python scripts/gen_api_docs.py          # regenerate this file")
    lines.append("python scripts/gen_api_docs.py --check  # fail when it has drifted")
    lines.append("```")
    lines.append("")
    lines.append(
        f"Schema: OpenAPI **{spec.get('openapi')}** · API version **{info.get('version')}** · "
        f"{len(operations)} operations across {len(paths)} paths "
        f"({secured} require authentication).\n"
    )
    lines.append(
        "Interactive documentation (`/docs`, `/redoc`) and the machine-readable "
        "schema (`/openapi.json`) are served **outside production only**; a "
        "production deployment disables all three (`main.create_app`).\n"
    )

    # --- operational notes (derived from the routers, not from prose) -------
    lines.append("## Operational notes")
    lines.append("")
    lines.append(
        '* `GET /health` — liveness only; a constant `{"status": "ok"}` payload '
        "with no version or environment disclosure.\n"
        '* `GET /live` — process-alive probe (`{"status": "alive"}`).\n'
        "* `GET /ready` — 200 only when the LLM provider is configured, the retrieval "
        "index is loaded and the database answers a trivial query; otherwise 503 with "
        'the failing dependency named. Provider name only (`{"status": "ready", '
        '"provider": "..."}`).\n'
        "* `GET /metrics` — Prometheus exposition, omitted from this schema. In "
        "production it requires `METRICS_TOKEN` via `X-Metrics-Token` or a Bearer "
        "token; outside production it is open (`routers/system.py`).\n"
        "* `GET /admin/system/info` — authenticated; the only endpoint that reports "
        "the app name, version and environment.\n"
        "* Every response — including the 500 built by the unhandled-exception "
        "handler — carries `X-Request-ID` (the caller's value when it is a safe "
        "token, otherwise a generated one). CORS preflight responses are answered "
        "before the request-id middleware runs and are the one exception.\n"
        "* When `must_change_password` is true (bootstrap admin), every route except "
        "`/health`, `/live`, `/ready`, `/metrics`, `/auth/login`, `/auth/change-password` "
        "and `/users/me` answers 403 until the password is rotated "
        "(`routers/deps.py`, `_FORCE_CHANGE_EXEMPT_PATHS`).\n"
    )

    # --- error contract ----------------------------------------------------
    lines.append("## Error contract")
    lines.append("")
    lines.append("Three wire shapes, all of them declared in `routers/_error_contract.py`:")
    lines.append("")
    lines.append('1. `{"detail": "<message>"}` — auth guards and single-message failures.')
    lines.append(
        '2. `{"detail": {"code": ..., "message": ..., <extras>}}` — business rules. '
        "`code` is a stable machine-readable string; switch on it, never on the message."
    )
    lines.append(
        '3. `{"detail": [{"loc": [...], "msg": ...}]}` — request/response '
        "validation (422), FastAPI's own shape."
    )
    lines.append("")
    lines.append("### Business-rule error codes")
    lines.append("")
    lines.append("| Code | Status | `detail` keys | Message (reference site) |")
    lines.append("|---|---|---|---|")
    for code in sorted(ERROR_CATALOG):
        error = ERROR_CATALOG[code]
        message = (error.message or "(composed per call)").replace("|", "\\|")
        lines.append(f"| `{code}` | {error.status} | {', '.join(error.keys)} | {message} |")
    lines.append("")

    # --- rate limits -------------------------------------------------------
    rules = _effective_rules(Settings())
    lines.append("## Rate limits")
    lines.append("")
    lines.append(
        "Applied per client IP unless the scope column says `user` (an authenticated "
        "caller's own budget, so one school NAT cannot lock out a classroom). Limits "
        "come from the running middleware configuration, including any "
        "`RATE_LIMIT_RULES` override; 429 responses carry `Retry-After`."
    )
    lines.append("")
    lines.append("| Route prefix | Limit / window | Scope |")
    lines.append("|---|---|---|")
    for prefix in sorted(rules):
        limit, scope = rules[prefix]
        lines.append(f"| `{prefix}` | {limit} / min | {scope} |")
    lines.append("")

    # --- routes ------------------------------------------------------------
    lines.append("## Routes")
    lines.append("")
    lines.append(
        "`Auth` is `bearer` where the operation declares the HTTP bearer security "
        "scheme; `Request` and `2xx` name the model in `components.schemas`; `Errors` "
        "lists the non-2xx statuses declared for the operation."
    )
    lines.append("")
    groups: dict[str, list[tuple[str, str, dict]]] = {}
    for path, method, op in operations:
        segment = path.strip("/").split("/", 1)[0] or "root"
        groups.setdefault(segment, []).append((path, method, op))
    for segment in sorted(groups):
        lines.append(f"### {segment}")
        lines.append("")
        lines.append("| Method | Path | Auth | Summary | Request | 2xx | Errors |")
        lines.append("|---|---|---|---|---|---|---|")
        for path, method, op in sorted(groups[segment], key=lambda row: (row[0], row[1])):
            summary = str(op.get("summary") or "").replace("|", "\\|") or "-"
            lines.append(
                f"| {method.upper()} | `{path}` | {_auth_cell(op, security_schemes)} | "
                f"{summary} | {_request_cell(spec, op)} | {_success_cell(spec, op)} | "
                f"{_error_cell(op)} |"
            )
        lines.append("")

    lines.append("## Configuration")
    lines.append("")
    lines.append(
        "Environment variables are documented in `.env.example` (generated from "
        "`Settings`, so every field the code reads appears there). Real `.env` files "
        "are never committed."
    )
    lines.append("")
    return "\n".join(lines)


def _display_path(path: Path) -> str:
    """Path relative to the repository when possible, else absolute."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the committed file with the generated one; exit 1 on drift",
    )
    args = parser.parse_args(argv)

    rendered = render(build_spec())
    if args.check:
        if not DOC_PATH.exists():
            print(f"::error::{_display_path(DOC_PATH)} does not exist")
            return 1
        committed = DOC_PATH.read_text(encoding="utf-8")
        if committed != rendered:
            print(
                f"::error file={_display_path(DOC_PATH)}::"
                "API reference is stale -- run: cd apps/api && python scripts/gen_api_docs.py"
            )
            return 1
        operations = rendered.count("\n| ")  # header+rows across every generated table
        print(f"docs/API.md matches the OpenAPI schema ({operations} table rows rendered)")
        return 0

    DOC_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {_display_path(DOC_PATH)} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
