"""BE-FIX-001..010: guards for the backend-integrity remediation.

One test per verified defect, each named after the finding it pins:

* BE-FIX-001 -- quiz submit is ONE transaction: a failure in the last
  learning-state write rolls the whole grading back (attempt stays ``open``,
  no answer log / counters / revision / mastery) and the retry succeeds.
* BE-FIX-002 -- chat turns authorize BEFORE the ledger reserve (a refused
  turn writes no ``ai_usage`` row), and the question-paper routes do not
  spend on a paper the caller does not own.
* BE-FIX-003 -- the document pipeline finalizes its reserved ledger row on
  every failure exit (provider failure, output-side safety refusal, unknown
  kind), and the input-side screen (before the reserve) creates no row at all.
* BE-FIX-004 -- a stale consent version gates generation and the
  student's data-collecting writes, leaves reads open, and cannot dead-end
  (the re-confirmation endpoint stays reachable).
* BE-FIX-005 -- the CSV classroom import records NO consent (NULL evidence,
  needs_reconfirm true) and the credential-bearing response is no-store.
* BE-FIX-007 -- /kg/rebuild needs an explicit confirmation and writes an
  audit row.
* BE-FIX-008 -- /tutor/ask books the COMPOSED prompt (system template +
  evidence budget + question), and an unpriced model is marked in the ledger
  instead of silently costing zero.
* BE-FIX-009 -- the erasure attempts-JSON prune reads in bounded batches and
  still prunes every row.
* BE-FIX-010 -- ``finalize_ai_usage(None)`` raises (docstring/behaviour agree).
* error contract -- the refusals these routes can return are declared in the
  served OpenAPI document.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    AiUsage,
    AnswerLog,
    Assignment,
    ChatMessage,
    ClassRoom,
    ConceptMastery,
    DailyActivity,
    QuizAttempt,
    RevisionItem,
    ShortTest,
    Student,
    StudentAbility,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.retrieval.context import EVIDENCE_TOKEN_BUDGET
from bangla_gpt_api.services.costs import (
    estimate_tokens,
    finalize_ai_usage,
    is_priced_model,
    ledger_model_name,
    record_ai_usage,
)
from bangla_gpt_api.services.gdpr import _strip_student_from_attempts_json
from bangla_gpt_api.services.tutor import SYSTEM_PROMPT
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
ADMIN_EMAIL = "root@example.com"
#: "কোষ কী?" -- a question the bundled sample corpus can serve.
QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"
CHAPTER = "\u0995\u09cb\u09b7"  # কোষ


def _settings(tmp_path, name: str = "integrity", **over) -> Settings:
    base = dict(
        env="test",
        database_url=engine_url(tmp_path, name),
        jwt_secret=SECRET,
        admin_email=ADMIN_EMAIL,
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    base.update(over)
    return Settings(**base)


class _App:
    """An app + its own session factory over the same test database."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.app = create_app(settings)
        self.factory = make_session_factory(make_engine(settings))
        self.client = TestClient(self.app)
        self.raw_client = TestClient(self.app, raise_server_exceptions=False)

    def ledger(self) -> list[AiUsage]:
        with self.factory() as db:
            return list(db.execute(select(AiUsage).order_by(AiUsage.id)).scalars())


def _make_app(tmp_path, name: str = "integrity", **over) -> _App:
    return _App(_settings(tmp_path, name, **over))


def _register(client: TestClient, email: str, role: str = "student") -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Test User", "role": role}
    if role == "student":
        payload.update({"guardian_consent": True, "class_level": 6})
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _student(client: TestClient, email: str) -> tuple[int, dict]:
    profile = _register(client, email, "student")
    return int(profile["profile_id"]), _headers(client, email)


def _admin_headers(client: TestClient) -> dict:
    return _headers(client, ADMIN_EMAIL)


def _count(factory, model, *where) -> int:
    with factory() as db:
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.where(*where)
        return int(db.execute(stmt).scalar_one())


# ------------------------------------------------------------------
# BE-FIX-001 -- one transaction per quiz submission
# ------------------------------------------------------------------


def test_quiz_submit_rolls_back_completely_when_a_later_write_fails(tmp_path, monkeypatch) -> None:
    env = _make_app(tmp_path, "atomic")
    student_id, headers = _student(env.client, "atomic@example.com")
    started = env.client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 3}, headers=headers
    )
    assert started.status_code == 200, started.text
    attempt_id = int(started.json()["attempt_id"])
    answers = [1] * len(started.json()["questions"])

    # The LAST learning-state write of the submit chain blows up after the
    # graded status, the answer log, the activity counters and the revision
    # queue have all been written inside the handler.
    from bangla_gpt_api.services import adaptive

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("elo store unavailable")

    monkeypatch.setattr(adaptive, "apply_review", _boom)

    failed = env.raw_client.post(
        f"/quizzes/{attempt_id}/submit", json={"answers": answers}, headers=headers
    )
    assert failed.status_code == 500, failed.text

    with env.factory() as db:
        attempt = db.get(QuizAttempt, attempt_id)
        assert attempt is not None
        assert attempt.status == "open", "a failed submit must not leave the attempt graded"
        assert attempt.score_pct is None
    assert _count(env.factory, AnswerLog) == 0, "answer log survived a failed submit"
    assert _count(env.factory, DailyActivity) == 0
    assert _count(env.factory, RevisionItem) == 0
    assert _count(env.factory, ConceptMastery) == 0
    assert _count(env.factory, StudentAbility) == 0

    # The retry path stays reachable (the pre-fix shape refused it with
    # attempt_already_graded against a status the child never finished).
    monkeypatch.undo()
    retry = env.client.post(
        f"/quizzes/{attempt_id}/submit", json={"answers": answers}, headers=headers
    )
    assert retry.status_code == 200, retry.text
    body = retry.json()
    assert body["total"] == 3 and body["correct"] == sum(
        1 for r in body["review"] if r["is_correct"]
    )

    with env.factory() as db:
        attempt = db.get(QuizAttempt, attempt_id)
        assert attempt is not None and attempt.status == "graded"
    assert _count(env.factory, AnswerLog) == 3
    assert _count(env.factory, DailyActivity) == 1
    assert _count(env.factory, RevisionItem) >= 1
    assert _count(env.factory, StudentAbility) >= 1


def test_quiz_submit_answer_count_mismatch_leaves_the_attempt_open(tmp_path) -> None:
    """Same invariant for the other pre-commit exit: the claim must roll back."""
    env = _make_app(tmp_path, "mismatch")
    student_id, headers = _student(env.client, "mismatch@example.com")
    started = env.client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 3}, headers=headers
    ).json()

    bad = env.client.post(
        f"/quizzes/{started['attempt_id']}/submit", json={"answers": [0]}, headers=headers
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "answer_count_mismatch"
    with env.factory() as db:
        attempt = db.get(QuizAttempt, int(started["attempt_id"]))
        assert attempt is not None and attempt.status == "open"

    good = env.client.post(
        f"/quizzes/{started['attempt_id']}/submit",
        json={"answers": [0] * len(started["questions"])},
        headers=headers,
    )
    assert good.status_code == 200, good.text


# ------------------------------------------------------------------
# BE-FIX-002 -- authorize before the AI budget reserve
# ------------------------------------------------------------------


def test_chat_turn_on_a_foreign_conversation_reserves_nothing(tmp_path) -> None:
    env = _make_app(tmp_path, "chatorder")
    _, owner_headers = _student(env.client, "owner@example.com")
    _, other_headers = _student(env.client, "other@example.com")
    conv = env.client.post("/tutor/conversations", json={"title": "mine"}, headers=owner_headers)
    assert conv.status_code == 201, conv.text
    conv_id = int(conv.json()["id"])

    refused = env.client.post(
        f"/tutor/conversations/{conv_id}/messages",
        json={"message": QUESTION},
        headers=other_headers,
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "not_allowed"
    assert env.ledger() == [], "a refused turn must not reserve (and commit) a ledger row"
    assert _count(env.factory, ChatMessage) == 0, "a refused turn must not store a message"

    missing = env.client.post(
        "/tutor/conversations/9999/messages", json={"message": QUESTION}, headers=other_headers
    )
    assert missing.status_code == 404
    assert env.ledger() == [], "an unknown conversation must not reserve a ledger row"


def test_answer_key_on_a_foreign_paper_reserves_nothing(tmp_path) -> None:
    """The same ordering on the document generators (BE-FIX-002 sweep)."""
    env = _make_app(tmp_path, "docorder")
    _register(env.client, "a@example.com", "teacher")
    a_headers = _headers(env.client, "a@example.com")
    _register(env.client, "b@example.com", "teacher")
    b_headers = _headers(env.client, "b@example.com")

    paper = env.client.post(
        "/teacher/qpapers",
        json={
            "class_level": 6,
            "subject": "science",
            "chapters": [CHAPTER],
            "marks": 10,
            "duration_min": 30,
            "exam_type": "unit",
            "difficulty": {"easy": 30, "medium": 40, "hard": 30},
        },
        headers=a_headers,
    )
    assert paper.status_code == 201, paper.text
    paper_id = int(paper.json()["id"])
    before = len(env.ledger())

    foreign = env.client.post(
        "/teacher/generate/answer_key",
        json={"class_level": 6, "subject": "science", "paper_id": paper_id},
        headers=b_headers,
    )
    assert foreign.status_code == 404, foreign.text
    assert len(env.ledger()) == before, "a foreign paper must not reserve a ledger row"


# ------------------------------------------------------------------
# BE-FIX-003 -- the document pipeline finalizes on every exit
# ------------------------------------------------------------------


def test_document_generation_finalizes_the_ledger_row_on_every_failure(
    tmp_path, monkeypatch
) -> None:
    env = _make_app(tmp_path, "docfail")
    _register(env.client, "doc@example.com", "teacher")
    headers = _headers(env.client, "doc@example.com")
    from bangla_gpt_api.providers import ProviderError
    from bangla_gpt_api.routers import _documents

    worksheet_body = {"class_level": 6, "subject": "science", "chapter": CHAPTER}

    # 1) provider failure: the reserve existed, so it must be finalized.
    async def _explode(*args: object, **kwargs: object):
        raise ProviderError("upstream down")

    monkeypatch.setattr(_documents, "generate_worksheet", _explode)
    res = env.client.post("/teacher/generate/worksheet", json=worksheet_body, headers=headers)
    assert res.status_code == 502, res.text
    rows = env.ledger()
    assert len(rows) == 1
    assert rows[0].route == "teacher/worksheet:failed"
    assert rows[0].prompt_tokens > 0 and rows[0].completion_tokens == 0

    # 2) the post-provider safety screen refuses after the reserve.
    real_screen = _documents._screen_free_text

    def _refuse_output(texts, *, where: str):
        if where.endswith("output"):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unsafe_content",
                    "message": "refused",
                    "reason": "self_harm",
                    "where": where,
                },
            )
        return real_screen(texts, where=where)

    async def _unsafe_payload(*args: object, **kwargs: object):
        return ({"questions": [{"question": "?"}]}, [])

    monkeypatch.setattr(_documents, "generate_worksheet", _unsafe_payload)
    monkeypatch.setattr(_documents, "_screen_free_text", _refuse_output)
    refused = env.client.post("/teacher/generate/worksheet", json=worksheet_body, headers=headers)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"]["code"] == "unsafe_content"
    rows = env.ledger()
    assert len(rows) == 2
    assert rows[-1].route == "teacher/worksheet:failed"
    assert rows[-1].completion_tokens == 0

    # 3) unknown kind on the shared runner (the AiJob path reaches it directly):
    #    the reserve is taken before the kind dispatch, so it must finalize.
    real_input_screen = _documents._screen_free_text

    def _pass_input(texts, *, where: str):
        if where.endswith("input"):
            return None
        return real_input_screen(texts, where=where)

    monkeypatch.setattr(_documents, "_screen_free_text", _pass_input)

    class _Gen:
        class_level = 6
        subject = "science"
        chapter = CHAPTER

    with env.factory() as db:
        actor = db.execute(select(User).where(User.email == "doc@example.com")).scalar_one()
        with pytest.raises(_documents.DocumentInputError) as exc:
            asyncio.run(
                _documents._generate_document(env.app.state.ctx, db, actor, "bogus", _Gen())
            )
        assert exc.value.code == "unknown_kind"
    rows = env.ledger()
    assert [r.route for r in rows] == [
        "teacher/worksheet:failed",
        "teacher/worksheet:failed",
        "teacher/bogus:failed",
    ]
    assert all(r.completion_tokens == 0 for r in rows)

    # 4) the INPUT screen refuses before the reserve exists -> nothing to
    #    finalize and no orphan row may be created.
    before = len(rows)

    def _refuse_input(texts, *, where: str):
        raise HTTPException(
            status_code=400,
            detail={"code": "unsafe_content", "message": "refused", "where": where},
        )

    monkeypatch.setattr(_documents, "_screen_free_text", _refuse_input)
    early = env.client.post("/teacher/generate/worksheet", json=worksheet_body, headers=headers)
    assert early.status_code == 400, early.text
    assert len(env.ledger()) == before, "a refusal before the reserve must not create a row"


# ------------------------------------------------------------------
# BE-FIX-004 -- the consent re-confirmation flag is a control
# ------------------------------------------------------------------


def test_stale_consent_gates_writes_and_generation_but_not_reconfirmation(tmp_path) -> None:
    env = _make_app(tmp_path, "consentgate")
    student_id, headers = _student(env.client, "consent@example.com")

    # Current version: generation works.
    ok = env.client.post(
        "/tutor/ask", json={"question": QUESTION, "class_level": 6}, headers=headers
    )
    assert ok.status_code == 200, ok.text

    # A consent-version bump leaves this student behind (the documented
    # "previously-consented students become needs_reconfirm" flow).
    with env.factory() as db:
        student = db.get(Student, student_id)
        assert student is not None
        student.consent_version = "2026-07-v1"
        db.commit()

    blocked = env.client.post(
        "/tutor/ask", json={"question": QUESTION, "class_level": 6}, headers=headers
    )
    assert blocked.status_code == 403, blocked.text
    detail = blocked.json()["detail"]
    assert detail["code"] == "consent_reconfirmation_required"
    assert f"/students/{student_id}/consent/reconfirm" in detail["message"], "dead end"

    quiz = env.client.post(
        "/quizzes", json={"student_id": student_id, "num_questions": 3}, headers=headers
    )
    assert quiz.status_code == 403
    assert quiz.json()["detail"]["code"] == "consent_reconfirmation_required"
    assert _count(env.factory, QuizAttempt) == 0

    progress = env.client.post(
        "/learn/progress",
        json={"subject": "science", "chapter": CHAPTER, "class_level": 6, "read_pct": 10},
        headers=headers,
    )
    assert progress.status_code == 403

    # Reads stay open while a re-confirmation is pending.
    assert env.client.get(f"/students/{student_id}/progress", headers=headers).status_code == 200

    # Not a dead end: the re-confirmation endpoint is reachable and lifts the
    # gate.
    status = env.client.get(f"/students/{student_id}/consent", headers=headers)
    assert status.status_code == 200
    assert status.json()["needs_reconfirm"] is True
    reconfirm = env.client.post(
        f"/students/{student_id}/consent/reconfirm", json={"accepted": True}, headers=headers
    )
    assert reconfirm.status_code == 200, reconfirm.text
    assert reconfirm.json()["needs_reconfirm"] is False
    after = env.client.post(
        "/tutor/ask", json={"question": QUESTION, "class_level": 6}, headers=headers
    )
    assert after.status_code == 200, after.text


def test_freshly_registered_student_is_not_gated(tmp_path) -> None:
    """Negative control: the gate must not block the ordinary flow."""
    env = _make_app(tmp_path, "consentfresh")
    student_id, headers = _student(env.client, "fresh@example.com")
    assert (
        env.client.post(
            "/quizzes", json={"student_id": student_id, "num_questions": 2}, headers=headers
        ).status_code
        == 200
    )
    assert env.client.get("/tutor/conversations", headers=headers).status_code == 200


# ------------------------------------------------------------------
# BE-FIX-005 -- the CSV import records pending consent, no fabricated data
# ------------------------------------------------------------------


def test_csv_import_records_no_consent_and_serves_no_store(tmp_path) -> None:
    env = _make_app(tmp_path, "csvconsent")
    _register(env.client, "teach@example.com", "teacher")
    headers = _headers(env.client, "teach@example.com")
    room = env.client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=headers
    )
    assert room.status_code == 201, room.text
    room_id = int(room.json()["id"])

    imported = env.client.post(
        f"/teacher/classrooms/{room_id}/import",
        json={"csv_text": "name,email\nRahim,rahim@school.edu\n"},
        headers=headers,
    )
    assert imported.status_code == 200, imported.text
    assert imported.headers.get("cache-control") == "no-store", "credential-bearing body cached"
    code = imported.json()["rows"][0]["invite_code"]
    assert code

    with env.factory() as db:
        student = db.execute(select(Student).where(Student.name == "Rahim")).scalar_one()
        assert student.consent_version is None, "import must not fabricate a consent version"
        assert student.consent_at is None
        assert student.consent_ip is None
        sid = student.id

    # The computed flag the gate reads: needs_reconfirm is true and no
    # accepted version exists.
    consent = env.client.get(f"/students/{sid}/consent", headers=_admin_headers(env.client))
    assert consent.status_code == 200, consent.text
    assert consent.json()["needs_reconfirm"] is True
    assert consent.json()["accepted_version"] is None

    # The one-time code still signs the imported child in (no behaviour
    # regression on the account-onboarding path).
    login = env.client.post("/auth/login", json={"email": "rahim@school.edu", "password": code})
    assert login.status_code == 200, login.text
    assert login.json()["must_change_password"] is True


# ------------------------------------------------------------------
# BE-FIX-007 -- /kg/rebuild is confirmed and audited
# ------------------------------------------------------------------


def test_kg_rebuild_requires_confirmation_and_writes_an_audit_row(tmp_path) -> None:
    env = _make_app(tmp_path, "kgrebuild")
    student_id, student_headers = _student(env.client, "kg@example.com")
    assert env.client.post("/kg/rebuild", headers=student_headers).status_code == 403

    admin = _admin_headers(env.client)
    refused = env.client.post("/kg/rebuild", headers=admin)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"]["code"] == "kg_rebuild_confirmation_required"

    rebuilt = env.client.post("/kg/rebuild?confirm=true", headers=admin)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["concepts"] > 0

    audit = env.client.get("/admin/audit?action=kg_rebuild", headers=admin)
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["total"] == 1, "the destructive rebuild must leave exactly one trail row"
    row = body["rows"][0]
    assert row["target"] == "knowledge_graph"
    assert set(row["detail"]) >= {"concepts", "llm_concepts", "edges", "llm_requested"}
    assert student_id  # the student's own account never reached this route


# ------------------------------------------------------------------
# BE-FIX-008 -- the ledger books the composed prompt, unpriced models shout
# ------------------------------------------------------------------


def test_ask_books_the_composed_prompt_not_the_bare_question(tmp_path) -> None:
    env = _make_app(tmp_path, "promptacct")
    _student(env.client, "prompt@example.com")
    headers = _headers(env.client, "prompt@example.com")

    res = env.client.post(
        "/tutor/ask", json={"question": QUESTION, "class_level": 6}, headers=headers
    )
    assert res.status_code == 200, res.text

    rows = env.ledger()
    assert len(rows) == 1
    expected = estimate_tokens(SYSTEM_PROMPT) + EVIDENCE_TOKEN_BUDGET + estimate_tokens(QUESTION)
    assert rows[0].prompt_tokens == expected
    bare = estimate_tokens(QUESTION)
    assert rows[0].prompt_tokens > 100 * bare, (
        "the bare-question under-count (BE-FIX-008) is back: "
        f"{rows[0].prompt_tokens} vs bare {bare}"
    )
    assert rows[0].model == "mock", "a priced model must not be marked unpriced"
    assert rows[0].completion_tokens > 0


def test_ledger_model_name_marks_only_unpriced_models() -> None:
    """Readable guard: the marker is a suffix on the stored model cell."""
    assert ledger_model_name("mock") == "mock"
    assert is_priced_model("mock") is True
    assert is_priced_model("gpt-4o-mini") is True
    assert is_priced_model("gpt-9-unknown") is False


def test_unpriced_model_is_marked_in_the_ledger(tmp_path) -> None:
    env = _make_app(tmp_path, "unpriced")
    student_id, _ = _student(env.client, "unpriced@example.com")

    marked = ledger_model_name("gpt-9-unknown")
    assert marked == "gpt-9-unknown [unpriced]"
    assert ledger_model_name(marked) == marked, "reserve -> finalize must not double-mark"

    with env.factory() as db:
        row = record_ai_usage(
            db,
            user_id=student_id,
            route="tutor.ask",
            model="gpt-9-unknown",
            prompt_text="x" * 400,
            answer_text=None,
        )
        db.commit()
        assert row.model == marked
        assert float(row.estimated_cost_usd) == 0.0
        # The finalize path must keep the marker (the reserve -> finalize pair
        # writes the same cell twice).
        finalize_ai_usage(db, row, model="gpt-9-unknown", answer_text="y" * 400)
        db.commit()
        assert row.model == marked


# ------------------------------------------------------------------
# BE-FIX-009 -- the erasure attempts-JSON prune is bounded
# ------------------------------------------------------------------


def test_attempts_json_prune_is_batched_and_still_complete(tmp_path) -> None:
    env = _make_app(tmp_path, "prunebatch")
    _register(env.client, "owner@example.com", "teacher")
    headers = _headers(env.client, "owner@example.com")
    room = env.client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=headers
    )
    assert room.status_code == 201, room.text
    room_id = int(room.json()["id"])
    # More rows than one read/write batch (gdpr._ERASURE_PRUNE_BATCH = 200).
    rows = 250
    erased_student, kept_student = 4242, 4243

    with env.factory() as db:
        teacher = db.execute(select(User).where(User.email == "owner@example.com")).scalar_one()
        classroom = db.get(ClassRoom, room_id)
        assert classroom is not None
        now = datetime.now(UTC).replace(tzinfo=None)
        for i in range(rows):
            db.add(
                Assignment(
                    teacher_id=teacher.id,
                    subject="science",
                    chapter="ch",
                    due_at=now,
                    attempts=[
                        {"student_id": erased_student, "attempt_id": i},
                        {"student_id": kept_student, "attempt_id": i},
                    ],
                )
            )
            db.add(
                ShortTest(
                    classroom_id=classroom.id,
                    teacher_id=teacher.id,
                    subject="science",
                    chapter="ch",
                    attempts=[
                        {"student_id": erased_student, "attempt_id": i},
                        {"student_id": kept_student, "attempt_id": i},
                    ],
                )
            )
        db.commit()
        _strip_student_from_attempts_json(db, erased_student)
        db.commit()

        for model in (Assignment, ShortTest):
            stored = list(db.execute(select(model)).scalars())
            assert len(stored) == rows
            assert all(
                all(str(e.get("student_id")) != str(erased_student) for e in r.attempts)
                for r in stored
            ), f"{model.__name__}: an erased reference survived the batched prune"
            assert all(
                any(str(e.get("student_id")) == str(kept_student) for e in r.attempts)
                for r in stored
            ), f"{model.__name__}: another student's history was pruned"


# ------------------------------------------------------------------
# BE-FIX-010 -- finalize_ai_usage agrees with its docstring
# ------------------------------------------------------------------


def test_finalize_ai_usage_requires_a_reserved_row(tmp_path) -> None:
    env = _make_app(tmp_path, "finalize")
    _student(env.client, "finalize@example.com")
    with env.factory() as db:
        with pytest.raises(ValueError):
            finalize_ai_usage(db, None, model="mock", answer_text="answer")


# ------------------------------------------------------------------
# error contract -- the refusals these routes can return are declared
# ------------------------------------------------------------------


def test_owned_routes_declare_the_refusals_they_raise(tmp_path) -> None:
    env = _make_app(tmp_path, "contract")
    spec = env.app.openapi()
    paths = spec["paths"]

    def responses(method: str, path: str) -> dict:
        return paths[path][method]["responses"]

    assert "502" in responses("post", "/tutor/ask")
    assert "400" in responses("post", "/quizzes/{attempt_id}/submit")
    assert "404" in responses("post", "/quizzes/{attempt_id}/submit")
    refused_body = responses("post", "/quizzes/{attempt_id}/submit")["404"]
    assert refused_body["content"]["application/json"]["schema"]["$ref"].endswith("CodedDetail")
    assert "503" in responses("get", "/search")
    assert "422" in responses("get", "/search")
    assert "400" in responses("post", "/kg/rebuild")
    assert "404" in responses("post", "/teacher/classrooms/{room_id}/import")
    assert "422" in responses("post", "/teacher/classrooms/{room_id}/import")
    assert "404" in responses("delete", "/teacher/documents/{document_id}")
    confirm = [
        p for p in paths["/kg/rebuild"]["post"].get("parameters", []) if p["name"] == "confirm"
    ]
    assert confirm, "/kg/rebuild must document its explicit confirmation flag"
