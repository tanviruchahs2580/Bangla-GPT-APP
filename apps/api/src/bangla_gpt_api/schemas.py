from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    class_level: int = Field(ge=1, le=12)
    subject: str | None = None


class SourceRef(BaseModel):
    book: str
    chapter: str
    section: str | None = None
    page: int | None = None
    score: float


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    sources: list[SourceRef]


_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=120)
    role: Literal["student", "teacher"]
    class_level: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def _require_class_level_for_students(self) -> "RegisterRequest":
        if self.role == "student" and self.class_level is None:
            raise ValueError("class_level is required when role is 'student'")
        return self


class RegisterResponse(BaseModel):
    user_id: int
    role: str
    profile_id: int


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChapterStat(BaseModel):
    chapter: str
    asked: int
    correct: int
    accuracy: float


class StudentBrief(BaseModel):
    student_id: int
    name: str
    class_level: int
    attempts_graded: int
    avg_score_pct: float | None


class StudentResponse(BaseModel):
    id: int
    name: str
    class_level: int


class StudentProgress(BaseModel):
    student: StudentResponse
    attempts_graded: int
    avg_score_pct: float | None
    by_chapter: list[ChapterStat]
    weak_chapters: list[str]


class ClassAnalytics(BaseModel):
    class_level: int
    students: int
    chapters: list[ChapterStat]
    weak_chapters: list[str]
    students_detail: list[StudentBrief]


class QuizStartRequest(BaseModel):
    student_id: int
    class_level: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = None
    num_questions: int = Field(default=5, ge=1, le=10)


class QuizQuestionPublic(BaseModel):
    id: str
    question_text: str
    options: list[str]


class QuizStarted(BaseModel):
    attempt_id: int
    questions: list[QuizQuestionPublic]


class QuizSubmitRequest(BaseModel):
    answers: list[int] = Field(min_length=1, max_length=20)


class ReviewItem(BaseModel):
    question_text: str
    options: list[str]
    chosen: int
    correct_index: int
    is_correct: bool
    chapter: str


class QuizResult(BaseModel):
    attempt_id: int
    score_pct: float
    correct: int
    total: int
    review: list[ReviewItem]
