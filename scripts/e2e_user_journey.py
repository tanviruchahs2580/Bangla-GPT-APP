"""QA-001: end-to-end user journey over real HTTP (live server).

Usage (Windows PowerShell):
    $env:DATABASE_URL = "sqlite:///C:/Users/DST/AppData/Local/Temp/opencode/e2e.db"
    .\\.venv\\Scripts\\python.exe -m uvicorn bangla_gpt_api.main:app --app-dir apps/api/src --port 8123
    .\\.venv\\Scripts\\python.exe scripts/e2e_user_journey.py --base http://127.0.0.1:8123

Covers, as a real user: health/headers → register → login → me → ask
(Bangla, grounded) → conversations → message → history → SSE stream →
quiz start → learn catalog → export → negatives (401s) → delete.
Fail-fast with a printed checklist; exit code 0 only when every step passes.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid

import httpx

PASS = "StrongPass123!"


class Journey:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.client = httpx.Client(base_url=self.base, timeout=60.0)
        self.email = f"e2e_{uuid.uuid4().hex[:8]}@example.com"
        self.token = ""
        self.conv_id: int | None = None
        self.steps: list[str] = []

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        status = "PASS" if cond else "FAIL"
        self.steps.append(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
        print(self.steps[-1], flush=True)
        if not cond:
            raise SystemExit(f"E2E FAILED at: {name} {detail}")

    def auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def run(self) -> None:
        c = self.client
        # 1. health + security headers
        r = c.get("/health")
        self.check("health 200", r.status_code == 200, r.text[:200])
        self.check("health body", r.json().get("status") == "ok", r.text[:200])
        self.check("x-request-id header", "x-request-id" in r.headers)
        self.check("nosniff header", r.headers.get("x-content-type-options") == "nosniff")
        # 2. register + login + me
        r = c.post(
            "/auth/register",
            json={"email": self.email, "password": PASS, "name": "E2E",
                  "role": "student", "class_level": 6, "guardian_consent": True},
        )
        self.check("register 201", r.status_code == 201, r.text[:300])
        r = c.post("/auth/login", json={"email": self.email, "password": PASS})
        self.check("login 200", r.status_code == 200, r.text[:300])
        self.token = r.json()["access_token"]
        r = c.get("/users/me", headers=self.auth())
        self.check("me 200", r.status_code == 200 and r.json()["email"] == self.email, r.text[:200])
        # 3. grounded Bangla ask
        r = c.post(
            "/tutor/ask",
            json={"question": "ভগ্নাংশ কী?", "class_level": 6},
            headers=self.auth(),
        )
        self.check("ask 200", r.status_code == 200, r.text[:300])
        self.check("ask grounded", r.json().get("grounded") is True, r.text[:300])
        # 4. conversations + message + history
        r = c.post("/tutor/conversations", json={"title": "e2e"}, headers=self.auth())
        self.check("conversation 201", r.status_code == 201, r.text[:300])
        self.conv_id = r.json()["id"]
        r = c.post(
            f"/tutor/conversations/{self.conv_id}/messages",
            json={"message": "ভগ্নাংশ কী?", "class_level": 6},
            headers=self.auth(),
        )
        self.check("message 200", r.status_code == 200, r.text[:300])
        r = c.get(f"/tutor/conversations/{self.conv_id}/messages", headers=self.auth())
        self.check("history has 2 turns", r.status_code == 200 and len(r.json()) == 2, r.text[:300])
        # 5. SSE stream ends with done
        with c.stream(
            "POST",
            f"/tutor/conversations/{self.conv_id}/messages/stream",
            json={"message": "ভগ্নাংশ কী?", "class_level": 6},
            headers=self.auth(),
        ) as resp:
            self.check("stream 200", resp.status_code == 200, str(resp.status_code))
            body = resp.read().decode("utf-8")
        self.check("stream has token frames", "event: token" in body, body[:200])
        self.check("stream ends with done", "event: done" in body, body[-300:])
        # 6. quiz + catalog + export
        me_id = c.get("/users/me", headers=self.auth()).json()["profile_id"]
        r = c.post(
            "/quizzes",
            json={"student_id": me_id, "class_level": 6, "num_questions": 2},
            headers=self.auth(),
        )
        self.check("quiz start", r.status_code in (200, 201), r.text[:300])
        r = c.get("/learn/subjects", headers=self.auth())
        self.check("learn subjects", r.status_code == 200 and len(r.json()) >= 1, r.text[:200])
        r = c.get("/users/me/export", headers=self.auth())
        self.check("export 200", r.status_code == 200, r.text[:200])
        # 7. negatives
        bad = c.post("/auth/login", json={"email": self.email, "password": "wrong-wrong"})
        self.check("wrong password 401", bad.status_code == 401, bad.text[:200])
        anon = c.post("/tutor/ask", json={"question": "ভগ্নাংশ কী?", "class_level": 6})
        self.check("anonymous ask 401", anon.status_code == 401, anon.text[:200])
        # 8. delete account
        r = c.delete("/users/me", headers=self.auth())
        self.check("delete 204", r.status_code == 204, r.text[:200])
        print(f"\nE2E JOURNEY COMPLETE: {len(self.steps)} steps, all green.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8123")
    args = ap.parse_args()
    for attempt in range(30):
        try:
            httpx.get(args.base + "/health", timeout=3.0)
            break
        except httpx.ConnectError:
            time.sleep(1.0)
    else:
        print("server not reachable at " + args.base)
        return 2
    Journey(args.base).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
