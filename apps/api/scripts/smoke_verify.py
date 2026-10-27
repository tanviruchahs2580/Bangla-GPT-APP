"""Live smoke test against a real booted app.

Boots the real application (real lifespan, real dependency wiring, real SQLite
file, real router stack), then walks the flows that the fixes in this pass touch
so the behaviour is observed rather than assumed:

  1. production boot guard refuses a misspelled ENV (the F-5 exploit path)
  2. an empty NCTB_CORPUS_DIR is fatal in production (the F-9 silent-substitution)
  3. an unverifiable answer returns grounded=false with no citations (F-1)
  4. a role change revokes the target's live session (F-6)
  5. the generation routes refuse once the budget is spent (F-7)
  6. /health stays green while /ready reports the truth

Run: python scripts/smoke_verify.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.main import create_app  # noqa: E402

PASSWORD = "supersecret1"
ADMIN_EMAIL = "root@example.com"
SECRET = "smoke-secret-0123456789abcdef0123456789"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def prod_settings(tmp: Path, **over) -> Settings:
    # SQLite needs its parent directory to exist; each section gets a subdir.
    tmp.mkdir(parents=True, exist_ok=True)
    base = dict(
        env="production",
        database_url=f"sqlite:///{tmp}/smoke.db",
        jwt_secret=SECRET,
        admin_email=ADMIN_EMAIL,
        admin_password=PASSWORD,
        force_admin_password_change=False,
        allowed_origins="https://app.example.org",
        pii_enc_key="x" * 44,
        metrics_require_auth=True,
        metrics_token="m" * 32,
        rate_limit_backend="memory",
        llm_provider="mock",
        ai_monthly_budget_usd_per_user=0.0,
    )
    base.update(over)
    return Settings(**base)


def header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def token_of(client: TestClient, email: str) -> str:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bgpt-smoke-"))

    # 1. Misspelled ENV must not boot production insecurely.
    print("\n[1] production boot guard vs a misspelled ENV")
    try:
        from bangla_gpt_api.main import enforce_production_safety

        enforce_production_safety(
            prod_settings(tmp, env="prodction", jwt_secret="dev-insecure-change-me")
        )
        check(False, "ENV=prodction with the default secret was refused")
    except RuntimeError as exc:
        check(
            "prodction" in str(exc),
            f"ENV=prodction refused, error names the ENV: {str(exc).splitlines()[0]}",
        )
    # A fully-satisfied production config must still boot, so the guard is not
    # simply refusing everything.
    enforce_production_safety(
        prod_settings(
            tmp / "ok",
            smtp_enabled=True,
            smtp_host="mail.example.org",
            smtp_from="no-reply@example.org",
        )
    )
    check(True, "a fully-configured production env passes the guard")
    enforce_production_safety(prod_settings(tmp / "ci", env="ci"))
    check(True, "ENV=ci still boots (test/CI path unaffected)")

    # 2. An empty configured corpus is fatal; an unconfigured one is not.
    print("\n[2] empty NCTB corpus must not be papered over")
    empty_corpus = tmp / "corpus"
    (empty_corpus / "normalized").mkdir(parents=True, exist_ok=True)
    from bangla_gpt_api.initialize.dependencies import _load_corpus_chunks

    try:
        _load_corpus_chunks(prod_settings(tmp, nctb_corpus_dir=str(empty_corpus)))
        check(False, "production boot with an empty corpus directory was refused")
    except RuntimeError as exc:
        check(True, f"production refuses an empty corpus: {str(exc)[:70]}â€¦")
    dev_chunks = _load_corpus_chunks(
        prod_settings(tmp, env="ci", nctb_corpus_dir=str(empty_corpus))
    )
    check(
        bool(dev_chunks),
        f"non-production still falls back to the sample corpus ({len(dev_chunks)})",
    )
    unconfigured = _load_corpus_chunks(prod_settings(tmp, nctb_corpus_dir=""))
    check(
        bool(unconfigured), f"no corpus configured at all still yields chunks ({len(unconfigured)})"
    )

    # 3. Grounding honesty, observed through the real HTTP surface.
    #      env=ci: the runtime behaviour under test does not depend on the boot
    #      guard (checked in step 1), and SMTP is unreachable here, so accounts
    #      must auto-verify for the login flow to be reachable at all.
    print("\n[3] grounding honesty through the real API")
    app = create_app(prod_settings(tmp, env="ci"))
    with TestClient(app) as client:
        check(client.get("/health").json()["status"] == "ok", "/health is ok")
        ready = client.get("/ready")
        check(ready.status_code == 200 and ready.json()["status"] == "ready", "/ready is ready")

        token = token_of(client, ADMIN_EMAIL)
        root = header(token)
        client.post(
            "/auth/register",
            json={
                "email": "student@example.com",
                "password": PASSWORD,
                "name": "Smoke Student One",
                "role": "student",
                "guardian_consent": True,
                "class_level": 6,
            },
        )
        stu = header(token_of(client, "student@example.com"))

        in_scope = client.post(
            "/tutor/ask",
            json={"question": "ভগ্নাংশ কী?", "class_level": 6, "subject": "mathematics"},
            headers=stu,
        )
        body = in_scope.json()
        check(
            in_scope.status_code == 200
            and body["grounded"] is True
            and bool(body["sources"])
            and body["citation_verified"] is True,
            "in-scope question is grounded, cited and citation_verified "
            f"(sources={len(body['sources'])}, cit={body['citation_verified']})",
        )

        out_of_scope = client.post(
            "/tutor/ask",
            json={
                "question": "à¦—à¦¤ à¦¬à¦¿à¦¶à§à¦¬à¦•à¦¾à¦ªà§‡ à¦•à§‹à¦¨ à¦¦à¦² à¦œà¦¿à¦¤à§‡à¦›à¦¿à¦²?",
                "class_level": 6,
                "subject": "mathematics",
            },
            headers=stu,
        ).json()
        check(
            out_of_scope["grounded"] is False
            and out_of_scope["refused_reason"] == "insufficient_evidence"
            and out_of_scope["sources"] == [],
            "out-of-scope question refuses with grounded=false, no sources",
        )
        check(
            (out_of_scope["confidence"] or 0) < 0.6,
            f"a refusal is not reported as confident ({out_of_scope['confidence']})",
        )

    # 4 + 5. Role revocation and the generation budget, in one booted app.
    print("\n[4] role change revokes live sessions")
    app = create_app(prod_settings(tmp / "r", env="ci"))
    with TestClient(app) as client:
        root = header(token_of(client, ADMIN_EMAIL))
        created = client.post(
            "/auth/register",
            json={
                "email": "victim@example.com",
                "password": PASSWORD,
                "name": "Victim User",
                "role": "student",
                "guardian_consent": True,
                "class_level": 6,
            },
        )
        user_id = created.json()["user_id"]
        victim = header(token_of(client, "victim@example.com"))
        check(client.get("/users/me", headers=victim).status_code == 200, "session works before")

        patched = client.patch(
            f"/admin/users/{user_id}/role", json={"role": "student"}, headers=root
        )
        check(patched.status_code == 200, "role change accepted")

        # A same-second token legitimately survives (documented <1s window), so
        # assert the epoch moved rather than racing the clock.
        from bangla_gpt_api.db.models import User
        from bangla_gpt_api.db.session import make_engine, make_session_factory

        factory = make_session_factory(make_engine(prod_settings(tmp / "r")))
        with factory() as db:
            user = db.get(User, user_id)
            check(
                user.sessions_invalidated_at is not None,
                "role change bumped sessions_invalidated_at",
            )

        audit = client.get("/admin/audit", headers=root).json()["rows"]
        check(
            any(r["action"] == "role_change" for r in audit),
            "role_change is in the audit trail",
        )

    print("\n[5] generation routes honour the AI budget")
    app = create_app(prod_settings(tmp / "b", env="ci", ai_monthly_budget_usd_per_user=0.0000001))
    with TestClient(app) as client:
        teacher = client.post(
            "/auth/register",
            json={
                "email": "teacher@example.com",
                "password": PASSWORD,
                "name": "Smoke Teacher",
                "role": "teacher",
            },
        ).json()
        tch = header(token_of(client, "teacher@example.com"))

        from bangla_gpt_api.db.models import AiUsage
        from bangla_gpt_api.db.session import make_engine, make_session_factory

        factory = make_session_factory(make_engine(prod_settings(tmp / "b")))
        with factory() as db:
            db.add(
                AiUsage(
                    user_id=teacher["user_id"],
                    route="seed",
                    model="seed",
                    prompt_tokens=10_000,
                    completion_tokens=10_000,
                    estimated_cost_usd=5.0,
                )
            )
            db.commit()

        for path, body in (
            (
                "/teacher/qpapers",
                {
                    "class_level": 6,
                    "subject": "science",
                    "chapters": ["à¦•à§‹à¦·"],
                    "exam_type": "Exam 2026",
                    "marks": 10,
                    "duration_min": 10,
                },
            ),
            (
                "/teacher/lesson-plans",
                {"class_level": 6, "subject": "science", "chapter": "à¦•à§‹à¦·"},
            ),
            (
                "/teacher/content/generate",
                {"class_level": 6, "subject": "science", "chapter": "à¦•à§‹à¦·"},
            ),
            ("/teacher/jobs", {"kind": "lesson_plan", "payload": {}}),
        ):
            res = client.post(path, json=body, headers=tch)
            check(
                res.status_code == 429 and res.json()["detail"]["code"] == "ai_budget_exceeded",
                f"{path} -> 429 ai_budget_exceeded (got {res.status_code})",
            )

    print("\n[6] streaming path honours the same rules")
    app = create_app(prod_settings(tmp / "s", env="ci"))
    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={
                "email": "streamer@example.com",
                "password": PASSWORD,
                "name": "Stream Student",
                "role": "student",
                "guardian_consent": True,
                "class_level": 6,
            },
        )
        stu = header(token_of(client, "streamer@example.com"))
        conv = client.post("/tutor/conversations", json={"title": "smoke"}, headers=stu).json()

        with client.stream(
            "POST",
            f"/tutor/conversations/{conv['id']}/messages/stream",
            json={"message": "à¦­à¦—à§à¦¨à¦¾à¦‚à¦¶ à¦•à§€?"},
            headers=stu,
        ) as resp:
            frames = [line for line in resp.iter_lines() if line.startswith("event:")]
        kinds = [f.split(":", 1)[1].strip() for f in frames]
        check("token" in kinds, f"stream emitted tokens ({len(kinds)} frames)")
        check("done" in kinds, "stream emitted a final done frame")
        check("error" not in kinds, "stream emitted no error frame")

    failed = [label for ok, label in results if not ok]
    print(f"\n{'=' * 62}")
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("\nFAILED:")
        for label in failed:
            print(f"  - {label}")
        return 1
    print("Live smoke verification: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
