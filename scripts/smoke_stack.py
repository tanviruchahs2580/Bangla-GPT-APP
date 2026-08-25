"""End-to-end smoke flow against a running stack (compose or bare uvicorn).

Usage:
    python scripts/smoke_stack.py [BASE_URL]

Default BASE_URL is http://127.0.0.1:8000 (inside the api container).
Exercises: register → login → tutor ask → quiz → export → delete.
Prints one PASS line per step; exits non-zero on first failure.
"""

import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
EMAIL = f"smoke-{int(__import__('time').time())}@example.com"
PASSWORD = "smoke-pass-123"


def call(method: str, path: str, body: dict | None = None, token: str | None = None):
    request = urllib.request.Request(f"{BASE}{path}", method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(request, data=data, timeout=15) as response:
        raw = response.read()
        return response.status, (json.loads(raw) if raw else None)


def step(name: str, condition: bool) -> None:
    print(("PASS" if condition else "FAIL"), name)
    if not condition:
        raise SystemExit(1)


status, body = call(
    "POST",
    "/auth/register",
    {
        "email": EMAIL,
        "password": PASSWORD,
        "name": "স্মোক",
        "role": "student",
        "class_level": 6,
        "guardian_consent": True,
    },
)
step("register 201", status == 201)
profile_id = (body or {}).get("profile_id")

status, body = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
token = (body or {}).get("access_token")
step("login 200 + token", status == 200 and bool(token))

status, body = call(
    "POST",
    "/tutor/ask",
    {"question": "কোষ কী?", "class_level": 6, "subject": "science"},
    token=token,
)
step("tutor/ask 200 grounded", status == 200 and body.get("grounded") is True)

status, body = call("POST", "/quizzes", {"student_id": profile_id, "num_questions": 2}, token=token)
attempt_id = (body or {}).get("attempt_id")
step("quiz start 200", status == 200 and attempt_id is not None)

if attempt_id is not None:
    answers = [0] * len(body.get("questions", []))
    status, _ = call("POST", f"/quizzes/{attempt_id}/submit", {"answers": answers}, token=token)
    step("quiz submit 200", status == 200)

status, body = call("GET", "/users/me/export", None, token=token)
step("export 200 profile", status == 200 and (body or {}).get("profile", {}).get("type") == "student")

status, _ = call("DELETE", "/users/me", None, token=token)
step("delete account 204", status == 204)

print("SMOKE OK")
