"""Assessment Routes — split from the main.py god-module (ARCH-001).

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via :mod:`.deps`, shared helpers via :mod:`.common`.
"""

import logging
import random
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    Assignment,
    ChapterContent,
    ChapterProgress,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    QuizAttempt,
    School,
    ShortTest,
    Student,
    SupportPlan,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.schemas import (
    AssignmentIn,
    AssignmentMineOut,
    AssignmentOut,
    AssignmentProgressRow,
    CoverageCell,
    CoverageOut,
    QuizQuestionPublic,
    ShortTestIn,
    ShortTestMineOut,
    ShortTestOut,
    SupportPlanIn,
    SupportPlanOut,
    WeakCell,
    WeakMatrixOut,
    WeakStudent,
)
from bangla_gpt_api.services import (
    atrisk,
    coverage,
    weakness,
)
from bangla_gpt_api.services.quiz import ClozeQuizGenerator, dump_quiz

from .common import (
    _answer_cells,
    _attempt_percents,
    _classroom_or_404,
    _default_school,
    _load_class_students,
    canonical_subject,
    notify_user,
)
from .deps import (
    Ctx,
    CurrentUser,
    DbSession,
    TeacherOrAdminUser,
    _assert_room_in_school,
    _assert_student_in_school,
    _tenant_school_id,
)

router = APIRouter()

logger = logging.getLogger(__name__)


def _st_questions(st: ShortTest) -> list[QuizQuestionPublic]:
    return [
        QuizQuestionPublic(
            id=str(q["id"]),
            question_text=str(q["question_text"]),
            options=[str(o) for o in q["options"]],
        )
        for q in st.questions
    ]


def _st_out(st: ShortTest) -> ShortTestOut:
    return ShortTestOut(
        id=st.id,
        classroom_id=st.classroom_id,
        teacher_id=st.teacher_id,
        subject=st.subject,
        chapter=st.chapter,
        num_questions=st.num_questions,
        duration_min=st.duration_min,
        questions=_st_questions(st),
        attempts=[dict(a) for a in st.attempts],
        created_at=st.created_at,
    )


@router.post("/teacher/shorttests", response_model=ShortTestOut, status_code=201)
def teacher_shorttest_create(
    app_ctx: Ctx, payload: ShortTestIn, db: DbSession, teacher: TeacherOrAdminUser
) -> ShortTestOut:
    """Generate ONE rule-based set, open an attempt per enrolled student.

    Rule-based (no LLM) so generate->assign stays far below the 10s p95
    target; the wall time is logged as ``shorttest_assigned.elapsed_ms``.
    """
    if app_ctx.index is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
        )
    room = _assert_room_in_school(teacher, _classroom_or_404(db, payload.classroom_id))
    roster = list(
        db.execute(
            select(Student)
            .join(ClassStudent, ClassStudent.student_id == Student.id)
            .where(ClassStudent.classroom_id == room.id)
            .order_by(Student.id)
        )
        .scalars()
        .all()
    )
    if not roster:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_roster", "message": "Classroom has no students yet"},
        )
    started = time.perf_counter()
    generator = ClozeQuizGenerator(app_ctx.index.chunks)
    questions = generator.generate(
        class_level=room.class_level,
        subject=canonical_subject(payload.subject),
        chapter=payload.chapter,
        num=payload.num_questions,
        seed=random.randrange(1_000_000_000),
    )
    if not questions:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_quiz_for_filter",
                "message": "No questions for this class/subject/chapter yet",
            },
        )
    dump = dump_quiz(questions)
    # F-PERF-05: bulk insert (add_all + single flush) instead of per-student flush loop
    attempt_objs = [
        QuizAttempt(
            student_id=student.id,
            subject=payload.subject,
            class_level=room.class_level,
            quiz_json=dump,
        )
        for student in roster
    ]
    db.add_all(attempt_objs)
    db.flush()
    attempts: list[dict[str, int]] = [
        {"student_id": obj.student_id, "attempt_id": obj.id} for obj in attempt_objs
    ]
    st = ShortTest(
        classroom_id=room.id,
        teacher_id=teacher.id,
        subject=payload.subject,
        chapter=payload.chapter,
        num_questions=payload.num_questions,
        duration_min=payload.duration_min,
        questions=dump,
        attempts=attempts,
    )
    db.add(st)
    db.flush()
    # Wave 1: every roster student with a user account gets a notification.
    for student in roster:
        notify_user(
            db,
            student.user_id,
            "shorttest",
            "notif_shorttest_assigned",
            {"short_test_id": st.id, "subject": payload.subject, "chapter": payload.chapter},
            # Wave 2: students open assigned work at the quiz hub.
            link="/student/quiz",
        )
    db.commit()
    db.refresh(st)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    json_log(
        logger,
        logging.INFO,
        "shorttest_assigned",
        short_test_id=st.id,
        classroom_id=room.id,
        teacher_id=teacher.id,
        students=len(attempts),
        question_count=len(questions),
        elapsed_ms=elapsed_ms,
    )
    return _st_out(st)


@router.get("/teacher/shorttests", response_model=list[ShortTestOut])
def teacher_shorttest_list(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    classroom_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ShortTestOut]:
    q = select(ShortTest)
    if teacher.role != "admin":
        q = q.where(ShortTest.teacher_id == teacher.id)
    if classroom_id is not None:
        q = q.where(ShortTest.classroom_id == classroom_id)
    rows = (
        db.execute(
            q.order_by(ShortTest.created_at.desc(), ShortTest.id.desc())
            .offset(offset)
            .limit(limit)  # S5.5: page the list (payload carries questions)
        )
        .scalars()
        .all()
    )
    return [_st_out(row) for row in rows]


@router.get("/shorttests/mine", response_model=list[ShortTestMineOut])
def shorttests_mine(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ShortTestMineOut]:
    """Assigned short tests for the signed-in student (duration soft:
    ``expired`` is advisory; submitting after it is still allowed so no
    completed work is lost)."""
    if user.role != "student":
        return []
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        return []
    room_ids = list(
        db.execute(select(ClassStudent.classroom_id).where(ClassStudent.student_id == student.id))
        .scalars()
        .all()
    )
    if not room_ids:
        return []
    rows = (
        db.execute(
            select(ShortTest)
            .where(ShortTest.classroom_id.in_(room_ids))
            .order_by(ShortTest.created_at.desc(), ShortTest.id.desc())
            .limit(limit)  # S5.5: cap per-request payload
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    out: list[ShortTestMineOut] = []
    for st in rows:
        expires_at = st.created_at + timedelta(minutes=st.duration_min)
        own = {int(a["student_id"]): int(a["attempt_id"]) for a in st.attempts}
        out.append(
            ShortTestMineOut(
                id=st.id,
                classroom_id=st.classroom_id,
                attempt_id=own.get(student.id),
                subject=st.subject,
                chapter=st.chapter,
                num_questions=st.num_questions,
                duration_min=st.duration_min,
                questions=_st_questions(st),
                created_at=st.created_at,
                expires_at=expires_at,
                expired=now >= expires_at,
            )
        )
    return out


# --- S2.7: weak heatmap + at-risk detection + support plan ----------------


def _read_chapters(db: Session, student_ids: list[int]) -> dict[int, set[str]]:
    """Tutor/reading signal: chapters the student has opened in the reader."""
    out: dict[int, set[str]] = defaultdict(set)
    if not student_ids:
        return out
    rows = db.execute(
        select(ChapterProgress.student_id, ChapterProgress.chapter).where(
            ChapterProgress.student_id.in_(student_ids)
        )
    ).all()
    for sid, chapter in rows:
        out[sid].add(chapter)
    return out


def _weak_matrix(db: Session, class_level: int, school_id: int | None = None) -> WeakMatrixOut:
    students = _load_class_students(db, class_level, school_id=school_id)
    ids = [s.id for s in students]
    cells = _answer_cells(db, ids)
    percents = _attempt_percents(db, ids)
    read = _read_chapters(db, ids)
    weak_map = weakness.weak_names_for(db, ids)

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for per_student in cells.values():
        for ch, (asked, correct) in per_student.items():
            totals[ch][0] += asked
            totals[ch][1] += correct
    concepts = sorted(totals, key=lambda c: (atrisk.cell_accuracy(*totals[c]) or 0.0, c))

    out_students = [
        WeakStudent(
            student_id=s.id,
            name=s.name,
            avg_score_pct=atrisk.avg_pct(percents.get(s.id, [])),
            attempts_graded=len(percents.get(s.id, [])),
            trend=atrisk.score_trend(percents.get(s.id, [])),
            at_risk=atrisk.is_at_risk(
                atrisk.avg_pct(percents.get(s.id, [])),
                atrisk.score_trend(percents.get(s.id, [])),
            ),
            weak_concepts=weak_map.get(s.id, []),
            cells={
                ch: WeakCell(
                    asked=a,
                    correct=c,
                    accuracy=atrisk.cell_accuracy(a, c),
                    read=ch in read.get(s.id, ()),
                )
                for ch, (a, c) in cells.get(s.id, {}).items()
            },
        )
        for s in students
    ]
    return WeakMatrixOut(class_level=class_level, concepts=concepts, students=out_students)


def _support_plan_out(row: SupportPlan) -> SupportPlanOut:
    return SupportPlanOut(
        id=row.id,
        student_id=row.student_id,
        teacher_id=row.teacher_id,
        class_level=row.class_level,
        focus_concepts=list(row.focus_concepts),
        plan=dict(row.plan),
        created_at=row.created_at,
    )


@router.get("/teacher/weak-matrix", response_model=WeakMatrixOut)
def teacher_weak_matrix(
    db: DbSession, teacher: TeacherOrAdminUser, class_level: int
) -> WeakMatrixOut:
    """Concept x student accuracy grid with at-risk flags for a class."""
    return _weak_matrix(db, class_level, school_id=_tenant_school_id(teacher))


@router.get("/teacher/curriculum-coverage", response_model=CoverageOut)
def teacher_curriculum_coverage(db: DbSession, teacher: TeacherOrAdminUser) -> CoverageOut:
    """S3.3: class x subject grid -- taught / practiced / mastered (>=70%).

    Taught = chapter content exists for the grade-subject or a
    ClassTeacher row assigns it ('' covers all subjects); practiced =
    quiz attempts by students of that class; mastered = graded mean
    >= coverage.MASTERED_MIN_PCT. Derivation lives in services.coverage
    (pure, unit-tested).
    """
    room_stmt = select(ClassRoom).order_by(ClassRoom.class_level, ClassRoom.section)
    if teacher.role != "admin":
        school = db.get(School, teacher.school_id) if teacher.school_id else None
        if school is None:
            school = _default_school(db)
        room_stmt = room_stmt.where(ClassRoom.school_id == school.id)
    rooms = db.execute(room_stmt).scalars().all()
    room_ids = [r.id for r in rooms]

    # v1 rule: one classroom per student, so this map is unambiguous.
    room_of: dict[int, int] = {}
    if room_ids:
        for cid, sid in db.execute(
            select(ClassStudent.classroom_id, ClassStudent.student_id).where(
                ClassStudent.classroom_id.in_(room_ids)
            )
        ).all():
            room_of[sid] = cid

    # quiz activity aggregated per (classroom, subject)
    attempts: dict[tuple[int, str], int] = defaultdict(int)
    graded: dict[tuple[int, str], list[float]] = defaultdict(list)
    if room_of:
        rows = db.execute(
            select(
                QuizAttempt.student_id,
                QuizAttempt.subject,
                QuizAttempt.status,
                QuizAttempt.score_pct,
            ).where(QuizAttempt.student_id.in_(list(room_of)))
        ).all()
        for sid, subject, status, pct in rows:
            if not subject or sid not in room_of:
                continue
            key = (room_of[sid], subject)
            attempts[key] += 1
            if status == "graded" and pct is not None:
                graded[key].append(float(pct))

    # assignment signals: chapter content + per-subject teacher rows
    content: dict[int, set[str]] = defaultdict(set)
    for level, subject in db.execute(
        select(ChapterContent.class_level, ChapterContent.subject).distinct()
    ).all():
        content[level].add(subject)
    assigned: dict[int, set[str]] = defaultdict(set)
    if room_ids:
        for cid, subject in db.execute(
            select(ClassTeacher.classroom_id, ClassTeacher.subject).where(
                ClassTeacher.classroom_id.in_(room_ids)
            )
        ).all():
            assigned[cid].add(subject)

    subjects: set[str] = set()
    cells: list[CoverageCell] = []
    for room in rooms:
        level_content = content.get(room.class_level, set())
        subs = set(level_content)
        subs |= {s for (cid, s) in attempts if cid == room.id}
        subs |= {s for s in assigned.get(room.id, ()) if s}
        for subject in sorted(subs):
            key = (room.id, subject)
            att = attempts.get(key, 0)
            avg = coverage.avg_of(graded.get(key, []))
            taught = coverage.is_taught(
                subject in level_content, assigned.get(room.id, set()), subject
            )
            status = coverage.derive_status(taught, att > 0, avg)
            subjects.add(subject)
            cells.append(
                CoverageCell(
                    classroom_id=room.id,
                    class_level=room.class_level,
                    section=room.section,
                    subject=subject,
                    taught=taught,
                    attempts=att,
                    attempts_graded=len(graded.get(key, [])),
                    avg_score_pct=avg,
                    status=status,
                )
            )
    return CoverageOut(subjects=sorted(subjects), cells=cells)


@router.post("/teacher/support-plans", response_model=SupportPlanOut, status_code=201)
def teacher_create_support_plan(
    payload: SupportPlanIn, db: DbSession, teacher: TeacherOrAdminUser
) -> SupportPlanOut:
    """Rule-based 3-week plan over the student's three weakest concepts."""
    student = db.get(Student, payload.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    # Wave 2 tenancy: plans can only be opened for own-school students.
    _assert_student_in_school(db, teacher, student)
    cells = _answer_cells(db, [student.id]).get(student.id, {})
    scored = sorted(
        (
            (ch, acc)
            for ch, (asked, correct) in cells.items()
            if (acc := atrisk.cell_accuracy(asked, correct)) is not None
        ),
        key=lambda t: (t[1], t[0]),
    )
    if not scored:
        raise HTTPException(status_code=422, detail="no graded quiz data for this student")
    weak = [{"name": ch, "accuracy": acc} for ch, acc in scored[:3]]
    plan = atrisk.build_plan(weak)
    row = SupportPlan(
        student_id=student.id,
        teacher_id=teacher.id,
        class_level=student.class_level,
        focus_concepts=plan["focus_concepts"],
        plan=plan,
    )
    db.add(row)
    db.flush()
    # Wave 1: tell the student's own account a support plan was created
    # (skipped silently when the student profile has no login yet).
    notify_user(
        db,
        student.user_id,
        "support_plan",
        "notif_support_plan",
        {"support_plan_id": row.id, "focus": len(plan["focus_concepts"])},
        # Wave 2: revision lives behind the student quiz hub.
        link="/student/quiz",
    )
    db.commit()
    db.refresh(row)
    json_log(
        logger,
        logging.INFO,
        "support_plan_created",
        student_id=student.id,
        teacher_id=teacher.id,
        focus=len(plan["focus_concepts"]),
    )
    return _support_plan_out(row)


@router.get("/teacher/support-plans", response_model=list[SupportPlanOut])
def teacher_list_support_plans(
    db: DbSession, teacher: TeacherOrAdminUser, student_id: int | None = None
) -> list[SupportPlanOut]:
    stmt = select(SupportPlan).order_by(SupportPlan.created_at.desc(), SupportPlan.id.desc())
    if teacher.role != "admin":
        stmt = stmt.where(SupportPlan.teacher_id == teacher.id)
    if student_id is not None:
        stmt = stmt.where(SupportPlan.student_id == student_id)
    rows = db.execute(stmt).scalars().all()
    return [_support_plan_out(r) for r in rows]


# --- S2.8: bulk assignment + tracking (multi-student, one quiz, due date) --


def _assignment_questions(a: Assignment) -> list[QuizQuestionPublic]:
    return [
        QuizQuestionPublic(
            id=str(q["id"]),
            question_text=str(q["question_text"]),
            options=[str(o) for o in q["options"]],
        )
        for q in a.questions
    ]


def _assignment_out(a: Assignment) -> AssignmentOut:
    return AssignmentOut(
        id=a.id,
        teacher_id=a.teacher_id,
        subject=a.subject,
        chapter=a.chapter,
        num_questions=a.num_questions,
        due_at=a.due_at,
        questions=_assignment_questions(a),
        attempts=[{k: int(v) for k, v in ref.items()} for ref in a.attempts],
        created_at=a.created_at,
    )


@router.post("/teacher/assignments", response_model=AssignmentOut, status_code=201)
def teacher_assignment_create(
    app_ctx: Ctx, payload: AssignmentIn, db: DbSession, teacher: TeacherOrAdminUser
) -> AssignmentOut:
    """Generate ONE rule-based set, open an attempt per selected student.

    All selected students must share one class level so the single shared
    question set stays fair; no LLM call keeps 52-student assigns fast.
    """
    if app_ctx.index is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "index_unavailable", "message": "Curriculum index unavailable"},
        )
    students: list[Student] = []
    for sid in dict.fromkeys(payload.student_ids):  # dedupe, keep order
        student = db.get(Student, sid)
        if student is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "unknown_student", "message": f"Student {sid} not found"},
            )
        # Wave 2 tenancy: never open an attempt for a student outside the
        # actor's school (IDOR guard; no-op for school-less teachers/admins).
        _assert_student_in_school(db, teacher, student)
        students.append(student)
    levels = {st.class_level for st in students}
    if len(levels) > 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "mixed_class_levels",
                "message": "Select students from a single class",
            },
        )
    due_at = payload.due_at
    if due_at.tzinfo is not None:
        due_at = due_at.astimezone(UTC).replace(tzinfo=None)
    started = time.perf_counter()
    generator = ClozeQuizGenerator(app_ctx.index.chunks)
    questions = generator.generate(
        class_level=students[0].class_level,
        subject=canonical_subject(payload.subject),
        chapter=payload.chapter,
        num=payload.num_questions,
        seed=random.randrange(1_000_000_000),
    )
    if not questions:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_quiz_for_filter",
                "message": "No questions for this class/subject/chapter yet",
            },
        )
    dump = dump_quiz(questions)
    attempts: list[dict[str, int]] = []
    for student in students:
        attempt = QuizAttempt(
            student_id=student.id,
            subject=payload.subject,
            class_level=student.class_level,
            quiz_json=dump,
        )
        db.add(attempt)
        db.flush()
        attempts.append({"student_id": student.id, "attempt_id": attempt.id})
    assignment = Assignment(
        teacher_id=teacher.id,
        subject=payload.subject,
        chapter=payload.chapter,
        num_questions=payload.num_questions,
        due_at=due_at,
        questions=dump,
        attempts=attempts,
    )
    db.add(assignment)
    db.flush()
    # Wave 1: every assigned student with a user account gets a notification.
    for student in students:
        notify_user(
            db,
            student.user_id,
            "assignment",
            "notif_quiz_assigned",
            {
                "assignment_id": assignment.id,
                "subject": payload.subject,
                "chapter": payload.chapter,
                "count": payload.num_questions,
            },
            # Wave 2: assigned quizzes open at the student quiz hub.
            link="/student/quiz",
        )
    db.commit()
    db.refresh(assignment)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    json_log(
        logger,
        logging.INFO,
        "assignment_assigned",
        assignment_id=assignment.id,
        teacher_id=teacher.id,
        students=len(attempts),
        question_count=len(questions),
        elapsed_ms=elapsed_ms,
    )
    return _assignment_out(assignment)


@router.get("/teacher/assignments", response_model=list[AssignmentOut])
def teacher_assignment_list(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AssignmentOut]:
    # S5.5: newest-first page (was every row the teacher ever created).
    q = select(Assignment)
    if teacher.role != "admin":
        q = q.where(Assignment.teacher_id == teacher.id)
    rows = (
        db.execute(
            q.order_by(Assignment.created_at.desc(), Assignment.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_assignment_out(row) for row in rows]


def _assignment_progress_rows(db: Session, assignment: Assignment) -> list[AssignmentProgressRow]:
    now = datetime.now(UTC).replace(tzinfo=None)
    refs = [(int(r["student_id"]), int(r["attempt_id"])) for r in assignment.attempts]
    attempts = (
        {
            a.id: a
            for a in db.execute(
                select(QuizAttempt).where(QuizAttempt.id.in_([aid for _, aid in refs]))
            ).scalars()
        }
        if refs
        else {}
    )
    names = (
        {
            s.id: s.name
            for s in db.execute(
                select(Student).where(Student.id.in_([sid for sid, _ in refs]))
            ).scalars()
        }
        if refs
        else {}
    )
    rows: list[AssignmentProgressRow] = []
    for sid, aid in refs:
        attempt = attempts.get(aid)
        done = attempt is not None and attempt.status == "graded"
        score_pct: float | None = None
        if done and attempt is not None and attempt.score_pct is not None:
            score_pct = float(attempt.score_pct)
        rows.append(
            AssignmentProgressRow(
                student_id=sid,
                name=names.get(sid, f"#{sid}"),
                attempt_id=aid,
                done=done,
                score_pct=score_pct,
                overdue=not done and now > assignment.due_at,
            )
        )
    return rows


@router.get(
    "/teacher/assignments/{assignment_id}/progress",
    response_model=list[AssignmentProgressRow],
)
def teacher_assignment_progress(
    assignment_id: int, db: DbSession, teacher: TeacherOrAdminUser
) -> list[AssignmentProgressRow]:
    assignment = db.get(Assignment, assignment_id)
    if assignment is None or (teacher.role != "admin" and assignment.teacher_id != teacher.id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    return _assignment_progress_rows(db, assignment)


@router.get("/assignments/mine", response_model=list[AssignmentMineOut])
def assignments_mine(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[AssignmentMineOut]:
    """Assigned quizzes for the signed-in student. Due date is soft like
    short tests: ``overdue`` is advisory, submitting still grades the work.

    S5.5: membership lives in the attempts JSON, so the candidate window is
    the most recent `limit` assignments (was an unbounded full-table scan),
    and attempt rows are fetched in ONE batched query (was 1 per item).
    A membership link table is the proper long-term fix (documented).
    """
    if user.role != "student":
        return []
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    if student is None:
        return []
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = (
        db.execute(
            select(Assignment)
            .order_by(Assignment.created_at.desc(), Assignment.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    matched: list[tuple[Assignment, int]] = []
    for a in rows:
        own = {int(r["student_id"]): int(r["attempt_id"]) for r in a.attempts}
        aid = own.get(student.id)
        if aid is not None:
            matched.append((a, aid))
    attempts = (
        {
            a.id: a
            for a in db.execute(
                select(QuizAttempt).where(QuizAttempt.id.in_([aid for _, aid in matched]))
            ).scalars()
        }
        if matched
        else {}
    )
    out: list[AssignmentMineOut] = []
    for a, aid in matched:
        attempt = attempts.get(aid)
        done = attempt is not None and attempt.status == "graded"
        out.append(
            AssignmentMineOut(
                id=a.id,
                attempt_id=aid,
                subject=a.subject,
                chapter=a.chapter,
                questions=_assignment_questions(a),
                due_at=a.due_at,
                overdue=now > a.due_at and not done,
                done=done,
            )
        )
    return out
