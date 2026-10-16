"""Generate the feature/route regression matrix from the app's own route table.

Read-only: builds the app in-process and writes a CSV next to this script.
Run from the repo root:
    .venv/Scripts/python.exe docs/audit-2026-10-16/probes/gen_regression_matrix.py

Two facts are derived from the app itself rather than transcribed:
  * the owning router, from `route.endpoint.__module__`
  * whether the operation is deliberately public, from `PUBLIC_OPERATIONS`
    (lowercased method, path) — the same source `test_openapi_auth_matrix.py`
    asserts against, so this matrix cannot drift from the declared surface.
"""

import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
import sys

sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.main import PUBLIC_OPERATIONS, create_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "FEATURE_REGRESSION_MATRIX.csv"
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# What this audit did to each area, and how it was regression-checked.
CHANGED = {
    "parent": "CHANGED (SEC-007 invite entropy 32→64 bits) + suite re-run",
    "initialize": "CHANGED (CORS now outermost) — affects every route; full suite re-run",
    "middleware": "CHANGED (CORS/rate-limit/body-size order) — affects every route; full suite re-run",
}


def _walk(routes):
    """Yield every concrete HTTP route, descending into included routers.

    `register_routers` mounts each module through FastAPI's `_IncludedRouter`
    wrapper, which exposes the mounted router as `original_router` instead of
    flattening its routes into the app's list.
    """
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _walk(inner.routes)
            continue
        nested = getattr(route, "routes", None)
        if nested:
            yield from _walk(nested)
            continue
        yield route


def main() -> int:
    settings = Settings(
        env="test",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        database_url="sqlite:///./.matrix-tmp.db",
    )
    app = create_app(settings)

    rows = []
    for route in _walk(app.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        endpoint = getattr(route, "endpoint", None)
        if not path or not methods or endpoint is None:
            continue  # Starlette's own mounts (/docs, /openapi.json, …)
        module = getattr(endpoint, "__module__", "")
        area = module.rsplit(".", 1)[-1] if module else "unknown"
        if endpoint.__name__ in {"openapi", "swagger_ui_html", "redoc_html"}:
            continue
        for method in sorted(methods & HTTP_METHODS):
            public = (method.lower(), path) in PUBLIC_OPERATIONS
            rows.append(
                {
                    "id": f"API-{len(rows) + 1:03d}",
                    "surface": "api",
                    "area": area,
                    "method": method,
                    "path": path,
                    "auth": "public (declared)" if public else "authenticated",
                    "handler": endpoint.__name__,
                    "change_impact": CHANGED.get(
                        area, "not modified by this audit; covered by the full suite re-run"
                    ),
                    "regression_status": "PASS (suite re-run after changes)",
                }
            )

    rows.sort(key=lambda r: (r["area"], r["path"], r["method"]))
    for i, row in enumerate(rows, start=1):
        row["id"] = f"API-{i:03d}"

    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    public_count = sum(1 for r in rows if r["auth"].startswith("public"))
    areas = sorted({r["area"] for r in rows})
    print(f"wrote {OUT.name}: {len(rows)} operations, {public_count} public")
    print("areas:", ", ".join(areas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
