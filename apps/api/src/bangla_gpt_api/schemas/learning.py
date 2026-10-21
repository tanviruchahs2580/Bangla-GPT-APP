"""Pydantic models: learning (split out of schemas.py, C-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)

from bangla_gpt_api.schemas.base import (  # noqa: F401
    MAX_QUIZ_QUESTIONS as MAX_QUIZ_QUESTIONS,
)
from bangla_gpt_api.schemas.base import (
    MeResponse as MeResponse,
)
from bangla_gpt_api.schemas.base import (
    QuizQuestionPublic as QuizQuestionPublic,
)
from bangla_gpt_api.schemas.base import (
    StrictIn as StrictIn,
)


class ActivityDay(BaseModel):
    """one heatmap cell (date is ISO in Asia/Dhaka)."""

    date: str
    questions: int
    quizzes: int
    minutes: int


class ActivitySummary(BaseModel):
    """streak + heatmap window for a student."""

    streak: int
    today: str
    days: list[ActivityDay]


class ChapterStat(BaseModel):
    chapter: str
    asked: int
    correct: int
    accuracy: float


class RevisionReviewIn(StrictIn):
    """one revision attempt; -1 means 'I did not answer'."""

    chosen: int = Field(ge=-1, le=7)


class RevisionItemOut(BaseModel):
    id: int
    question: str
    options: list[str]
    correct_index: int
    chapter: str
    reps: int
    interval_days: int
    ease_factor: float
    due_date: str


class RevisionDueOut(BaseModel):
    today: str
    due_count: int
    items: list[RevisionItemOut]


class SearchHit(BaseModel):
    """one search result. kind drives the icon + landing route."""

    kind: Literal["subject", "chapter", "question"]
    title: str
    subtitle: str | None = None
    href: str
    score: float


class SearchResponse(BaseModel):
    query: str
    ask_action: bool
    hits: list[SearchHit]


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


class ConsentStatusOut(BaseModel):
    """consent re-confirm flow (guardian consent for minors)."""

    student_id: int
    current_version: str
    accepted_version: str | None
    accepted_at: datetime | None
    needs_reconfirm: bool


class ConsentReconfirmIn(StrictIn):
    accepted: bool


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


class QuizStartRequest(StrictIn):
    student_id: int
    class_level: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = Field(default=None, max_length=60)
    # chapter preselect for the workspace "অনুশীলন" tab.
    chapter: str | None = Field(default=None, max_length=200)
    num_questions: int = Field(default=5, ge=1, le=10)


class ReteachCardOut(BaseModel):
    """grounded re-teach card -- a surfaced KG gap paired with the
    first sentences of the prerequisite chapter itself (no AI text)."""

    concept: str
    prereq: str
    depth: int
    excerpt: str


class QuizStarted(BaseModel):
    attempt_id: int
    questions: list[QuizQuestionPublic]
    requested: int
    note: str | None = None
    reteach: list[ReteachCardOut] = Field(default_factory=list)


class QuizSubmitRequest(StrictIn):
    # Bounded by the same constant assignments generate from; see
    # MAX_QUIZ_QUESTIONS. A lower cap here makes an assignment unsubmittable.
    answers: list[int] = Field(min_length=1, max_length=MAX_QUIZ_QUESTIONS)


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
    reteach: list[ReteachCardOut] = Field(default_factory=list)


class ContinueLearning(BaseModel):
    subject: str | None = None
    chapter: str | None = None
    class_level: int | None = None
    excerpt: str | None = None


class QuickAction(BaseModel):
    label: str
    to: str
    icon: str | None = None


class Recommendation(BaseModel):
    type: str  # weak_quiz | continue | general
    subject: str | None = None
    chapter: str | None = None
    reason: str | None = None


class DashboardSummary(BaseModel):
    user: MeResponse
    today: str  # ISO date
    continue_learning: ContinueLearning | None = None
    quick_actions: list[QuickAction] = []
    recommendation: Recommendation | None = None
    progress: StudentProgress | None = None


class ChapterProgressIn(StrictIn):
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)
    class_level: int = Field(ge=1, le=12)
    read_pct: int | None = Field(default=None, ge=0, le=100)
    completed: bool | None = None
    bookmarked: bool | None = None


class ChapterProgressOut(BaseModel):
    subject: str
    chapter: str
    class_level: int
    read_pct: int
    completed: bool
    bookmarked: bool
    updated_at: datetime | None = None
