from pydantic import BaseModel, Field


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


class CreateStudentRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    class_level: int = Field(ge=1, le=12)


class StudentResponse(BaseModel):
    id: int
    name: str
    class_level: int


class ChapterStat(BaseModel):
    chapter: str
    asked: int
    correct: int
    accuracy: float


class StudentProgress(BaseModel):
    student: StudentResponse
    attempts_graded: int
    avg_score_pct: float | None
    by_chapter: list[ChapterStat]
    weak_chapters: list[str]


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
