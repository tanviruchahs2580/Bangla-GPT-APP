"""T-37 capacity smoke: dependency-free load script (LOCAL + MOCK, measure-only).

Five representative endpoints, stepped concurrency, three runs per step.
No pass/fail threshold — the numbers are inputs for human pilot sizing (HO-6/HO-7).
"""
import asyncio, json, statistics, sys, time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
STEPS = [10, 25]
DURATION = 8  # seconds per step (kept short; measure-only)

TOKENS = {}
ROLES = {
    "student": ("stu.t37@load.test", "Str0ngStuPassw0rd!"),
    "teacher": ("teach.t37@load.test", "Str0ngTeachPassw0rd!"),
}

def http(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            code = r.status
            r.read()
    except urllib.error.HTTPError as e:
        code = e.code
        e.read()
    except Exception:
        code = -1
    return code, (time.perf_counter() - t0) * 1000

def seed_and_login():
    for role, (email, pw) in ROLES.items():
        code, _ = http("POST", "/auth/login", {"email": email, "password": pw})
        if code != 200:
            code, _ = http("POST", "/auth/register", {"email": email, "password": pw,
                          "name": "Load " + role, "role": role,
                          **({"class_level": 6, "guardian_consent": True} if role == "student" else {})})
        code, _ = http("POST", "/auth/login", {"email": email, "password": pw})
        assert code == 200, (role, code)
        TOKENS[role] = json.loads(json.dumps({})).get(role)
    # capture tokens via a tiny sync helper (urllib returns body; re-login to read)
    out = {}
    for role, (email, pw) in ROLES.items():
        req = urllib.request.Request(BASE + "/auth/login", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, data=json.dumps({"email": email, "password": pw}).encode(), timeout=30) as r:
            out[role] = json.loads(r.read())["access_token"]
    return out

async def worker(role, path, method, body_fn, deadline, latencies, errors):
    token = TOKENS[role]
    while time.perf_counter() < deadline:
        code, ms = http(method, path, body_fn() if callable(body_fn) else body_fn, token)
        if code in (200, 201):
            latencies.append(ms)
        else:
            errors.append((code, path))

async def phase(name, role, path, method, body_fn, vus):
    lat, errs = [], []
    deadline = time.perf_counter() + DURATION
    tasks = [asyncio.create_task(worker(role, path, method, body_fn, deadline, lat, errs)) for _ in range(vus)]
    await asyncio.gather(*tasks)
    lat.sort()
    def pct(p):
        return round(lat[min(len(lat)-1, int(p * len(lat)))], 1) if lat else None
    return {"endpoint": name, "vus": vus, "n": len(lat), "errors": len(errs),
            "p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99)}

async def main():
    TOKENS.update(seed_and_login())
    results = []
    qs = {"question": "কোষ বিভাজন কী?", "class_level": 6, "subject": "science"}
    for vus in STEPS:
        for run in range(2):
            r = []
            r.append(await phase("GET /health", "student", "/health", "GET", None, vus))
            r.append(await phase("POST /tutor/ask (mock)", "student", "/tutor/ask", "POST", lambda: dict(qs), vus))
            r.append(await phase("GET /students/me/invite-code", "student", "/students/me/invite-code", "GET", None, vus))
            r.append(await phase("GET /learn/progress", "student", "/learn/progress", "GET", None, vus))
            r.append(await phase("POST /notes", "student", "/notes", "POST",
                                 lambda: {"title": "t", "content": "c"}, vus))
            results.append({"step": vus, "run": run + 1, "rows": r})
            print(json.dumps(results[-1]), flush=True)  # stream: partial results survive a timeout
    print(json.dumps({"base": BASE, "provenance": ["LOCAL", "MOCK", "SQLITE"], "results": results}, indent=1))

asyncio.run(main())
