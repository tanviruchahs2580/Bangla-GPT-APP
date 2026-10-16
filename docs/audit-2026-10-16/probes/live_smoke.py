"""Live production smoke: exercise the deployed app as a real user.

Runs against the Vercel production domain (through its /api edge proxy, so this
also verifies the proxy, the tunnel origin and the API container behind them).

Deliberately modest: the deployed instance runs production-like auth rate
limits (10 logins/min per IP), so this keeps its login/register count low. The
full 154-check sweep stays a local/CI activity.

Usage:
    .venv/Scripts/python.exe docs/audit-2026-10-16/probes/live_smoke.py
"""

from __future__ import annotations

import sys
import uuid

import httpx

BASE = "https://bangla-gpt-app.vercel.app"
API = f"{BASE}/api"
PASSWORD = "LiveCheck123!"
CLASS, SUBJECT = 6, "science"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail if not cond else ""))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if not cond and detail else ""), flush=True)


def main() -> int:
    c = httpx.Client(timeout=60.0)
    tag = uuid.uuid4().hex[:6]

    # ---------------------------------------------------------- public surface
    h = c.get(f"{API}/health")
    check("live /api/health", h.status_code == 200 and h.json().get("status") == "ok", h.text[:120])
    r = c.get(f"{API}/ready")
    check("live /api/ready reports a provider", r.status_code == 200 and "provider" in r.text, r.text[:120])
    p = c.get(f"{BASE}/")
    check("live SPA index served", p.status_code == 200 and "শ্রেণি" in p.text)
    check("live index is current (৬–১০, not ১–১২)", "৬–১০" in p.text and "১–১২" not in p.text)
    check("live /login route served", c.get(f"{BASE}/login").status_code == 200)
    check("live /status route served", c.get(f"{BASE}/status").status_code == 200)
    check("security headers from the edge", h.headers.get("x-content-type-options") == "nosniff")

    # --------------------------------------------------------------- registers
    student = f"live.student.{tag}@example.com"
    teacher = f"live.teacher.{tag}@example.com"
    rs = c.post(f"{API}/auth/register", json={"email": student, "password": PASSWORD, "name": "Live Student",
                                             "role": "student", "class_level": CLASS, "guardian_consent": True})
    check("live student registration (with consent)", rs.status_code == 201, rs.text[:160])
    rt = c.post(f"{API}/auth/register", json={"email": teacher, "password": PASSWORD, "name": "Live Teacher",
                                             "role": "teacher"})
    check("live teacher registration", rt.status_code == 201, rt.text[:160])

    ls = c.post(f"{API}/auth/login", json={"email": student, "password": PASSWORD})
    check("live student login", ls.status_code == 200 and "access_token" in ls.text, ls.text[:160])
    lt = c.post(f"{API}/auth/login", json={"email": teacher, "password": PASSWORD})
    check("live teacher login", lt.status_code == 200 and "access_token" in lt.text, lt.text[:160])
    if ls.status_code != 200 or lt.status_code != 200:
        print("\nCannot continue without sessions.")
        return 1
    s_tok = {"Authorization": f"Bearer {ls.json()['access_token']}"}
    t_tok = {"Authorization": f"Bearer {lt.json()['access_token']}"}

    me = c.get(f"{API}/users/me", headers=s_tok)
    check("live /users/me", me.status_code == 200 and me.json().get("email") == student, me.text[:160])
    profile = me.json().get("profile_id")

    # ----------------------------------------------------------- learn + tutor
    subs = c.get(f"{API}/learn/subjects", headers=s_tok)
    check("live learn subjects", subs.status_code == 200 and len(subs.json()) >= 1, subs.text[:160])
    chs = c.get(f"{API}/learn/subjects/{SUBJECT}/chapters", headers=s_tok, params={"class_level": CLASS})
    check("live chapter list", chs.status_code == 200 and len(chs.json()) >= 1, chs.text[:160])
    chapter = None
    if chs.status_code == 200 and chs.json():
        first = chs.json()[0]
        chapter = first.get("chapter") if isinstance(first, dict) else first
    if chapter:
        content = c.get(f"{API}/learn/subjects/{SUBJECT}/chapters/{chapter}", headers=s_tok,
                        params={"class_level": CLASS})
        check("live chapter content has sections",
              content.status_code == 200 and bool(content.json().get("sections")), content.text[:160])

    ask = c.post(f"{API}/tutor/ask", headers=s_tok,
                 json={"question": "কোষ কী?", "class_level": CLASS, "subject": SUBJECT, "chapter": chapter})
    check("live tutor answers", ask.status_code == 200 and bool(ask.json().get("answer")), ask.text[:200])
    if ask.status_code == 200:
        check("live tutor cites sources", isinstance(ask.json().get("sources"), list))

    quiz = c.post(f"{API}/quizzes", headers=s_tok,
                  json={"student_id": profile, "class_level": CLASS, "subject": SUBJECT,
                        "chapter": chapter, "num_questions": 3})
    check("live quiz starts", quiz.status_code in (200, 201), quiz.text[:200])
    if quiz.status_code in (200, 201):
        q = quiz.json()
        sub = c.post(f"{API}/quizzes/{q['attempt_id']}/submit", headers=s_tok,
                     json={"answers": [0 for _ in q.get("questions", [])]})
        check("live quiz submit grades", sub.status_code == 200 and "score_pct" in sub.text, sub.text[:200])
        check("live dashboard summary", c.get(f"{API}/dashboard/summary", headers=s_tok).status_code == 200)
        check("live revision queue", c.get(f"{API}/revision/due", headers=s_tok).status_code == 200)

    rep = c.get(f"{API}/students/me/report", headers=s_tok, params={"period": "weekly"})
    check("live student report", rep.status_code == 200, rep.text[:160])
    if rep.status_code == 200:
        check("live report carries suggestion code+params",
              isinstance(rep.json().get("suggestion_code"), str)
              and isinstance(rep.json().get("suggestion_params"), dict))

    inv = c.post(f"{API}/students/me/invite-code", headers=s_tok)
    check("live invite code issued", inv.status_code == 201, inv.text[:160])
    if inv.status_code == 201:
        payload = inv.json()["code"].split("-", 1)[1]
        check("live invite code is 64-bit hex (this audit's fix)",
              len(payload) == 16 and all(ch in "0123456789ABCDEF" for ch in payload))

    # --------------------------------------------------------------- teacher
    check("live teacher workload", c.get(f"{API}/teacher/workload", headers=t_tok).status_code == 200)
    check("live teacher classrooms list", c.get(f"{API}/teacher/classrooms", headers=t_tok).status_code == 200)

    # -------------------------------------------------------------- negatives
    check("live 401 on unauthenticated tutor",
          c.post(f"{API}/tutor/ask", json={"question": "hi", "class_level": CLASS}).status_code == 401)
    check("live 401 on unauthenticated admin", c.get(f"{API}/admin/users").status_code == 401)
    check("live student refused teacher area", c.get(f"{API}/teacher/workload", headers=s_tok).status_code == 403)
    check("live unknown route is 404", c.get(f"{API}/definitely-not-a-route").status_code == 404)

    failed = [r for r in results if not r[1]]
    print("\n" + "=" * 70)
    print(f"LIVE CHECKS: {len(results)}  PASSED: {len(results) - len(failed)}  FAILED: {len(failed)}")
    for name, _, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
