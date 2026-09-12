"""Learn Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from bangla_gpt_api import caching
from bangla_gpt_api.db.models import (
    AnswerLog,
    ChapterProgress,
    DailyActivity,
    QuizAttempt,
    RevisionItem,
    Student,
    User,
)
from bangla_gpt_api.schemas import (
    ActivityDay,
    ActivitySummary,
    ChapterProgressIn,
    ChapterProgressOut,
    ChapterStat,
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
from bangla_gpt_api.services import (
    adaptive,
    knowledge,
    revision,
    weakness,
)
from bangla_gpt_api.services.activity import (
    dhaka_date,
    heatmap_days,
    record_activity,
    streak_days,
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

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/learn/subjects", response_model=list[SubjectOut])
def learn_subjects(
    user: CurrentUser,
    class_level: int | None = Query(default=None),
) -> list[SubjectOut]:
    return list_subjects(class_level)


@router.get("/learn/subjects/{subject}/chapters", response_model=list[ChapterSummaryOut])
def learn_subject_chapters(
    subject: str,
    user: CurrentUser,
    class_level: int | None = Query(default=None),
) -> list[ChapterSummaryOut]:
    chapters = subject_chapters(subject, class_level)
    if not chapters:
        raise HTTPException(status_code=404, detail="Subject not found")
    return chapters


@router.get("/learn/subjects/{subject}/chapters/{chapter}", response_model=ChapterContentOut)
def learn_chapter_content(
    subject: str,
    chapter: str,
    user: CurrentUser,
    class_level: int | None = Query(default=None),
) -> ChapterContentOut:
    content = chapter_content(subject, class_level, chapter)
    if content is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return content


# --- Wave 2: school tenancy helpers -----------------------------------------
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
    # S4.5: generate a wider pool, then hand the student the questions
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
        # S4.5: open KG gaps arrive as re-teach cards BEFORE the next Q.
        reteach=[
            ReteachCardOut(**card)
            for card in adaptive.open_reteach_cards(db, app_ctx.index.chunks, student.id)
        ],
    )


@router.post("/quizzes/{attempt_id}/submit", response_model=QuizResult)
def submit_quiz(
    app_ctx: Ctx, attempt_id: int, payload: QuizSubmitRequest, db: DbSession, user: CurrentUser
) -> QuizResult:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    authorize_student_access(db, attempt.student_id, user)

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
        raise HTTPException(status_code=400, detail="Attempt already graded")

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
    # S1.10: quiz outcomes seed/refresh the spaced-revision queue.
    revision.record_quiz_result(
        db, attempt.student_id, review, attempt.subject, attempt.class_level
    )
    # S4.4: the same graded answers update per-concept mastery in the
    # knowledge graph (chapter roots seeded lazily from the curriculum).
    reteach_cards: list[ReteachCardOut] = []
    if app_ctx.index is not None:
        knowledge.ensure_concepts(db, app_ctx.index.chunks)
        knowledge.record_quiz_result(db, attempt.student_id, review, attempt.class_level)
        # S4.5: Elo ratings follow the graded answers; every wrong answer
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

    # F-PERF-02: SQL aggregates instead of full-history Python loops (shape preserved)
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
    by_chapter = sorted(
        (
            ChapterStat(
                chapter=chapter,
                asked=asked,
                correct=correct_count,
                accuracy=round(100.0 * correct_count / asked, 2),
            )
            for chapter, (asked, correct_count) in stats.items()
        ),
        key=lambda s: s.accuracy,
    )
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
    """S1.9: streak + GitHub-style daily heatmap (Asia/Dhaka days)."""
    authorize_student_access(db, student_id, user)
    today = dhaka_date(datetime.now(UTC))
    rows = (
        db.execute(
            select(DailyActivity)
            .where(DailyActivity.student_id == student_id)
            .order_by(DailyActivity.date)
        )
        .scalars()
        .all()
    )
    window = heatmap_days(list(rows), today, days)
    date_axis = [
        (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).date().isoformat()
        for i in range(days - 1, -1, -1)
    ]
    active = {r.date for r in rows if (r.questions or r.quizzes or r.minutes)}
    return ActivitySummary(
        streak=streak_days(active, today),
        today=today,
        days=[ActivityDay(date=d, **c) for d, c in zip(date_axis, window, strict=True)],
    )


# ------------------------------------------------------------------
# S1.10: spaced revision queue (SM-2-lite)
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


@router.get("/revision/due", response_model=RevisionDueOut)
def get_revision_due(
    db: DbSession, user: CurrentUser, limit: Annotated[int, Query(ge=1, le=50)] = 20
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
# S4.4: knowledge graph — concept gaps from mastery + prerequisites
# ------------------------------------------------------------------


@router.get("/kg/gaps", response_model=KgGapsOut)
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
# S1.11: global search over subjects + chapters + questions (BM25)
# ------------------------------------------------------------------


@router.get("/search", response_model=SearchResponse)
def global_search(
    app_ctx: Ctx,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> SearchResponse:
    """S1.11: one search box for the whole curriculum.

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

    out: list[SearchHit] = []
    # Subject entries match the slug or the Bangla book title directly.
    norm = query.casefold()
    subjects_seen: set[str] = set()
    for chunk in app_ctx.index.chunks:
        slug = chunk.meta.subject
        if slug in subjects_seen:
            continue
        book = chunk.meta.book or slug
        if norm == slug.casefold() or norm in slug or norm in book.casefold():
            subjects_seen.add(slug)
            out.append(
                SearchHit(
                    kind="subject",
                    title=book,
                    subtitle=slug,
                    href="/student/learn",
                    score=1000.0,
                )
            )
        if len(subjects_seen) >= 3:
            break

    def chapter_href(subject: str, chapter: str, class_level: int) -> str:
        return f"/student/learn/{quote(subject)}/{quote(chapter)}?class={class_level}"

    chapters: dict[tuple[str, str, int], SearchHit] = {}
    questions: dict[tuple[str, str, int, str], SearchHit] = {}
    for hit in hits:
        meta = hit.chunk.meta
        href = chapter_href(meta.subject, meta.chapter, meta.class_level)
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
    out.extend(merged[:10])
    return SearchResponse(query=query, ask_action=ask, hits=out)


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    app_ctx: Ctx, request: Request, db: DbSession, user: CurrentUser
) -> DashboardSummary:
    """S5.3: per-user 60s cache over the S1.1 summary (shared Redis cache
    when RATE_LIMIT_BACKEND=redis + REDIS_URL, memory cache otherwise)."""
    today = datetime.now(UTC).date().isoformat()
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


def _build_dashboard_summary(app_ctx: Ctx, db: Session, user: User, today: str) -> DashboardSummary:
    me = _build_me_response(app_ctx, db, user)
    quick_actions = [
        QuickAction(label="পাঠ্যবই পড়ুন", to="/student/learn", icon="book"),
        QuickAction(label="AI-কে প্রশ্ন করুন", to="/student/tutor", icon="zap"),
        QuickAction(label="কুইজ দিন", to="/student/quiz", icon="graduation"),
    ]
    if user.role != "student":
        return DashboardSummary(
            user=me,
            today=today,
            continue_learning=None,
            quick_actions=quick_actions,
            recommendation=None,
            progress=None,
        )
    # Student progress (reuse logic minimally)
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        return DashboardSummary(
            user=me,
            today=today,
            quick_actions=quick_actions,
            recommendation=None,
            progress=None,
        )
    # Compute progress
    attempts = (
        db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student.id)).scalars().all()
    )
    graded = [a for a in attempts if a.status == "graded"]
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    if graded:
        rows = (
            db.execute(select(AnswerLog).where(AnswerLog.attempt_id.in_([a.id for a in graded])))
            .scalars()
            .all()
        )
        for r in rows:
            stats[r.chapter][0] += 1
            stats[r.chapter][1] += r.is_correct
    by_chapter = sorted(
        (
            ChapterStat(chapter=k, asked=v[0], correct=v[1], accuracy=round(100.0 * v[1] / v[0], 2))
            for k, v in stats.items()
        ),
        key=lambda s: s.accuracy,
    )
    weak = weakness.weak_names(db, student.id)
    avg_score = (
        round(sum(a.score_pct for a in graded if a.score_pct is not None) / len(graded), 2)
        if graded
        else None
    )
    progress = StudentProgress(
        student=StudentResponse(id=student.id, name=student.name, class_level=student.class_level),
        attempts_graded=len(graded),
        avg_score_pct=avg_score,
        by_chapter=by_chapter,
        weak_chapters=weak,
    )
    # Continue: last graded attempt's first question chapter
    continue_learning = None
    if graded:
        last = sorted(graded, key=lambda a: a.created_at or datetime.min, reverse=True)[0]
        if last.quiz_json:
            first = (
                last.quiz_json[0] if isinstance(last.quiz_json, list) and last.quiz_json else None
            )
            if first and isinstance(first, dict) and first.get("chapter"):
                continue_learning = ContinueLearning(
                    subject=last.subject,
                    chapter=first["chapter"],
                    class_level=last.class_level,
                    excerpt=first.get("question_text", "")[:120],
                )
    # Recommendation: weak first, else general
    recommendation = None
    if weak:
        # Find subject for weak chapter via last attempt or default science
        subj = None
        for a in graded:
            if a.quiz_json and any(
                q.get("chapter") == weak[0] for q in a.quiz_json if isinstance(q, dict)
            ):
                subj = a.subject
                break
        recommendation = Recommendation(
            type="weak_quiz", subject=subj or "science", chapter=weak[0], reason="দুর্বল অধ্যায়"
        )
    elif graded:
        recommendation = Recommendation(type="general", reason="নতুন কুইজ চেষ্টা করুন")
    return DashboardSummary(
        user=me,
        today=today,
        continue_learning=continue_learning,
        quick_actions=quick_actions,
        recommendation=recommendation,
        progress=progress,
    )


@router.get("/learn/progress", response_model=list[ChapterProgressOut])
def get_learn_progress(
    db: DbSession, user: CurrentUser, subject: str | None = None, class_level: int | None = None
) -> list[ChapterProgressOut]:
    """S1.2: List chapter progress for current student."""
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
    rows = db.execute(q.order_by(ChapterProgress.updated_at.desc())).scalars().all()
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
    """S1.2: Upsert progress/bookmark for a chapter."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Only students")
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    # Import here to avoid circular
    from bangla_gpt_api.db.models import ChapterProgress

    row = db.execute(
        select(ChapterProgress).where(
            ChapterProgress.student_id == student.id,
            ChapterProgress.subject == payload.subject,
            ChapterProgress.chapter == payload.chapter,
            ChapterProgress.class_level == payload.class_level,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ChapterProgress(
            student_id=student.id,
            subject=payload.subject,
            chapter=payload.chapter,
            class_level=payload.class_level,
            read_pct=payload.read_pct or 0,
            completed=payload.completed or False,
            bookmarked=payload.bookmarked or False,
        )
        db.add(row)
    else:
        if payload.read_pct is not None:
            row.read_pct = payload.read_pct
        if payload.completed is not None:
            row.completed = payload.completed
        if payload.bookmarked is not None:
            row.bookmarked = payload.bookmarked
        row.updated_at = datetime.now(UTC)
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
