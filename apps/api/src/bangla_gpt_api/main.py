from collections import defaultdict
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings, get_settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.db.models import AnswerLog, QuizAttempt, Student
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.providers import ProviderNotConfigured, get_provider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.schemas import (
    AskRequest,
    AskResponse,
    ChapterStat,
    CreateStudentRequest,
    QuizQuestionPublic,
    QuizResult,
    QuizStarted,
    QuizStartRequest,
    QuizSubmitRequest,
    ReviewItem,
    StudentProgress,
    StudentResponse,
)
from bangla_gpt_api.services.quiz import ClozeQuizGenerator, dump_quiz
from bangla_gpt_api.services.tutor import TutorService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version)

    try:
        provider = get_provider(settings)
    except ProviderNotConfigured:
        provider = None

    index: BM25Index | None = None
    tutor: TutorService | None = None
    if provider is not None:
        index = BM25Index(load_sample_corpus())
        tutor = TutorService(index=index, provider=provider)

    engine = make_engine(settings)
    init_db(engine)
    session_factory = make_session_factory(engine)

    def get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    DbSession = Annotated[Session, Depends(get_db)]

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "env": settings.env,
        }

    @app.get("/live")
    async def live() -> dict:
        return {"status": "alive"}

    @app.get("/ready")
    async def ready() -> dict:
        if provider is None:
            detail = (
                f"LLM_PROVIDER={settings.llm_provider!r} is not implemented yet. "
                "Set LLM_PROVIDER=mock or configure a supported provider."
            )
            raise HTTPException(status_code=503, detail=detail)
        return {"status": "ready", "provider": provider.name}

    @app.post("/tutor/ask", response_model=AskResponse)
    async def ask(payload: AskRequest) -> AskResponse:
        if tutor is None:
            raise HTTPException(status_code=503, detail="Tutor service unavailable")
        return await tutor.ask(payload.question, payload.class_level, payload.subject)

    @app.post("/students", response_model=StudentResponse, status_code=201)
    def create_student(payload: CreateStudentRequest, db: DbSession) -> StudentResponse:
        student = Student(name=payload.name.strip(), class_level=payload.class_level)
        db.add(student)
        db.commit()
        return StudentResponse(id=student.id, name=student.name, class_level=student.class_level)

    @app.get("/students/{student_id}", response_model=StudentResponse)
    def get_student(student_id: int, db: DbSession) -> StudentResponse:
        student = db.get(Student, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        return StudentResponse(id=student.id, name=student.name, class_level=student.class_level)

    @app.post("/quizzes", response_model=QuizStarted)
    def start_quiz(payload: QuizStartRequest, db: DbSession) -> QuizStarted:
        if index is None:
            raise HTTPException(status_code=503, detail="Curriculum index unavailable")
        student = db.get(Student, payload.student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        class_level = (
            payload.class_level if payload.class_level is not None else student.class_level
        )

        attempt = QuizAttempt(
            student_id=student.id,
            subject=payload.subject,
            class_level=class_level,
        )
        db.add(attempt)
        db.flush()

        generator = ClozeQuizGenerator(index.chunks)
        questions = generator.generate(
            class_level=class_level,
            subject=payload.subject,
            num=payload.num_questions,
            seed=attempt.id,
        )
        if not questions:
            db.rollback()
            raise HTTPException(
                status_code=422, detail="No quiz could be generated for this filter"
            )

        attempt.quiz_json = dump_quiz(questions)
        db.commit()

        return QuizStarted(
            attempt_id=attempt.id,
            questions=[
                QuizQuestionPublic(id=q.id, question_text=q.question_text, options=list(q.options))
                for q in questions
            ],
        )

    @app.post("/quizzes/{attempt_id}/submit", response_model=QuizResult)
    def submit_quiz(attempt_id: int, payload: QuizSubmitRequest, db: DbSession) -> QuizResult:
        attempt = db.get(QuizAttempt, attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Attempt not found")
        if attempt.status == "graded":
            raise HTTPException(status_code=400, detail="Attempt already graded")
        questions = list(attempt.quiz_json)
        if len(payload.answers) != len(questions):
            raise HTTPException(
                status_code=400, detail="Answer count does not match question count"
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

        return QuizResult(
            attempt_id=attempt.id,
            score_pct=attempt.score_pct,
            correct=correct,
            total=total,
            review=review,
        )

    @app.get("/students/{student_id}/progress", response_model=StudentProgress)
    def get_progress(student_id: int, db: DbSession) -> StudentProgress:
        student = db.get(Student, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")

        attempts = (
            db.execute(select(QuizAttempt).where(QuizAttempt.student_id == student_id))
            .scalars()
            .all()
        )
        graded = [a for a in attempts if a.status == "graded"]

        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        if graded:
            answer_rows = (
                db.execute(
                    select(AnswerLog).where(AnswerLog.attempt_id.in_([a.id for a in graded]))
                )
                .scalars()
                .all()
            )
            for row in answer_rows:
                stats[row.chapter][0] += 1
                stats[row.chapter][1] += row.is_correct

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
        weak_chapters = [s.chapter for s in by_chapter if s.accuracy < 60.0]
        avg_score = round(sum(a.score_pct for a in graded) / len(graded), 2) if graded else None

        return StudentProgress(
            student=StudentResponse(
                id=student.id, name=student.name, class_level=student.class_level
            ),
            attempts_graded=len(graded),
            avg_score_pct=avg_score,
            by_chapter=by_chapter,
            weak_chapters=weak_chapters,
        )

    return app


app = create_app()
