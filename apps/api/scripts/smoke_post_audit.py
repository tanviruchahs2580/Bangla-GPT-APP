"""Post-fix functional smoke: boot the real app on a scratch SQLite and
exercise the surfaces the audit waves touched, as a user would.

Run:  python scripts/smoke_post_audit.py
Exit 0 = every probe behaved as designed; any probe failure exits 1.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bgpt-smoke-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'smoke.db'}"
    os.environ["ENV"] = "test"
    os.environ["JWT_SECRET"] = "smoke-secret-0123456789abcdef0123456789"  # noqa: S105 - obvious smoke fixture, not a credential
    os.environ["ADMIN_EMAIL"] = "root@example.com"
    os.environ["ADMIN_PASSWORD"] = "Str0ngSmokePassw0rd!"  # noqa: S105 - obvious smoke fixture, not a credential
    os.environ["FORCE_ADMIN_PASSWORD_CHANGE"] = "true"  # noqa: S105 - not a secret at all

    from bangla_gpt_api.config import get_settings

    get_settings.cache_clear()

    from bangla_gpt_api.main import create_app

    app = create_app(get_settings())
    config = uvicorn.Config(app, host="127.0.0.1", port=8777, log_level="critical")
    server = uvicorn.Server(config)
    import threading

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = "http://127.0.0.1:8777"
    for _ in range(100):
        try:
            httpx.get(base + "/live", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    client = httpx.Client(base_url=base, timeout=15)

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    r = client.get("/health")
    check("health 200", r.status_code == 200, r.text[:120])
    r = client.get("/live")
    check("liveness 200", r.status_code == 200)
    r = client.get("/ready")
    check(
        "ready 200 with provider+index",
        r.status_code == 200 and r.json().get("status") == "ready",
        r.text[:200],
    )

    # student register -> login -> me (C1's sibling policy applies at register)
    email = "smoke-student@example.com"
    r = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "SmokePass123!",
            "name": "Smoke",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    check("register 201", r.status_code == 201, r.text[:160])
    r = client.post("/auth/login", json={"email": email, "password": "SmokePass123!"})
    check("login 200", r.status_code == 200, r.text[:160])
    headers = {"Authorization": "Bearer " + r.json()["access_token"]}
    r = client.get("/users/me", headers=headers)
    check("users/me 200", r.status_code == 200 and r.json()["email"] == email)

    # C2: revoke stamps naive UTC and refuses the token. The epoch comparison
    # is integer-second and same-second mints stay valid BY DESIGN (deps.py),
    # so cross the second boundary before asserting the death.
    r = client.post("/users/me/sessions/revoke", headers=headers)
    check("sessions/revoke 204", r.status_code == 204, r.text[:120])
    time.sleep(1.1)
    r = client.get("/users/me", headers=headers)
    check("revoked token dies 401", r.status_code == 401)
    r = client.post("/auth/login", json={"email": email, "password": "SmokePass123!"})
    headers = {"Authorization": "Bearer " + r.json()["access_token"]}
    check("re-login after revoke 200", r.status_code == 200)

    # C1: join-school with a blocklisted password must refuse 400 (422/404 would
    # mean the policy did not run; we use an invalid code on purpose to see the
    # policy fire BEFORE the invite verdict — password check is first)
    r = client.post(
        "/auth/join-school",
        json={
            "invite_code": "bogus-code",
            "email": "staff@example.com",
            "password": "password",
            "name": "Staff",
        },
    )
    check(
        "join-school weak password 400 not 404",
        r.status_code == 400 and "password" in r.text,
        f"{r.status_code} {r.text[:160]}",
    )

    # join-school with a strong password + bogus code must be 404 (policy passed)
    r = client.post(
        "/auth/join-school",
        json={
            "invite_code": "bogus-code",
            "email": "staff@example.com",
            "password": "StaffPass123!",
            "name": "Staff",
        },
    )
    check(
        "strong password reaches invite verdict 404",
        r.status_code == 404,
        f"{r.status_code} {r.text[:160]}",
    )

    # tutor: a locally-produced refusal still answers honestly
    r = client.post(
        "/tutor/ask",
        json={"question": "মঙ্গল গ্রহে কি মানুষ বাস করে?", "class_level": 6, "subject": "science"},
        headers=headers,
    )
    body = r.json() if r.status_code == 200 else {}
    check(
        "tutor out-of-corpus refusal grounded=false",
        r.status_code == 200 and body.get("grounded") is False,
        f"{r.status_code} {r.text[:200]}",
    )

    # error envelope contract survives (C17): unknown token -> coded 401
    r = client.get("/users/me", headers={"Authorization": "Bearer not-a-token"})
    check(
        "coded 401 envelope",
        r.status_code == 401
        and r.json()["detail"].get("code")
        in {"unauthenticated", "invalid_token", "session_expired", "session_ended"},
        r.text[:160],
    )

    server.should_exit = True
    thread.join(timeout=10)
    print(
        json.dumps(
            [{"probe": n, "ok": ok, "detail": d} for n, ok, d in checks],
            ensure_ascii=False,
            indent=1,
        )
    )
    bad = [c for c in checks if not c[1]]
    print(f"SMOKE: {len(checks) - len(bad)}/{len(checks)} probes passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
