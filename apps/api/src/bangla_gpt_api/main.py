import time
from collections import defaultdict, deque
from collections.abc import Generator
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from bangla_gpt_api.auth.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from bangla_gpt_api.config import Settings, get_settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.db.models import (
    AnswerLog,
    Parent,
    ParentStudentLink,
    QuizAttempt,
    Student,
    Teacher,
    User,
)
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.logging_config import configure_logging
from bangla_gpt_api.providers import ProviderNotConfigured, get_provider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.schemas import (
    AdminOverview,
    AskRequest,
    AskResponse,
    ChapterStat,
    ClassAnalytics,
    LoginRequest,
    ParentLinkRequest,
    QuizQuestionPublic,
    QuizResult,
    QuizStarted,
    QuizStartRequest,
    QuizSubmitRequest,
    RegisterRequest,
    RegisterResponse,
    ReviewItem,
    RoleUpdateRequest,
    StudentBrief,
    StudentProgress,
    StudentResponse,
    TokenResponse,
    UserPublic,
)
from bangla_gpt_api.services.quiz import ClozeQuizGenerator, dump_quiz
from bangla_gpt_api.services.tutor import TutorService


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        import uuid

        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rules: dict[str, int]) -> None:
        super().__init__(app)
        self.rules = rules
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        for path_prefix, limit in self.rules.items():
            if not request.url.path.startswith(path_prefix) or limit <= 0:
                continue
            key = (client_ip, path_prefix)
            now = time.monotonic()
            hits = self._hits[key]
            while hits and now - hits[0] >= 60.0:
                hits.popleft()
            if len(hits) >= limit:
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
            hits.append(now)
            break
        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
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

    if settings.admin_email and settings.admin_password:
        with session_factory() as bootstrap_db:
            admin_email = settings.admin_email.strip().lower()
            exists = bootstrap_db.execute(
                select(User).where(User.email == admin_email)
            ).scalar_one_or_none()
            if exists is None:
                bootstrap_db.add(
                    User(
                        email=admin_email,
                        password_hash=hash_password(settings.admin_password),
                        role="admin",
                    )
                )
                bootstrap_db.commit()

    app.add_middleware(
        RateLimitMiddleware,
        rules={
            "/auth/login": settings.rate_limit_login_per_minute,
            "/tutor/ask": settings.rate_limit_tutor_per_minute,
        },
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RequestIdMiddleware)

    def get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    DbSession = Annotated[Session, Depends(get_db)]

    bearer_scheme = HTTPBearer(auto_error=False)
    BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

    def get_current_user(
        credentials: BearerCredentials,
        db: DbSession,
    ) -> User:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        try:
            payload = decode_token(credentials.credentials, settings=settings)
            user_id = int(payload["sub"])
        except (pyjwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise _unauthorized("Invalid or expired token") from exc
        user = db.get(User, user_id)
        if user is None:
            raise _unauthorized("Invalid or expired token")
        return user

    CurrentUser = Annotated[User, Depends(get_current_user)]

    def require_roles(*roles: str):
        def dependency(user: CurrentUser) -> User:
            if user.role not in roles:
                raise HTTPException(status_code=403, detail="Insufficient role")
            return user

        return dependency

    TeacherOrAdminUser = Annotated[User, Depends(require_roles("teacher", "admin"))]
    ParentUser = Annotated[User, Depends(require_roles("parent"))]
    AdminUser = Annotated[User, Depends(require_roles("admin"))]

    def authorize_student_access(db: Session, student_id: int, user: User) -> Student:
        student = db.get(Student, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        if user.role in ("teacher", "admin"):
            return student
        if user.role == "student" and student.user_id == user.id:
            return student
        raise HTTPException(status_code=403, detail="Not allowed to access this student")

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
    async def ready(db: DbSession) -> dict:
        if provider is None:
            detail = (
                f"LLM_PROVIDER={settings.llm_provider!r} is not implemented yet. "
                "Set LLM_PROVIDER=mock or configure a supported provider."
            )
            raise HTTPException(status_code=503, detail=detail)
        try:
            db.execute(select(1))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"status": "ready", "provider": provider.name}

    @app.post("/auth/register", response_model=RegisterResponse, status_code=201)
    def register(payload: RegisterRequest, db: DbSession) -> RegisterResponse:
        email = payload.email.strip().lower()
        existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already registered")
        user = User(email=email, password_hash=hash_password(payload.password), role=payload.role)
        db.add(user)
        db.flush()
        profile: Student | Teacher | Parent
        if payload.role == "student":
            profile = Student(
                name=payload.name.strip(), class_level=payload.class_level, user_id=user.id
            )
        elif payload.role == "parent":
            profile = Parent(name=payload.name.strip(), user_id=user.id)
        else:
            profile = Teacher(name=payload.name.strip(), user_id=user.id)
        db.add(profile)
        db.commit()
        return RegisterResponse(user_id=user.id, role=user.role, profile_id=profile.id)

    @app.post("/auth/login", response_model=TokenResponse)
    def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
        email = payload.email.strip().lower()
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        token = create_access_token(user, settings=settings)
        return TokenResponse(access_token=token)

    @app.post("/tutor/ask", response_model=AskResponse)
    async def ask(payload: AskRequest) -> AskResponse:
        if tutor is None:
            raise HTTPException(status_code=503, detail="Tutor service unavailable")
        return await tutor.ask(payload.question, payload.class_level, payload.subject)

    @app.get("/students/{student_id}", response_model=StudentResponse)
    def get_student(student_id: int, db: DbSession, user: CurrentUser) -> StudentResponse:
        student = authorize_student_access(db, student_id, user)
        return StudentResponse(id=student.id, name=student.name, class_level=student.class_level)

    @app.post("/quizzes", response_model=QuizStarted)
    def start_quiz(payload: QuizStartRequest, db: DbSession, user: CurrentUser) -> QuizStarted:
        if index is None:
            raise HTTPException(status_code=503, detail="Curriculum index unavailable")
        student = authorize_student_access(db, payload.student_id, user)
        class_level = (
            payload.class_level if payload.class_level is not None else student.class_level
        )

        attempt = QuizAttempt(
            student_id=student.id, subject=payload.subject, class_level=class_level
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
    def submit_quiz(
        attempt_id: int, payload: QuizSubmitRequest, db: DbSession, user: CurrentUser
    ) -> QuizResult:
        attempt = db.get(QuizAttempt, attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Attempt not found")
        authorize_student_access(db, attempt.student_id, user)
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
    def get_progress(student_id: int, db: DbSession, user: CurrentUser) -> StudentProgress:
        student = authorize_student_access(db, student_id, user)

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

    def _load_class_students(db: Session, class_level: int | None) -> list[Student]:
        statement = select(Student).order_by(Student.id)
        if class_level is not None:
            statement = statement.where(Student.class_level == class_level)
        return list(db.execute(statement).scalars().all())

    def _student_briefs(db: Session, students: list[Student]) -> list[StudentBrief]:
        briefs: list[StudentBrief] = []
        for student in students:
            attempts = (
                db.execute(
                    select(QuizAttempt).where(
                        QuizAttempt.student_id == student.id, QuizAttempt.status == "graded"
                    )
                )
                .scalars()
                .all()
            )
            scores = [a.score_pct for a in attempts if a.score_pct is not None]
            avg = round(sum(scores) / len(scores), 2) if scores else None
            briefs.append(
                StudentBrief(
                    student_id=student.id,
                    name=student.name,
                    class_level=student.class_level,
                    attempts_graded=len(attempts),
                    avg_score_pct=avg,
                )
            )
        return briefs

    @app.get("/teacher/students", response_model=list[StudentBrief])
    def teacher_roster(
        db: DbSession, teacher: TeacherOrAdminUser, class_level: int | None = None
    ) -> list[StudentBrief]:
        students = _load_class_students(db, class_level)
        return _student_briefs(db, students)

    @app.get("/teacher/classes/{class_level}/analytics", response_model=ClassAnalytics)
    def teacher_analytics(
        class_level: int, db: DbSession, teacher: TeacherOrAdminUser
    ) -> ClassAnalytics:
        students = _load_class_students(db, class_level)
        briefs = _student_briefs(db, students)

        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        if students:
            attempt_ids = [
                a.id
                for a in db.execute(
                    select(QuizAttempt).where(
                        QuizAttempt.student_id.in_([s.id for s in students]),
                        QuizAttempt.status == "graded",
                    )
                )
                .scalars()
                .all()
            ]
            if attempt_ids:
                rows = (
                    db.execute(select(AnswerLog).where(AnswerLog.attempt_id.in_(attempt_ids)))
                    .scalars()
                    .all()
                )
                for row in rows:
                    stats[row.chapter][0] += 1
                    stats[row.chapter][1] += row.is_correct

        chapters = sorted(
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

        return ClassAnalytics(
            class_level=class_level,
            students=len(students),
            chapters=chapters,
            weak_chapters=[c.chapter for c in chapters if c.accuracy < 60.0],
            students_detail=briefs,
        )

    @app.get("/admin/users", response_model=list[UserPublic])
    def admin_list_users(db: DbSession, admin: AdminUser) -> list[UserPublic]:
        users = db.execute(select(User).order_by(User.id)).scalars().all()
        return [
            UserPublic(id=u.id, email=u.email, role=u.role, created_at=u.created_at) for u in users
        ]

    @app.patch("/admin/users/{user_id}/role", response_model=UserPublic)
    def admin_update_role(
        user_id: int, payload: RoleUpdateRequest, db: DbSession, admin: AdminUser
    ) -> UserPublic:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if target.role == "admin" and payload.role != "admin":
            admins = db.execute(
                select(func.count()).select_from(User).where(User.role == "admin")
            ).scalar_one()
            if admins <= 1:
                raise HTTPException(status_code=409, detail="Cannot demote the last admin")
        target.role = payload.role
        db.commit()
        db.refresh(target)
        return UserPublic(
            id=target.id, email=target.email, role=target.role, created_at=target.created_at
        )

    @app.get("/admin/analytics/overview", response_model=AdminOverview)
    def admin_overview(db: DbSession, admin: AdminUser) -> AdminOverview:
        users = db.execute(select(User)).scalars().all()
        by_role: dict[str, int] = defaultdict(int)
        for u in users:
            by_role[u.role] += 1
        attempts = (
            db.execute(select(QuizAttempt).where(QuizAttempt.status == "graded")).scalars().all()
        )
        scores = [a.score_pct for a in attempts if a.score_pct is not None]
        return AdminOverview(
            users_total=len(users),
            students=by_role.get("student", 0),
            teachers=by_role.get("teacher", 0),
            admins=by_role.get("admin", 0),
            parents=by_role.get("parent", 0),
            quiz_attempts_graded=len(attempts),
            avg_score_pct=round(sum(scores) / len(scores), 2) if scores else None,
        )

    @app.post("/parents/link", status_code=201)
    def parent_link(payload: ParentLinkRequest, db: DbSession, parent: ParentUser) -> dict:
        parent_profile = db.execute(
            select(Parent).where(Parent.user_id == parent.id)
        ).scalar_one_or_none()
        if parent_profile is None:
            parent_profile = Parent(name=parent.email.split("@")[0], user_id=parent.id)
            db.add(parent_profile)
            db.flush()
        student = db.get(Student, payload.student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
        existing = db.execute(
            select(ParentStudentLink).where(
                ParentStudentLink.parent_id == parent_profile.id,
                ParentStudentLink.student_id == student.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Already linked")
        db.add(ParentStudentLink(parent_id=parent_profile.id, student_id=student.id))
        db.commit()
        return {"linked": True, "parent_id": parent_profile.id, "student_id": student.id}

    @app.get("/parents/me/children", response_model=list[StudentBrief])
    def parent_children(db: DbSession, parent: ParentUser) -> list[StudentBrief]:
        parent_profile = db.execute(
            select(Parent).where(Parent.user_id == parent.id)
        ).scalar_one_or_none()
        if parent_profile is None:
            return []
        links = (
            db.execute(
                select(ParentStudentLink).where(ParentStudentLink.parent_id == parent_profile.id)
            )
            .scalars()
            .all()
        )
        if not links:
            return []
        students = (
            db.execute(select(Student).where(Student.id.in_([link.student_id for link in links])))
            .scalars()
            .all()
        )
        return _student_briefs(db, list(students))

    @app.get("/parents/me/children/{student_id}/progress", response_model=StudentProgress)
    def parent_child_progress(
        student_id: int, db: DbSession, parent: ParentUser
    ) -> StudentProgress:
        parent_profile = db.execute(
            select(Parent).where(Parent.user_id == parent.id)
        ).scalar_one_or_none()
        if parent_profile is None:
            raise HTTPException(status_code=404, detail="Not linked to this student")
        link = db.execute(
            select(ParentStudentLink).where(
                ParentStudentLink.parent_id == parent_profile.id,
                ParentStudentLink.student_id == student_id,
            )
        ).scalar_one_or_none()
        if link is None:
            raise HTTPException(status_code=404, detail="Not linked to this student")
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
            rows = (
                db.execute(
                    select(AnswerLog).where(AnswerLog.attempt_id.in_([a.id for a in graded]))
                )
                .scalars()
                .all()
            )
            for row in rows:
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
