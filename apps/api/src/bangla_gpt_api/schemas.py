from datetime import datetime
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
    sources: list[SourceRef] = []
    # Machine-readable refusal category ('unsafe_content' | 'insufficient_evidence').
    refused_reason: str | None = None
    # Soft post-generation signal that the answer leans on the cited evidence.
    citation_verified: bool | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ConversationOut(BaseModel):
    id: int
    title: str | None
    created_at: datetime
    message_count: int = 0


class ChatSendRequest(BaseModel):
    message: str = Field(min_length=3, max_length=1000)
    class_level: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = None


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    grounded: bool | None = None
    refused_reason: str | None = None
    sources: list[SourceRef] = []
    rating: int | None = None
    created_at: datetime


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=-1, le=1)
    message_id: int | None = None
    attempt_id: int | None = None
    comment: str | None = Field(default=None, max_length=500)


class AnalyticsEvent(BaseModel):
    """Privacy-safe product event; logged as structured JSON, never PII."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.]+$")
    props: dict[str, str | int | bool] = {}


_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=120)
    role: Literal["student", "teacher", "parent"]
    class_level: int | None = Field(default=None, ge=1, le=12)
    # Parental/guardian consent is mandatory for student accounts (minors).
    guardian_consent: bool = False

    @model_validator(mode="after")
    def _require_class_level_for_students(self) -> "RegisterRequest":
        if self.role == "student" and self.class_level is None:
            raise ValueError("class_level is required when role is 'student'")
        if self.role == "student" and not self.guardian_consent:
            raise ValueError("guardian_consent is required when role is 'student'")
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
    must_change_password: bool = False


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    """Verification code only — no password fields (V1 fix)."""

    token: str = Field(min_length=16, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class DataExportResponse(BaseModel):
    """Self-service GDPR-style export of everything we store about the user."""

    user: dict
    profile: dict | None
    quiz_attempts: list[dict]
    parent_links: list[dict]


class MeResponse(BaseModel):
    user_id: int
    email: str
    role: str
    profile_id: int | None
    name: str | None
    class_level: int | None


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
    requested: int
    note: str | None = None


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


class RoleUpdateRequest(BaseModel):
    role: Literal["student", "teacher", "parent", "admin"]


class UserPublic(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime


class AdminOverview(BaseModel):
    users_total: int
    students: int
    teachers: int
    admins: int
    parents: int
    quiz_attempts_graded: int
    avg_score_pct: float | None


class ParentLinkRequest(BaseModel):
    student_id: int = Field(ge=1)


class ParentInviteLinkRequest(BaseModel):
    code: str = Field(min_length=8, max_length=128)


class AdminUsersPage(BaseModel):
    total: int
    items: list[UserPublic]
