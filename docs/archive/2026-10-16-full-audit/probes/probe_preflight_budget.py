"""Probe: does a CORS preflight OPTIONS request consume rate-limit budget?

Run from the repo root:
    .venv/Scripts/python.exe docs/audit-2026-10-16/probes/probe_preflight_budget.py

With RATE_LIMIT_LOGIN_PER_MINUTE=2, a browser issuing login POSTs sends a
preflight before the first one. If preflights are counted, only one real
login attempt fits in the window instead of two.
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


def scenario(label: str, *, preflight: bool) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="bgpt-preflight-"))
    settings = Settings(
        env="test",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        database_url=f"sqlite:///{tmp}/probe.db",
        allowed_origins=ORIGIN,
        rate_limit_login_per_minute=2,
    )
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    if preflight:
        res = client.options(
            "/auth/login",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
        )
        print(f"  preflight -> {res.status_code}")
    statuses = []
    for i in range(3):
        res = client.post(
            "/auth/login",
            json={"email": "a@b.c", "password": "x"},
            headers={"Origin": ORIGIN},
        )
        statuses.append(res.status_code)
    print(f"  {label}: login POST statuses = {statuses}")


print("limit = 2 login requests/minute")
print("without preflight:")
scenario("no-preflight", preflight=False)
print("with preflight (real browser behaviour, cross-origin):")
scenario("with-preflight", preflight=True)
