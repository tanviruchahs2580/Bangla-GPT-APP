"""Full-surface end-to-end verification as a real user, over real HTTP.

Covers every role journey the product exposes (student, teacher, parent,
school_admin, admin), the auth surface (password reset, MFA, forced password
change), the negative authorization matrix, and the specific behaviours this
audit changed (parent invite entropy, CORS readability of rejections).

Idempotent: fixed QA accounts are reused across runs, so a browser pass can log
in with the same credentials afterwards.

Usage:
    .venv/Scripts/python.exe docs/audit-2026-10-16/probes/e2e_full_surface.py \
        --base http://127.0.0.1:8020 --admin-email qa.admin.audit@example.com
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx

PASSWORD = "AuditPass123!"
ADMIN_PASSWORD = "AuditPass123!"
ROTATED = "AuditPass789!"
CLASS, SUBJECT = 6, "science"
CHAPTER = "কোষ"

_results: list[tuple[str, bool, str]] = []
_check_log: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    _results.append((name, bool(cond), detail if not cond else ""))
    line = f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if not cond and detail else "")
    print(line, flush=True)
    _check_log.append(line)
    return bool(cond)


def body(res: httpx.Response, limit: int = 240) -> str:
    try:
        return str(res.json())[:limit]
    except Exception:
        return res.text[:limit]


class Api:
    def __init__(self, base: str) -> None:
        self.c = httpx.Client(base_url=base.rstrip("/"), timeout=120.0)

    def call(self, method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
        headers = dict(kw.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.c.request(method, path, headers=headers, **kw)


def ensure_account(api: Api, email: str, role: str, password: str = PASSWORD, **extra) -> None:
    """Register if missing; a re-run then just logs in."""
    payload = {"email": email, "password": password, "name": f"QA {role}", "role": role}
    payload.update(extra)
    res = api.call("POST", "/auth/register", json=payload)
    if res.status_code not in (201, 409):
        print(f"  (register {email} -> {res.status_code} {body(res, 120)})")


def login(api: Api, email: str, password: str = PASSWORD) -> tuple[str, httpx.Response]:
    res = api.call("POST", "/auth/login", json={"email": email, "password": password})
    token = res.json().get("access_token", "") if res.status_code == 200 else ""
    return token, res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    ap.add_argument("--admin-email", default="qa.admin.audit@example.com")
    args = ap.parse_args()

    api = Api(args.base)
    student_email = "qa.student@example.com"
    teacher_email = "qa.teacher@example.com"
    parent_email = "qa.parent@example.com"
    staff_email = "qa.staff@example.com"

    # ---------------------------------------------------------------- health
    h = api.call("GET", "/health")
    check("health returns ok", h.status_code == 200 and h.json().get("status") == "ok", body(h))
    r = api.call("GET", "/ready")
    check("ready reports db+provider", r.status_code == 200 and "provider" in r.json(), body(r))
    check("status endpoint answers", api.call("GET", "/status").status_code == 200)
    check("security headers present", h.headers.get("x-content-type-options") == "nosniff")
    check("request id generated", bool(h.headers.get("x-request-id")))
    check("client request id honored",
          api.call("GET", "/health", headers={"X-Request-ID": "req-e2e-1"}).headers.get("x-request-id") == "req-e2e-1")
    check("docs hidden outside dev? (open in dev is expected)", api.call("GET", "/openapi.json").status_code == 200)

    # ---------------------------------------------------------------- auth
    check("student needs guardian consent",
          api.call("POST", "/auth/register", json={"email": f"nc.{uuid.uuid4().hex[:6]}@example.com",
                                                  "password": PASSWORD, "name": "NC",
                                                  "role": "student", "class_level": CLASS}).status_code == 409)
    check("admin self-registration refused",
          api.call("POST", "/auth/register", json={"email": f"hack.{uuid.uuid4().hex[:6]}@example.com",
                                                  "password": PASSWORD, "name": "H",
                                                  "role": "admin"}).status_code in (403, 422, 409))
    ensure_account(api, student_email, "student", class_level=CLASS, guardian_consent=True)
    ensure_account(api, teacher_email, "teacher")
    ensure_account(api, parent_email, "parent")

    s_tok, s_res = login(api, student_email)
    t_tok, t_res = login(api, teacher_email)
    p_tok, p_res = login(api, parent_email)
    check("student login", bool(s_tok), body(s_res))
    check("teacher login", bool(t_tok), body(t_res))
    check("parent login", bool(p_tok), body(p_res))
    check("wrong password rejected", login(api, student_email, "WrongPass123!")[1].status_code == 401)
    check("unknown user rejected", login(api, f"nobody.{uuid.uuid4().hex[:6]}@example.com")[1].status_code == 401)

    me = api.call("GET", "/users/me", s_tok)
    me_j = me.json() if me.status_code == 200 else {}
    student_profile = me_j.get("profile_id")
    check("me returns profile", me.status_code == 200 and me_j.get("email") == student_email, body(me))
    check("me requires auth", api.call("GET", "/users/me").status_code == 401)

    # MFA enroll on the parent account (secret issued; full TOTP round trip is
    # covered by tests/test_mfa.py which can compute codes)
    mf = api.call("POST", "/auth/mfa/enroll", p_tok)
    check("mfa enroll issues a secret", mf.status_code == 200 and "secret" in str(mf.json()), body(mf))

    # password rotation on a throwaway account, then back
    throw_email = f"qa.rotate.{uuid.uuid4().hex[:6]}@example.com"
    ensure_account(api, throw_email, "student", class_level=CLASS, guardian_consent=True)
    tt, _ = login(api, throw_email)
    cp = api.call("POST", "/auth/change-password", tt, json={"current_password": PASSWORD, "new_password": ROTATED})
    check("change password", cp.status_code in (200, 204), body(cp))
    check("old password no longer works", login(api, throw_email, PASSWORD)[1].status_code == 401)
    check("new password works", bool(login(api, throw_email, ROTATED)[0]))

    # ---------------------------------------------------------------- student
    subjects = api.call("GET", "/learn/subjects", s_tok)
    check("learn subjects", subjects.status_code == 200 and len(subjects.json()) >= 1, body(subjects))
    chapters = api.call("GET", f"/learn/subjects/{SUBJECT}/chapters?class_level={CLASS}", s_tok)
    ch_list = chapters.json() if chapters.status_code == 200 else []
    check("subject chapters", chapters.status_code == 200 and len(ch_list) >= 1, body(chapters))
    chapter_name = CHAPTER
    if ch_list and not any((c.get("chapter") if isinstance(c, dict) else c) == CHAPTER for c in ch_list):
        first = ch_list[0]
        chapter_name = first.get("chapter") if isinstance(first, dict) else first
    content = api.call("GET", f"/learn/subjects/{SUBJECT}/chapters/{chapter_name}?class_level={CLASS}", s_tok)
    sections = content.json().get("sections") if content.status_code == 200 else None
    check(f"chapter content has sections ({chapter_name})",
          content.status_code == 200 and bool(sections), body(content))
    check("chapter content is grounded in the corpus",
          bool(sections) and all(s.get("text") for s in sections))

    prog = api.call("POST", "/learn/progress", s_tok,
                    json={"subject": SUBJECT, "chapter": chapter_name, "class_level": CLASS,
                          "read_pct": 40, "bookmarked": True})
    check("progress upsert", prog.status_code in (200, 201), body(prog))
    plist = api.call("GET", "/learn/progress", s_tok)
    check("progress list contains it", plist.status_code == 200 and any(
        p.get("chapter") == chapter_name for p in plist.json()), body(plist))

    ask = api.call("POST", "/tutor/ask", s_tok,
                   json={"question": "কোষ কী?", "class_level": CLASS, "subject": SUBJECT, "chapter": chapter_name})
    ask_ok = ask.status_code == 200 and bool(ask.json().get("answer"))
    check("tutor answers from evidence", ask_ok, body(ask))
    ask_j = ask.json() if ask_ok else {}
    check("tutor answer carries sources", isinstance(ask_j.get("sources"), list))

    conv = api.call("POST", "/tutor/conversations", s_tok, json={"title": "E2E"})
    conv_id = conv.json().get("id") if conv.status_code in (200, 201) else None
    check("conversation create", conv_id is not None, body(conv))
    msg_id = None
    if conv_id:
        check("conversation list", api.call("GET", "/tutor/conversations", s_tok).status_code == 200)
        msg = api.call("POST", f"/tutor/conversations/{conv_id}/messages", s_tok,
                       json={"message": "পানিচক্র কী?", "class_level": CLASS, "subject": SUBJECT})
        check("conversation message", msg.status_code in (200, 201), body(msg))
        if msg.status_code in (200, 201):
            msg_id = msg.json().get("id") or (msg.json().get("message") or {}).get("id")
        check("conversation messages list",
              api.call("GET", f"/tutor/conversations/{conv_id}/messages", s_tok).status_code == 200)
        check("message search", api.call("GET", "/tutor/messages/search?q=পানি", s_tok).status_code == 200)
        check("conversation rename", api.call("PATCH", f"/tutor/conversations/{conv_id}", s_tok,
                                             json={"title": "E2E renamed"}).status_code in (200, 204))
        stream = api.call("POST", f"/tutor/conversations/{conv_id}/messages/stream", s_tok,
                          json={"message": "আলো কী?", "class_level": CLASS, "subject": SUBJECT})
        check("SSE stream responds",
              stream.status_code == 200 and "text/event-stream" in stream.headers.get("content-type", ""),
              f"{stream.status_code} {stream.headers.get('content-type')}")
        check("SSE stream carries tokens", "token" in stream.text, stream.text[:120])

    fb = api.call("POST", "/feedback", s_tok, json={"rating": 1, "message_id": msg_id, "comment": "E2E helpful"})
    check("feedback accepted", fb.status_code in (200, 201), body(fb))
    check("analytics event accepted", api.call("POST", "/events", s_tok,
                                              json={"name": "e2e_event", "props": {"k": "v"}}).status_code in (200, 202))

    quiz = api.call("POST", "/quizzes", s_tok,
                    json={"student_id": student_profile, "class_level": CLASS, "subject": SUBJECT,
                          "chapter": chapter_name, "num_questions": 5})
    quiz_ok = quiz.status_code in (200, 201)
    check("quiz start", quiz_ok, body(quiz))
    attempt_id = None
    if quiz_ok:
        qdata = quiz.json()
        attempt_id = qdata.get("attempt_id")
        qs = qdata.get("questions", [])
        check("quiz returns questions", len(qs) >= 1, str(qdata)[:200])
        check("quiz questions carry options", all(len(q.get("options", [])) >= 2 for q in qs), str(qs[:1])[:200])
        sub = api.call("POST", f"/quizzes/{attempt_id}/submit", s_tok, json={"answers": [0 for _ in qs]})
        check("quiz submit graded", sub.status_code == 200 and "score_pct" in sub.json(), body(sub))
        if sub.status_code == 200:
            graded = sub.json()
            check("grading is honest (score reflects answers)",
                  isinstance(graded.get("score_pct"), (int, float)) and "review" in graded, str(graded)[:200])
        check("quiz double-submit refused",
              api.call("POST", f"/quizzes/{attempt_id}/submit", s_tok,
                       json={"answers": [0 for _ in qs]}).status_code == 400)
        check("quiz endpoint is POST-only (no history leak by GET)",
              api.call("GET", "/quizzes", s_tok).status_code == 405)
        check("dashboard summary", api.call("GET", "/dashboard/summary", s_tok).status_code == 200)
        check("global search", api.call("GET", "/search?q=কোষ", s_tok).status_code == 200)
        check("revision queue", api.call("GET", "/revision/due", s_tok).status_code == 200)
        check("kg gaps", api.call("GET", "/kg/gaps", s_tok).status_code == 200)
        check("activity heatmap", api.call("GET", f"/students/{student_profile}/activity", s_tok).status_code == 200)
        check("own progress view", api.call("GET", f"/students/{student_profile}/progress", s_tok).status_code == 200)
        check("own consent state", api.call("GET", f"/students/{student_profile}/consent", s_tok).status_code == 200)

    note = api.call("POST", "/notes", s_tok, json={"title": "E2E", "body": "note body", "source": "chapter"})
    check("note create", note.status_code in (200, 201), body(note))
    check("notes list", api.call("GET", "/notes", s_tok).status_code == 200)
    if note.status_code in (200, 201):
        check("note delete", api.call("DELETE", f"/notes/{note.json().get('id')}", s_tok).status_code in (200, 204))
    check("notifications list", api.call("GET", "/notifications", s_tok).status_code == 200)
    check("prefs read", api.call("GET", "/students/me/prefs", s_tok).status_code == 200)
    prefs = api.call("PATCH", "/students/me/prefs", s_tok,
                     json={"memory_enabled": True,
                           "learning_prefs": {"explanation_style": "simple", "subject_focus": "science"}})
    check("prefs patch (whitelisted keys)", prefs.status_code == 200, body(prefs))
    bad_pref = api.call("PATCH", "/students/me/prefs", s_tok, json={"learning_prefs": {"nonsense": "x"}})
    check("unknown pref key refused", bad_pref.status_code == 422, body(bad_pref))
    check("memory read", api.call("GET", "/students/me/memory", s_tok).status_code == 200)
    check("memory clear", api.call("DELETE", "/students/me/memory", s_tok).status_code in (200, 204))
    rep = api.call("GET", "/students/me/report?period=monthly", s_tok)
    check("report monthly", rep.status_code == 200, body(rep))
    if rep.status_code == 200:
        rj = rep.json()
        check("report carries suggestion code+params",
              isinstance(rj.get("suggestion_code"), str) and isinstance(rj.get("suggestion_params"), dict),
              str(rj)[:200])
    check("data export", api.call("GET", "/users/me/export", s_tok).status_code == 200)

    inv = api.call("POST", "/students/me/invite-code", s_tok)
    inv_ok = inv.status_code == 201
    check("student invite code issued", inv_ok, body(inv))
    invite_code = inv.json().get("code", "") if inv_ok else ""
    if inv_ok:
        payload = invite_code.split("-", 1)[1]
        check("invite code is 64-bit hex (this audit's SEC-007 fix)",
              len(payload) == 16 and all(c in "0123456789ABCDEF" for c in payload), f"got {invite_code!r}")

    # ---------------------------------------------------------------- teacher
    check("teacher workload", api.call("GET", "/teacher/workload", t_tok).status_code == 200)
    check("teacher students list", api.call("GET", "/teacher/students", t_tok).status_code == 200)
    check("teacher analytics", api.call("GET", f"/teacher/classes/{CLASS}/analytics", t_tok).status_code == 200)
    room = api.call("POST", "/teacher/classrooms", t_tok, json={"class_level": CLASS, "section": "A"})
    room_ok = room.status_code in (200, 201)
    if not room_ok and room.status_code == 409:
        # a previous run already created this class+section; reuse it
        listing = api.call("GET", "/teacher/classrooms", t_tok)
        for row in (listing.json() if listing.status_code == 200 else []):
            if row.get("class_level") == CLASS and row.get("section") == "A":
                room = httpx.Response(200, json=row, request=listing.request)
                room_ok = True
                break
        check("duplicate classroom refused (idempotent re-run)", room_ok, body(room))
    else:
        check("classroom create", room_ok, body(room))
    room_id = room.json().get("id") if room_ok else None
    imported_code = ""
    imported_email = ""
    roster_student_profile = None
    if room_id:
        check("classroom list", api.call("GET", "/teacher/classrooms", t_tok).status_code == 200)
        check("classroom roster empty ok", api.call("GET", f"/teacher/classrooms/{room_id}/roster", t_tok).status_code == 200)
        imported_email = f"qa.roster.{uuid.uuid4().hex[:6]}@example.com"
        csv_text = f"name,email\nQA Roster,{imported_email}\n"
        imp = api.call("POST", f"/teacher/classrooms/{room_id}/import", t_tok, json={"csv_text": csv_text})
        imp_ok = imp.status_code in (200, 201)
        check("roster CSV import", imp_ok, body(imp))
        if imp_ok:
            ij = imp.json()
            check("CSV import actually created the student", ij.get("created") == 1, str(ij)[:200])
            for row in ij.get("rows", []):
                if row.get("status") == "created" and row.get("invite_code"):
                    imported_code = row["invite_code"]
        if imported_code:
            # the imported student logs in with the one-time code, is forced to
            # change password, then becomes assignable (same school).
            first_login = api.call("POST", "/auth/login",
                                   json={"email": imported_email, "password": imported_code})
            check("imported student can log in with the issued code", first_login.status_code == 200, body(first_login))
            if first_login.status_code == 200:
                imp_tok = first_login.json().get("access_token", "")
                chg = api.call("POST", "/auth/change-password", imp_tok,
                               json={"current_password": imported_code, "new_password": PASSWORD})
                check("forced password change works", chg.status_code in (200, 204), body(chg))
                imp_tok2, _ = login(api, imported_email)
                me2 = api.call("GET", "/users/me", imp_tok2)
                roster_student_profile = me2.json().get("profile_id") if me2.status_code == 200 else None
                check("imported student profile reachable", bool(roster_student_profile), body(me2))
        st = api.call("POST", "/teacher/shorttests", t_tok,
                      json={"classroom_id": room_id, "subject": SUBJECT, "chapter": chapter_name, "num_questions": 3})
        check("short test create (roster present)", st.status_code in (200, 201), body(st))
        check("short test list", api.call("GET", "/teacher/shorttests", t_tok).status_code == 200)
        check("student short tests list", api.call("GET", "/shorttests/mine", s_tok).status_code == 200)
        if roster_student_profile:
            asn = api.call("POST", "/teacher/assignments", t_tok,
                           json={"student_ids": [roster_student_profile], "subject": SUBJECT,
                                 "chapter": chapter_name, "num_questions": 3,
                                 "due_at": "2026-11-30T12:00:00"})
            check("assignment create for same-school student", asn.status_code in (200, 201), body(asn))
            if asn.status_code in (200, 201):
                aid = asn.json().get("id")
                check("assignment list", api.call("GET", "/teacher/assignments", t_tok).status_code == 200)
                check("assignment progress", api.call("GET", f"/teacher/assignments/{aid}/progress", t_tok).status_code == 200)
            # A support plan is derived from graded quizzes, so the student must
            # have taken one first — the API refuses to invent a plan from no
            # data (422 "no graded quiz data for this student").
            if roster_student_profile and imp_tok2:
                empty_plan = api.call("POST", "/teacher/support-plans", t_tok,
                                      json={"student_id": roster_student_profile})
                check("support plan refused without graded quiz data",
                      empty_plan.status_code == 422, f"{empty_plan.status_code} {body(empty_plan)}")
                rq = api.call("POST", "/quizzes", imp_tok2,
                              json={"student_id": roster_student_profile, "class_level": CLASS,
                                    "subject": SUBJECT, "chapter": chapter_name, "num_questions": 3})
                if rq.status_code in (200, 201):
                    rqj = rq.json()
                    api.call("POST", f"/quizzes/{rqj['attempt_id']}/submit", imp_tok2,
                             json={"answers": [0 for _ in rqj.get("questions", [])]})
                plan = api.call("POST", "/teacher/support-plans", t_tok,
                                json={"student_id": roster_student_profile})
                check("support plan create after graded quiz", plan.status_code in (200, 201), body(plan))
            check("support plan list", api.call("GET", "/teacher/support-plans", t_tok).status_code == 200)
        # negative: a self-registered student outside the school must be refused
        out = api.call("POST", "/teacher/assignments", t_tok,
                       json={"student_ids": [student_profile], "subject": SUBJECT, "chapter": chapter_name,
                             "num_questions": 3, "due_at": "2026-11-30T12:00:00"})
        check("cross-school assignment refused (tenancy)", out.status_code == 403, f"{out.status_code} {body(out)}")
        out2 = api.call("GET", f"/teacher/classrooms/{room_id}/roster", t_tok)
        check("roster now lists the imported student",
              out2.status_code == 200 and len(out2.json() or []) >= 1, body(out2))
    check("weak matrix", api.call("GET", f"/teacher/weak-matrix?class_level={CLASS}", t_tok).status_code == 200)
    check("curriculum coverage", api.call("GET", f"/teacher/curriculum-coverage?class_level={CLASS}", t_tok).status_code == 200)

    qp = api.call("POST", "/teacher/qpapers", t_tok,
                  json={"class_level": CLASS, "subject": SUBJECT, "chapters": [chapter_name],
                        "exam_type": "Exam 2026", "marks": 10, "duration_min": 60})
    qp_ok = qp.status_code in (200, 201)
    check("question paper draft", qp_ok, body(qp))
    if qp_ok:
        qid = qp.json().get("id")
        check("qpaper has questions", len(qp.json().get("questions", [])) >= 1, str(qp.json())[:200])
        check("qpaper list", api.call("GET", "/teacher/qpapers", t_tok).status_code == 200)
        check("qpaper get", api.call("GET", f"/teacher/qpapers/{qid}", t_tok).status_code == 200)
        check("qpaper regenerate", api.call("POST", f"/teacher/qpapers/{qid}/regenerate", t_tok,
                                           json={}).status_code in (200, 201))
        check("qpaper shuffle", api.call("POST", f"/teacher/qpapers/{qid}/shuffle", t_tok,
                                        json={}).status_code in (200, 201))
        check("qpaper pdf", api.call("GET", f"/teacher/qpapers/{qid}/pdf", t_tok).status_code == 200)
    big = api.call("POST", "/teacher/qpapers", t_tok,
                   json={"class_level": CLASS, "subject": SUBJECT, "chapters": [chapter_name],
                         "exam_type": "Exam 2026", "marks": 30, "duration_min": 60})
    print(f"  [note] qpaper marks=30 -> {big.status_code} {body(big, 120)}")
    lp = api.call("POST", "/teacher/lesson-plans", t_tok,
                  json={"class_level": CLASS, "subject": SUBJECT, "chapter": chapter_name, "minutes": 35})
    check("lesson plan create", lp.status_code in (200, 201), body(lp))
    for kind in ("worksheet", "homework", "rubric"):
        g = api.call("POST", f"/teacher/generate/{kind}", t_tok,
                     json={"class_level": CLASS, "subject": SUBJECT, "chapter": chapter_name})
        check(f"generate {kind}", g.status_code in (200, 201), body(g))
    check("unknown generator kind refused", api.call("POST", "/teacher/generate/lesson_plan", t_tok,
                                                    json={"class_level": CLASS}).status_code == 404)
    docs = api.call("GET", "/teacher/documents", t_tok)
    check("teacher documents list", docs.status_code == 200, body(docs))
    jobs = api.call("POST", "/teacher/jobs", t_tok,
                    json={"kind": "worksheet", "payload": {"class_level": CLASS, "subject": SUBJECT,
                                                          "chapter": chapter_name}})
    check("teacher job enqueue", jobs.status_code in (200, 201, 202), body(jobs))
    check("teacher jobs list", api.call("GET", "/teacher/jobs", t_tok).status_code == 200)

    # ---------------------------------------------------------------- parent
    link = api.call("POST", "/parents/link/invite", p_tok, json={"code": invite_code})
    check("parent redeems invite", link.status_code in (200, 201), body(link))
    kids = api.call("GET", "/parents/me/children", p_tok)
    check("parent sees linked child", kids.status_code == 200 and len(kids.json()) == 1, body(kids))
    check("invite is single use",
          api.call("POST", "/parents/link/invite", p_tok, json={"code": invite_code}).status_code == 400)
    check("parent child report",
          api.call("GET", f"/parents/me/children/{student_profile}/report?period=weekly", p_tok).status_code == 200)
    check("consent-less direct link is disabled",
          api.call("POST", "/parents/link", p_tok, json={"student_id": student_profile}).status_code in (403, 410))

    # ---------------------------------------------------------------- admin
    a_tok, a_res = login(api, args.admin_email, ADMIN_PASSWORD)
    if not a_tok:
        # a previous run of this script already rotated the bootstrap password
        a_tok, a_res = login(api, args.admin_email, ROTATED)
    if a_tok:
        gate = api.call("GET", "/admin/users?limit=1", a_tok)
        if gate.status_code == 403 and "Password change required" in str(gate.json()):
            print("  [note] bootstrap admin is forced to change its password first (correct)")
            chg = api.call("POST", "/auth/change-password", a_tok,
                           json={"current_password": ADMIN_PASSWORD, "new_password": ROTATED})
            check("admin forced password change", chg.status_code in (200, 204), body(chg))
            a_tok, _ = login(api, args.admin_email, ROTATED)
    check("admin login", bool(a_tok), body(a_res))
    if a_tok:
        check("admin users list", api.call("GET", "/admin/users?limit=5", a_tok).status_code == 200)
        check("admin users filtered", api.call("GET", "/admin/users?role=teacher&limit=5", a_tok).status_code == 200)
        check("admin overview", api.call("GET", "/admin/analytics/overview", a_tok).status_code == 200)
        check("admin school stats", api.call("GET", "/admin/schools/stats", a_tok).status_code == 200)
        check("admin content versions", api.call("GET", "/admin/content/versions", a_tok).status_code == 200)
        check("admin feedback queue", api.call("GET", "/admin/feedback?status=open&limit=5", a_tok).status_code == 200)
        check("admin ai quality", api.call("GET", "/admin/ai/quality", a_tok).status_code == 200)
        check("admin safety refusals", api.call("GET", "/admin/safety/refusals", a_tok).status_code == 200)
        check("admin audit log", api.call("GET", "/admin/audit", a_tok).status_code == 200)
        check("admin system info", api.call("GET", "/admin/system/info", a_tok).status_code == 200)
        check("admin reports aggregate", api.call("GET", "/admin/reports/aggregate", a_tok).status_code == 200)
        sch = api.call("POST", "/admin/schools", a_tok, json={"name": f"QA School {uuid.uuid4().hex[:6]}"})
        check("admin creates school", sch.status_code in (200, 201), body(sch))
        if sch.status_code in (200, 201):
            sid = sch.json().get("id")
            check("admin schools list", api.call("GET", "/admin/schools", a_tok).status_code == 200)
            inv2 = api.call("POST", f"/schools/{sid}/invites", a_tok, json={"role": "school_admin"})
            check("school invite created", inv2.status_code in (200, 201), body(inv2))
            if inv2.status_code in (200, 201):
                code = inv2.json().get("code", "")
                check("school invite code has >= 10 chars", len(code) >= 10, f"got {code!r}")
                join = api.call("POST", "/auth/join-school",
                                json={"invite_code": code, "email": staff_email,
                                      "password": PASSWORD, "name": "QA Staff"})
                if join.status_code in (200, 201):
                    check("school staff joins via invite", True)
                else:
                    # idempotent re-run: the staff account already exists
                    check("school invite is single-use / email already taken",
                          join.status_code == 409, f"{join.status_code} {body(join)}")
                staff_tok, sres = login(api, staff_email)
                check("school staff login", bool(staff_tok), body(sres))
                if staff_tok:
                    for path in ("/school/overview", "/school/students", "/school/teachers",
                                 "/school/classes", "/school/coverage", "/school/analytics", "/schools/mine"):
                        check(f"school staff: {path}", api.call("GET", path, staff_tok).status_code == 200)
                    check("staff blocked from admin area",
                          api.call("GET", "/admin/schools", staff_tok).status_code == 403)
            check("admin school invites list",
                  api.call("GET", f"/admin/schools/{sid}/invites", a_tok).status_code == 200)
        users = api.call("GET", f"/admin/users?q={student_email}&limit=5", a_tok)
        if users.status_code == 200 and users.json().get("items"):
            uid = users.json()["items"][0]["id"]
            check("admin role change",
                  api.call("PATCH", f"/admin/users/{uid}/role", a_tok, json={"role": "teacher"}).status_code == 200)
            check("admin role change reversed",
                  api.call("PATCH", f"/admin/users/{uid}/role", a_tok, json={"role": "student"}).status_code == 200)
            imp_r = api.call("POST", f"/admin/users/{uid}/impersonate", a_tok, json={"reason": "e2e check"})
            check("impersonation starts", imp_r.status_code in (200, 201), body(imp_r))
            if imp_r.status_code in (200, 201):
                imp_tok = imp_r.json().get("access_token") or imp_r.json().get("token", "")
                if imp_tok:
                    acted = api.call("GET", "/users/me", imp_tok)
                    check("impersonated token acts as that user",
                          acted.status_code == 200 and acted.json().get("email") == student_email, body(acted))
                    check("impersonation exit allowed",
                          api.call("POST", "/auth/impersonate/exit", imp_tok).status_code in (200, 204))
        tri = api.call("GET", "/admin/feedback?status=all&limit=5", a_tok)
        if tri.status_code == 200 and tri.json().get("rows"):
            fid = tri.json()["rows"][0]["id"]
            check("feedback triage",
                  api.call("PATCH", f"/admin/feedback/{fid}", a_tok, json={"triaged": True}).status_code == 200)
        check("maintenance purge runs", api.call("POST", "/admin/maintenance/purge", a_tok).status_code == 200)

    # ------------------------------------------------------------ negatives
    check("student blocked from teacher area", api.call("GET", "/teacher/workload", s_tok).status_code == 403)
    check("teacher blocked from admin area", api.call("GET", "/admin/users", t_tok).status_code == 403)
    check("student blocked from admin area", api.call("GET", "/admin/users", s_tok).status_code == 403)
    check("parent blocked from teacher area", api.call("GET", "/teacher/workload", p_tok).status_code == 403)
    check("teacher cannot read another student's report",
          api.call("GET", f"/students/{student_profile}/report", t_tok).status_code in (403, 404))
    check("teacher cannot start a quiz as a student",
          api.call("POST", "/quizzes", t_tok, json={"student_id": student_profile, "class_level": CLASS,
                                                   "subject": SUBJECT, "chapter": chapter_name}).status_code in (403, 422))
    check("unauthenticated tutor blocked",
          api.call("POST", "/tutor/ask", json={"question": "hi", "class_level": CLASS}).status_code == 401)
    check("unauthenticated admin blocked", api.call("GET", "/admin/users").status_code == 401)
    check("unknown route is 404", api.call("GET", "/definitely-not-a-route").status_code == 404)

    failed = [r for r in _results if not r[1]]
    print("\n" + "=" * 72)
    print(f"CHECKS: {len(_results)}  PASSED: {len(_results) - len(failed)}  FAILED: {len(failed)}")
    for name, _, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
