"""Learn Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from bangla_gpt_api import caching
from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.db.models import (
    AnswerLog,
    ChapterProgress,
    ClassStudent,
    ClassTeacher,
    QuizAttempt,
    RevisionItem,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.retrieval.normalize import normalize_nfkc
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded, message
from bangla_gpt_api.schemas import (
    SMALL_PAGE_DEFAULT_LIMIT,
    SMALL_PAGE_MAX_LIMIT,
    ActivitySummary,
    ChapterProgressIn,
    ChapterProgressOut,
    ContinueLearning,
    DashboardSummary,
    KgGapOut,
    KgGapsOut,
    KgRebuildOut,
    QuickAction,
    QuizQuestionPublic,
    QuizResult,
    QuizStarted,
    QuizStartRequest,
    QuizSubmitRequest,
    Recommendation,
    ReteachCardOut,
    ReviewItem,
    RevisionDueOut,
    RevisionItemOut,
    RevisionReviewIn,
    SearchHit,
    SearchResponse,
    StudentProgress,
    StudentResponse,
)
from bangla_gpt_api.security import write_audit
from bangla_gpt_api.services import (
    adaptive,
    knowledge,
    revision,
    weakness,
)
from bangla_gpt_api.services.activity import (
    activity_summary,
    dhaka_date,
    graded_attempt_stats,
    record_activity,
    sorted_chapter_stats,
)
from bangla_gpt_api.services.learn import (
    ChapterContentOut,
    ChapterSummaryOut,
    SubjectOut,
    chapter_content,
    list_subjects,
    subject_chapters,
)
from bangla_gpt_api.services.quiz import ClozeQuizGenerator, dump_quiz

from .common import (
    _is_question_like,
    _student_profile,
    canonical_subject,
)
from .deps import (
    AdminUser,
    Ctx,
    CurrentUser,
    DbSession,
    _build_me_response,
    authorize_student_access,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)

#: Roles whose in-school scope passes ``authorize_student_access`` (reads AND
#: writes). The submission gate below narrows the WRITE case.
_STAFF_ROLES = ("teacher", "admin", "school_admin")


def _staff_classroom_assigned(db: Session, user: User, student_id: int) -> bool:
    """True when this teacher is an assigned ClassTeacher of a classroom the
    student is enrolled in ('' subject covers all). One EXISTS probe."""
    probe = (
        select(ClassStudent.student_id)
        .join(ClassTeacher, ClassTeacher.classroom_id == ClassStudent.classroom_id)
        .join(Teacher, Teacher.id == ClassTeacher.teacher_id)
        .where(ClassStudent.student_id == student_id, Teacher.user_id == user.id)
        .exists()
    )
    return db.scalar(select(probe)) is True


def _authorize_quiz_submission(db: Session, attempt: QuizAttempt, user: User) -> None:
    """Writes to a student's attempt are the student's own act (audit B-07).

    ``authorize_student_access`` is the READ/WRITE gate for progress and
    profile surfaces -- in-school staff pass it for a student's data, and
    nothing distinguished a read from a teacher CHOOSING ANSWERS on behalf
    of an account-holding student, silently moving the child out of the
    at-risk bucket the weak-matrix, support plans, parent digests and
    government reports all read. Submission writes now split:

    * the owning student always may submit their own attempt;
    * staff act only for the proctored roster: students with no login of
      their own (``user_id IS NULL``, the CSV-import paper flow), or the
      classroom's own assigned teacher (ClassTeacher -- minted at
      ``POST /teacher/classrooms``), and school admins -- every such proxy
      submission lands in the audit trail (action=quiz_proxy_submit);
    * a teacher outside the classroom is a coded 403.
    """
    student = authorize_student_access(db, attempt.student_id, user)
    if user.role not in _STAFF_ROLES:
        return
    write_audit(
        db,
        action="quiz_proxy_submit",
        actor_user_id=user.id,
        actor_role=user.role,
        target=f"quiz_attempt:{attempt.id}",
        detail={"student_id": student.id, "attempt_id": attempt.id},
    )
    if student.user_id is None:
        return  # proctored roster: no login exists, staff hands the paper in
    if user.role == "teacher" and not _staff_classroom_assigned(db, user, student.id):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "staff_cannot_submit_student_quiz",
                "message": "Only the student or their class teacher can submit this attempt",
            },
        )


@router.get("/learn/subjects", response_model=list[SubjectOut])
def learn_subjects(
    app_ctx: Ctx,
    user: CurrentUser,
    class_level: int | None = Query(default=None),
) -> list[SubjectOut]:
    # the tutor's actual loaded corpus (real NCTB corpus when configured),
    # so Learn lists exactly the content the tutor can cite.
    return list_subjects(class_level, chunks=_index_chunks(app_ctx))


@router.get("/learn/subjects/{subject}/chapters", response_model=list[ChapterSummaryOut])
def learn_subject_chapters(
    app_ctx: Ctx,
    subject: str,
    user: CurrentUser,
    class_level: int | None = Query(default=None),
) -> list[ChapterSummaryOut]:
    chapters = subject_chapters(subject, class_level, chunks=_index_chunks(app_ctx))
    if not chapters:
        raise HTTPException(
            status_code=404, detail={"code": "subject_not_found", "message": "Subject not found"}
        )
    return chapters


@router.get("/learn/subjects/{subject}/chapters/{chapter}", response_model=ChapterContentOut)
def learn_chapter_content(
    app_ctx: Ctx,
    subject: str,
    chapter: str,
    user: CurrentUser,
    class_level: int | None = Query(default=None),
) -> ChapterContentOut:
    content = chapter_content(subject, class_level, chapter, chunks=_index_chunks(app_ctx))
    if content is None:
        raise HTTPException(
            status_code=404, detail={"code": "chapter_not_found", "message": "Chapter not found"}
        )
    return content


def _index_chunks(app_ctx: Ctx) -> list[Chunk] | None:
    """The corpus the retrieval index serves, or None without an index."""
    return app_ctx.index.chunks if app_ctx.index is not None else None


# --- school tenancy helpers -----------------------------------------
# Tenancy anchor is User.school_id. A student belongs to a school EXACTLY
# when one of their ClassRoom memberships carries that school_id. A teacher
# WITHOUT a school keeps the pre-Wave-2 behavior (no tenancy wall) so every
# standalone-teacher flow stays byte-compatible; once a teacher is attached
# to a school, students and classrooms of OTHER schools become invisible
# (403 other_school, same code the /school/* routes use).
@router.post("/quizzes", response_model=QuizStarted)
def start_quiz(
    app_ctx: Ctx, payload: QuizStartRequest, db: DbSession, user: CurrentUser
) -> QuizStarted:
    if app_ctx.index is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
        )
    student = authorize_student_access(db, payload.student_id, user)
    class_level = payload.class_level if payload.class_level is not None else student.class_level

    attempt = QuizAttempt(student_id=student.id, subject=payload.subject, class_level=class_level)
    db.add(attempt)
    db.flush()

    generator = ClozeQuizGenerator(app_ctx.index.chunks)
    # generate a wider pool, then hand the student the questions
    # whose rated difficulty sits nearest ability + 0.5 sigma.
    pool = generator.generate(
        class_level=class_level,
        subject=canonical_subject(payload.subject),
        chapter=payload.chapter,
        num=min(payload.num_questions * adaptive.POOL_MULTIPLIER, adaptive.POOL_CAP),
        seed=attempt.id,
    )
    questions = adaptive.pick_questions(
        db,
        pool,
        student_id=student.id,
        subject=canonical_subject(payload.subject),
        class_level=class_level,
        num=payload.num_questions,
    )
    if not questions:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_quiz_for_filter",
                "message": "No quiz could be generated for this class/subject yet",
            },
        )

    attempt.quiz_json = dump_quiz(questions)
    db.commit()

    note: str | None = None
    if len(questions) < payload.num_questions:
        # A4: never silently short-change the caller — surface a code the
        # UI can translate into an honest, localized notice.
        note = f"partial_quiz:{len(questions)}"

    return QuizStarted(
        attempt_id=attempt.id,
        requested=payload.num_questions,
        note=note,
        questions=[
            QuizQuestionPublic(id=q.id, question_text=q.question_text, options=list(q.options))
            for q in questions
        ],
        # open KG gaps arrive as re-teach cards BEFORE the next Q.
        reteach=[
            ReteachCardOut(**card)
            for card in adaptive.open_reteach_cards(db, app_ctx.index.chunks, student.id)
        ],
    )


@router.post("/quizzes/{attempt_id}/submit", response_model=QuizResult, responses=message(404))
def submit_quiz(
    app_ctx: Ctx, attempt_id: int, payload: QuizSubmitRequest, db: DbSession, user: CurrentUser
) -> QuizResult:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(
            status_code=404, detail={"code": "attempt_not_found", "message": "Attempt not found"}
        )
    _authorize_quiz_submission(db, attempt, user)

    # Atomic claim: exactly one concurrent submission may transition
    # open -> graded. Losers get a clean 400 instead of corrupting state.
    claim_stmt = (
        update(QuizAttempt)
        .where(QuizAttempt.id == attempt.id, QuizAttempt.status == "open")
        .values(status="graded")
    )
    claimed = cast(CursorResult[Any], db.execute(claim_stmt))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail={"code": "attempt_already_graded", "message": "Attempt already graded"},
        )

    questions = list(attempt.quiz_json)
    if len(payload.answers) != len(questions):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "answer_count_mismatch",
                "message": "Answer count does not match question count",
                "expected": len(questions),
                "received": len(payload.answers),
            },
        )

    correct = 0
    review: list[ReviewItem] = []
    for seq, (question, chosen) in enumerate(zip(questions, payload.answers, strict=True)):
        is_correct = chosen == question["answer_index"]
        correct += is_correct
        db.add(
            AnswerLog(
                attempt_id=attempt.id,
                seq=seq,
                question_text=question["question_text"],
                chosen=chosen,
                correct_index=question["answer_index"],
                is_correct=is_correct,
                chapter=question["chapter"],
                book=question["book"],
            )
        )
        review.append(
            ReviewItem(
                question_text=question["question_text"],
                options=list(question["options"]),
                chosen=chosen,
                correct_index=question["answer_index"],
                is_correct=is_correct,
                chapter=question["chapter"],
            )
        )

    total = len(questions)
    attempt.status = "graded"
    attempt.total = total
    attempt.correct = correct
    attempt.score_pct = round(100.0 * correct / total, 2)
    db.commit()
    record_activity(db, attempt.student_id, quizzes=1, minutes=1)
    # quiz outcomes seed/refresh the spaced-revision queue.
    revision.record_quiz_result(
        db, attempt.student_id, review, attempt.subject, attempt.class_level
    )
    # the same graded answers update per-concept mastery in the
    # knowledge graph (chapter roots seeded lazily from the curriculum).
    reteach_cards: list[ReteachCardOut] = []
    if app_ctx.index is not None:
        knowledge.ensure_concepts(db, app_ctx.index.chunks)
        knowledge.record_quiz_result(db, attempt.student_id, review, attempt.class_level)
        # Elo ratings follow the graded answers; every wrong answer
        # runs the KG gap check, and surfaced gaps become re-teach cards.
        adaptive.apply_review(
            db,
            student_id=attempt.student_id,
            class_level=attempt.class_level,
            graded=[
                (str(question["id"]), question["chapter"], item.is_correct)
                for question, item in zip(questions, review, strict=True)
            ],
        )
        reteach_cards = [
            ReteachCardOut(**card)
            for card in adaptive.wrong_answer_reteach_cards(
                db,
                app_ctx.index.chunks,
                attempt.student_id,
                [
                    question["chapter"]
                    for question, item in zip(questions, review, strict=True)
                    if not item.is_correct
                ],
            )
        ]

    return QuizResult(
        attempt_id=attempt.id,
        score_pct=attempt.score_pct,
        correct=correct,
        total=total,
        review=review,
        reteach=reteach_cards,
    )


@router.get("/students/{student_id}/progress", response_model=StudentProgress)
def get_progress(student_id: int, db: DbSession, user: CurrentUser) -> StudentProgress:
    student = authorize_student_access(db, student_id, user)

    # SQL aggregates instead of full-history Python loops (shape preserved)
    graded_count, avg_score_raw = db.execute(
        select(func.count(), func.avg(QuizAttempt.score_pct)).where(
            QuizAttempt.student_id == student_id,
            QuizAttempt.status == "graded",
            QuizAttempt.score_pct.is_not(None),
        )
    ).one()
    attempts_graded = int(graded_count)
    avg_score = round(float(avg_score_raw), 2) if avg_score_raw is not None else None

    from sqlalchemy import Integer
    from sqlalchemy import cast as _cast

    # Per-chapter accuracy via GROUP BY (one query, not N rows + Python)
    g_rows = db.execute(
        select(
            AnswerLog.chapter,
            func.count().label("asked"),
            func.sum(_cast(AnswerLog.is_correct, Integer)).label("correct"),
        )
        .join(QuizAttempt, AnswerLog.attempt_id == QuizAttempt.id)
        .where(QuizAttempt.student_id == student_id, QuizAttempt.status == "graded")
        .group_by(AnswerLog.chapter)
    ).all()
    stats: dict[str, list[int]] = {ch: [asked, int(correct or 0)] for ch, asked, correct in g_rows}
    by_chapter = sorted_chapter_stats(stats)
    weak_chapters = weakness.weak_names(db, student.id)

    return StudentProgress(
        student=StudentResponse(id=student.id, name=student.name, class_level=student.class_level),
        attempts_graded=attempts_graded,
        avg_score_pct=avg_score,
        by_chapter=by_chapter,
        weak_chapters=weak_chapters,
    )


@router.get("/students/{student_id}/activity", response_model=ActivitySummary)
def get_activity(
    student_id: int,
    db: DbSession,
    user: CurrentUser,
    days: Annotated[int, Query(ge=7, le=370)] = 91,
) -> ActivitySummary:
    """streak + GitHub-style daily heatmap (Asia/Dhaka days)."""
    authorize_student_access(db, student_id, user)
    return activity_summary(db, student_id, days)


# ------------------------------------------------------------------
# spaced revision queue (SM-2-lite)
# ------------------------------------------------------------------


def _revision_out(row: RevisionItem) -> RevisionItemOut:
    return RevisionItemOut(
        id=row.id,
        question=row.question,
        options=list(row.options_json or []),
        correct_index=row.correct_index,
        chapter=row.chapter,
        reps=row.reps,
        interval_days=row.interval_days,
        ease_factor=row.ease_factor,
        due_date=row.due_date,
    )


@router.get("/revision/due", response_model=RevisionDueOut, responses=coded(404))
def get_revision_due(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=SMALL_PAGE_MAX_LIMIT)] = SMALL_PAGE_DEFAULT_LIMIT,
) -> RevisionDueOut:
    student = _student_profile(db, user)
    today = dhaka_date(datetime.now(UTC))
    rows = revision.due_items(db, student.id, today, limit=limit)
    return RevisionDueOut(
        today=today,
        due_count=revision.due_count(db, student.id, today),
        items=[_revision_out(r) for r in rows],
    )


@router.post("/revision/{item_id}/review", response_model=RevisionItemOut)
def review_revision_item(
    item_id: int, payload: RevisionReviewIn, db: DbSession, user: CurrentUser
) -> RevisionItemOut:
    student = _student_profile(db, user)
    row = db.get(RevisionItem, item_id)
    if row is None or row.student_id != student.id:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Revision item not found"},
        )
    quality = 5 if payload.chosen == row.correct_index else 1
    reps, interval, ease = revision.next_schedule(
        row.reps, row.interval_days, row.ease_factor, quality
    )
    row.reps, row.interval_days, row.ease_factor = reps, interval, ease
    today = dhaka_date(datetime.now(UTC))
    row.due_date = today if quality < 3 else revision.add_days(today, interval)
    db.commit()
    db.refresh(row)
    return _revision_out(row)


# ------------------------------------------------------------------
# knowledge graph — concept gaps from mastery + prerequisites
# ------------------------------------------------------------------


@router.get("/kg/gaps", response_model=KgGapsOut, responses=coded(404))
def kg_gaps(app_ctx: Ctx, db: DbSession, user: CurrentUser) -> KgGapsOut:
    """Weak-concept gaps: missing/weak prerequisites of concepts this
    student has practiced (transitive, depth-ordered)."""
    student = _student_profile(db, user)
    if app_ctx.index is not None:
        knowledge.ensure_concepts(db, app_ctx.index.chunks)
    gaps = knowledge.student_gaps(db, student.id)
    return KgGapsOut(
        weak_threshold_pct=knowledge.WEAK_THRESHOLD_PCT,
        min_attempts=knowledge.MIN_ATTEMPTS,
        gaps=[
            KgGapOut(
                concept=g.concept,
                prereq=g.prereq,
                prereq_pct=g.prereq_pct,
                prereq_total=g.prereq_total,
                depth=g.depth,
            )
            for g in gaps
        ],
    )


@router.post("/kg/rebuild", response_model=KgRebuildOut)
async def kg_rebuild(
    app_ctx: Ctx,
    db: DbSession,
    user: AdminUser,
    llm: Annotated[bool, Query()] = False,
) -> KgRebuildOut:
    """Admin: rebuild chapter-root concepts + curated prerequisite edges.
    With llm=true, also attempt corpus-verified LLM concept extraction."""
    if app_ctx.index is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
        )
    active_provider = app_ctx.provider
    if llm and active_provider is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_unavailable", "message": "LLM provider not configured"},
        )
    stats = await knowledge.rebuild_concepts(db, app_ctx.index.chunks, active_provider, llm=llm)
    return KgRebuildOut(**stats)


# ------------------------------------------------------------------
# global search over subjects + chapters + questions (BM25)
# ------------------------------------------------------------------


def _subject_hits(chunks: list, query: str, limit: int = 3) -> list[SearchHit]:
    """Subject entries whose slug or book title matches the query text.

    Subject names are matched directly (not by relevance score), so they lead
    the result list and are capped: a query that matches every subject is
    served by the chapter/question hits below it.

    The query folds through the shared normalizer (F-104, residual): the
    retrieval lanes already fold ZWNJ/ZWJ and decomposed yya spellings, so a
    subject query typed the same way as the other lanes must not be the one
    lane that misses. The book title is folded on both sides for the same
    reason -- it is Bangla text a student can type with either encoding.
    """
    norm = normalize_nfkc(query).casefold()
    out: list[SearchHit] = []
    seen: set[str] = set()
    for chunk in chunks:
        slug = chunk.meta.subject
        if slug in seen:
            continue
        book = chunk.meta.book or slug
        if norm == slug.casefold() or norm in slug or norm in normalize_nfkc(book).casefold():
            seen.add(slug)
            out.append(
                SearchHit(
                    kind="subject",
                    title=book,
                    subtitle=slug,
                    href="/student/learn",
                    score=1000.0,
                )
            )
        if len(seen) >= limit:
            break
    return out


def _chapter_href(subject: str, chapter: str, class_level: int) -> str:
    return f"/student/learn/{quote(subject)}/{quote(chapter)}?class={class_level}"


def _ranked_hits(hits: list, limit: int = 10) -> list[SearchHit]:
    """Chapter and question-section hits, deduped per chapter and ranked.

    The question hit is the more specific pointer, so a chapter that owns one
    is represented by it alone.
    """
    chapters: dict[tuple[str, str, int], SearchHit] = {}
    questions: dict[tuple[str, str, int, str], SearchHit] = {}
    for hit in hits:
        meta = hit.chunk.meta
        href = _chapter_href(meta.subject, meta.chapter, meta.class_level)
        section = meta.section or ""
        qkey = (meta.subject, meta.chapter, meta.class_level, section)
        if section and _is_question_like(section) and qkey not in questions:
            questions[qkey] = SearchHit(
                kind="question",
                title=section,
                subtitle=f"{meta.chapter} \u00b7 {meta.book or meta.subject}",
                href=href,
                score=hit.score,
            )
        ckey = (meta.subject, meta.chapter, meta.class_level)
        if ckey not in chapters:
            chapters[ckey] = SearchHit(
                kind="chapter",
                title=meta.chapter,
                subtitle=meta.book or meta.subject,
                href=href,
                score=hit.score,
            )
    question_chapters = {(s, c, cl) for (s, c, cl, _sec) in questions}
    merged = sorted(
        list(questions.values())
        + [hit for key, hit in chapters.items() if key not in question_chapters],
        key=lambda h: h.score,
        reverse=True,
    )
    return merged[:limit]


@router.get("/search", response_model=SearchResponse)
def global_search(
    app_ctx: Ctx,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> SearchResponse:
    """one search box for the whole curriculum.

    Question-like queries set ``ask_action`` so the UI can offer the
    ask-in-Tutor action; chapter and question-section hits are deduped
    per chapter (the question hit is the more specific pointer).
    """
    if app_ctx.index is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
        )
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_query", "message": "Query must not be blank"},
        )
    ask = _is_question_like(query)
    hits = app_ctx.index.search(query, top_k=24, min_score=0.5)
    out = _subject_hits(app_ctx.index.chunks, query)
    out.extend(_ranked_hits(hits))
    return SearchResponse(query=query, ask_action=ask, hits=out)


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    app_ctx: Ctx, request: Request, db: DbSession, user: CurrentUser
) -> DashboardSummary:
    """per-user 60s cache over the summary (shared Redis cache
    when RATE_LIMIT_BACKEND=redis + REDIS_URL, memory cache otherwise)."""
    # Same Asia/Dhaka day as every other learning surface (activity, revision,
    # dashboard cache keys): a UTC date here flips "today" six hours early.
    today = dhaka_date(datetime.now(UTC))
    summary_cache = app_ctx.cache
    key = f"summary:{user.id}:{today}"
    cached = summary_cache.get_json(key)
    if cached is not None:
        try:
            cached_summary = DashboardSummary(**cached)
        except (TypeError, ValueError):  # stale shape -> recompute below
            pass
        else:
            caching.CACHE_EVENTS_TOTAL.labels(cache="summary", result="hit").inc()
            return cached_summary
    caching.CACHE_EVENTS_TOTAL.labels(cache="summary", result="miss").inc()
    summary = _build_dashboard_summary(app_ctx, db, user, today)
    summary_cache.set_json(key, summary.model_dump(mode="json"), caching.SUMMARY_CACHE_TTL_SECONDS)
    return summary


QUICK_ACTIONS: tuple[QuickAction, ...] = (
    QuickAction(label="পাঠ্যবই পড়ুন", to="/student/learn", icon="book"),
    QuickAction(label="AI-কে প্রশ্ন করুন", to="/student/tutor", icon="zap"),
    QuickAction(label="কুইজ দিন", to="/student/quiz", icon="graduation"),
)


def _continue_learning(graded: list[QuizAttempt]) -> ContinueLearning | None:
    """Last graded attempt's first question chapter, when it names one."""
    if not graded:
        return None
    # Attempts with no created_at sort last. The sentinel is naive on
    # purpose: created_at is stored as naive UTC throughout this codebase
    # (SQLite has no timezone type), so an aware sentinel would raise
    # TypeError on comparison instead of sorting.
    last = sorted(graded, key=lambda a: a.created_at or datetime.min, reverse=True)[0]
    if not last.quiz_json:
        return None
    first = last.quiz_json[0] if isinstance(last.quiz_json, list) and last.quiz_json else None
    if not (first and isinstance(first, dict) and first.get("chapter")):
        return None
    return ContinueLearning(
        subject=last.subject,
        chapter=first["chapter"],
        class_level=last.class_level,
        excerpt=first.get("question_text", "")[:120],
    )


def _recommendation(graded: list[QuizAttempt], weak: list[str]) -> Recommendation | None:
    """Weak-chapter practice first, a general nudge when there is any history."""
    if weak:
        subject = next(
            (
                a.subject
                for a in graded
                if a.quiz_json
                and any(q.get("chapter") == weak[0] for q in a.quiz_json if isinstance(q, dict))
            ),
            None,
        )
        return Recommendation(
            type="weak_quiz",
            subject=subject or "science",
            chapter=weak[0],
            reason="দুর্বল অধ্যায়",
        )
    if graded:
        return Recommendation(type="general", reason="নতুন কুইজ চেষ্টা করুন")
    return None


def _build_dashboard_summary(app_ctx: Ctx, db: Session, user: User, today: str) -> DashboardSummary:
    me = _build_me_response(app_ctx, db, user)
    if user.role != "student":
        return DashboardSummary(
            user=me,
            today=today,
            continue_learning=None,
            quick_actions=list(QUICK_ACTIONS),
            recommendation=None,
            progress=None,
        )
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        return DashboardSummary(
            user=me,
            today=today,
            quick_actions=list(QUICK_ACTIONS),
            recommendation=None,
            progress=None,
        )
    attempts = (
        db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student.id)).scalars().all()
    )
    graded = [a for a in attempts if a.status == "graded"]
    by_chapter, avg_score = graded_attempt_stats(db, graded)
    weak = weakness.weak_names(db, student.id)
    progress = StudentProgress(
        student=StudentResponse(id=student.id, name=student.name, class_level=student.class_level),
        attempts_graded=len(graded),
        avg_score_pct=avg_score,
        by_chapter=by_chapter,
        weak_chapters=weak,
    )
    return DashboardSummary(
        user=me,
        today=today,
        continue_learning=_continue_learning(graded),
        quick_actions=list(QUICK_ACTIONS),
        recommendation=_recommendation(graded, weak),
        progress=progress,
    )


@router.get("/learn/progress", response_model=list[ChapterProgressOut])
def get_learn_progress(
    db: DbSession, user: CurrentUser, subject: str | None = None, class_level: int | None = None
) -> list[ChapterProgressOut]:
    """List chapter progress for current student."""
    if user.role != "student":
        return []
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        return []
    q = select(ChapterProgress).where(ChapterProgress.student_id == student.id)
    if subject:
        q = q.where(ChapterProgress.subject == subject)
    if class_level:
        q = q.where(ChapterProgress.class_level == class_level)
    rows = (
        db.execute(q.order_by(ChapterProgress.updated_at.desc(), ChapterProgress.id.desc()))
        .scalars()
        .all()
    )
    return [
        ChapterProgressOut(
            subject=r.subject,
            chapter=r.chapter,
            class_level=r.class_level,
            read_pct=r.read_pct,
            completed=r.completed,
            bookmarked=r.bookmarked,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/learn/progress", response_model=ChapterProgressOut)
def upsert_learn_progress(
    payload: ChapterProgressIn, db: DbSession, user: CurrentUser
) -> ChapterProgressOut:
    """Upsert progress/bookmark for a chapter."""
    if user.role != "student":
        raise HTTPException(
            status_code=403, detail={"code": "students_only", "message": "Only students"}
        )
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        raise HTTPException(
            status_code=404, detail={"code": "student_not_found", "message": "Student not found"}
        )
    # Import here to avoid circular
    from bangla_gpt_api.db.models import ChapterProgress
    from bangla_gpt_api.services.upsert import get_or_create

    # A first-touch read AND write from two tabs used to race the unique key
    # into an unhandled IntegrityError; get_or_create closes that (savepoint +
    # re-read). updated_at is naive UTC like every other column default —
    # an aware datetime here would depend on the database session's timezone.
    row, _created = get_or_create(
        db,
        model=ChapterProgress,
        lookup=select(ChapterProgress).where(
            ChapterProgress.student_id == student.id,
            ChapterProgress.subject == payload.subject,
            ChapterProgress.chapter == payload.chapter,
            ChapterProgress.class_level == payload.class_level,
        ),
        defaults={
            "student_id": student.id,
            "subject": payload.subject,
            "chapter": payload.chapter,
            "class_level": payload.class_level,
            "read_pct": payload.read_pct or 0,
            "completed": payload.completed or False,
            "bookmarked": payload.bookmarked or False,
        },
    )
    if payload.read_pct is not None:
        row.read_pct = payload.read_pct
    if payload.completed is not None:
        row.completed = payload.completed
    if payload.bookmarked is not None:
        row.bookmarked = payload.bookmarked
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return ChapterProgressOut(
        subject=row.subject,
        chapter=row.chapter,
        class_level=row.class_level,
        read_pct=row.read_pct,
        completed=row.completed,
        bookmarked=row.bookmarked,
        updated_at=row.updated_at,
    )
