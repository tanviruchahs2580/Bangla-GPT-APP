"""Probe: middleware execution order and cross-origin readability of rejections.

Run from the repo root:
    .venv/Scripts/python.exe docs/audit-2026-10-16/probes/probe_middleware_order.py

Prints, for a test-env app with CORS configured:
  * registration order (app.user_middleware)
  * resolved runtime order (outermost -> innermost)
  * whether CORS / security / request-id headers reach each response class
"""

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.main import create_app  # noqa: E402

ORIGIN = "https://app.example.edu.bd"
INTERESTING = (
    "access-control-allow-origin",
    "x-request-id",
    "x-content-type-options",
    "content-security-policy",
)


def headed(res) -> dict:
    return {h: res.headers.get(h) for h in INTERESTING}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bgpt-probe-"))
    settings = Settings(
        env="test",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        database_url=f"sqlite:///{tmp}/probe.db",
        allowed_origins=ORIGIN,
        rate_limit_login_per_minute=1,
        max_body_bytes=200,
    )
    app = create_app(settings)
    client = TestClient(app, raise_server_exceptions=False)

    print("registration order :", [m.cls.__name__ for m in app.user_middleware])

    node = app.build_middleware_stack()
    runtime = []
    while node is not None and len(runtime) < 12:
        runtime.append(type(node).__name__)
        node = getattr(node, "app", None)
    print("runtime outermost->innermost:", runtime)

    print("\n[1] /health 200")
    res = client.get("/health", headers={"Origin": ORIGIN})
    print("   status", res.status_code, headed(res))

    print("\n[2] preflight OPTIONS /auth/login")
    res = client.options(
        "/auth/login",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    print("   status", res.status_code, headed(res))

    print("\n[3] rate-limited POST /auth/login (limit=1/min)")
    first = client.post("/auth/login", json={"email": "a@b.c", "password": "x"}, headers={"Origin": ORIGIN})
    second = client.post("/auth/login", json={"email": "a@b.c", "password": "x"}, headers={"Origin": ORIGIN})
    print("   first  status", first.status_code, headed(first))
    print("   second status", second.status_code, headed(second))
    print("   second body", second.text[:200])

    print("\n[4] oversized body POST /auth/login (max=200 bytes)")
    res = client.post(
        "/auth/login",
        content=b"x" * 5000,
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    print("   status", res.status_code, headed(res))
    print("   body", res.text[:200])

    print("\n[5] 404 unknown path")
    res = client.get("/definitely-not-a-route", headers={"Origin": ORIGIN})
    print("   status", res.status_code, headed(res))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
