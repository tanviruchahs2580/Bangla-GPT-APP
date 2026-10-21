"""Pydantic models: misc (split out of schemas.py, C-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)

from bangla_gpt_api.schemas.base import (  # noqa: F401
    MAX_QUIZ_QUESTIONS as MAX_QUIZ_QUESTIONS,
)
from bangla_gpt_api.schemas.base import (
    QuizQuestionPublic as QuizQuestionPublic,
)
from bangla_gpt_api.schemas.base import (
    SourceRef as SourceRef,
)
from bangla_gpt_api.schemas.base import (
    StrictIn as StrictIn,
)
from bangla_gpt_api.schemas.base import (
    WeakCell as WeakCell,
)

CHAT_STRATEGIES: tuple[str, ...] = ("simple", "example", "book_language", "steps", "analogy")


EXPLANATION_STYLES: tuple[str, ...] = ("simple", "standard", "detailed")


class RoleUpdateRequest(StrictIn):
    # school_admin is a real role value now (plain string column, so
    # the migration stays green -- value round-trip is covered by tests).
    role: Literal["student", "teacher", "parent", "admin", "school_admin"]


class FeedbackAdminRow(BaseModel):
    """One queue item. Deliberately omits the reporter's identity beyond the
    id (triage needs the complaint, not the child's email)."""

    id: int
    user_id: int
    role: str
    rating: int
    comment: str | None
    message_id: int | None
    attempt_id: int | None
    triaged: bool
    triaged_at: datetime | None
    note: str | None
    created_at: datetime


class FeedbackQueuePage(BaseModel):
    rows: list[FeedbackAdminRow]
    total: int
    open_count: int
    limit: int
    offset: int


class StatusComponent(BaseModel):
    name: str
    ok: bool
    detail: str


class StatusOut(BaseModel):
    """Public service status page payload.

    Counts and booleans only -- never user data, never error strings from
    dependencies (which could leak hostnames or SQL).
    """

    status: str  # ok | degraded
    components: list[StatusComponent]
    checked_at: datetime


class WeakStudent(BaseModel):
    student_id: int
    name: str
    avg_score_pct: float | None = None
    attempts_graded: int
    trend: str  # down | up | flat
    at_risk: bool
    #: single-source weakness rollup (weakest first); empty = no weak concept
    weak_concepts: list[str] = []
    cells: dict[str, WeakCell]


class WeakMatrixOut(BaseModel):
    class_level: int
    concepts: list[str]
    students: list[WeakStudent]


class SupportPlanIn(StrictIn):
    student_id: int


class SupportPlanOut(BaseModel):
    id: int
    student_id: int
    teacher_id: int
    class_level: int
    focus_concepts: list[str]
    plan: dict[str, object]
    created_at: datetime | None = None


class AssignmentIn(StrictIn):
    """pick students (single class), one shared quiz, a due date."""

    student_ids: list[int] = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)
    num_questions: int = Field(default=5, ge=1, le=MAX_QUIZ_QUESTIONS)
    due_at: datetime


class AssignmentOut(BaseModel):
    id: int
    teacher_id: int
    subject: str
    chapter: str
    num_questions: int
    due_at: datetime
    questions: list[QuizQuestionPublic]
    attempts: list[dict[str, int]]
    created_at: datetime | None = None


class AssignmentProgressRow(BaseModel):
    """Completion list row: done = the student's attempt is graded."""

    student_id: int
    name: str
    attempt_id: int
    done: bool
    score_pct: float | None = None
    overdue: bool


class AssignmentMineOut(BaseModel):
    id: int
    attempt_id: int
    subject: str
    chapter: str
    questions: list[QuizQuestionPublic]
    due_at: datetime
    overdue: bool
    done: bool


class CoverageCell(BaseModel):
    """One class-subject cell of the curriculum coverage grid."""

    classroom_id: int
    class_level: int
    section: str
    subject: str
    taught: bool
    attempts: int
    attempts_graded: int
    avg_score_pct: float | None = None
    status: str  # mastered | practiced | taught | uncovered


class CoverageOut(BaseModel):
    """Class x subject coverage grid (cells flat; subjects = column order)."""

    subjects: list[str]
    cells: list[CoverageCell]


class ContentVersionRowOut(BaseModel):
    """Current-version summary of one chapter's append-only version chain."""

    subject: str
    class_level: int
    chapter: str
    current_version: int
    versions_total: int
    source: str  # ai | teacher (current version)
    updated_at: datetime | None = None
    updated_by_email: str | None = None


class KgGapOut(BaseModel):
    """one surfaced learning gap (weak concept -> missing prereq)."""

    concept: str
    prereq: str
    prereq_pct: float | None = None  # None = prereq never practiced
    prereq_total: int
    depth: int  # 1 = direct prerequisite


class KgGapsOut(BaseModel):
    weak_threshold_pct: float
    min_attempts: int
    gaps: list[KgGapOut]


class KgRebuildOut(BaseModel):
    concepts: int
    llm_concepts: int
    edges: int


TEACHER_DOCUMENT_KINDS: tuple[str, ...] = ("worksheet", "answer_key", "homework", "rubric")


TEACHER_DOCUMENT_PDF_KINDS: tuple[str, ...] = ("worksheet", "answer_key", "lesson_plan")


class WorksheetIn(BaseModel):
    class_level: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)


class HomeworkIn(WorksheetIn):
    pass


class RubricIn(WorksheetIn):
    pass


class AnswerKeyIn(BaseModel):
    """Answer key from an own paper (paper_id) OR an inline question list."""

    class_level: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str | None = Field(default=None, max_length=200)
    paper_id: int | None = None
    questions: list[str] | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def _questions_source(self) -> AnswerKeyIn:
        if (self.paper_id is None) == (self.questions is None):
            raise ValueError("exactly one of paper_id or questions must be provided")
        if self.questions is not None and not all(
            isinstance(q, str) and q.strip() for q in self.questions
        ):
            raise ValueError("questions entries must be non-empty strings")
        return self


class TeacherDocumentOut(BaseModel):
    id: int
    kind: str
    class_level: int
    subject: str
    chapter: str | None = None
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class GenerateDocumentOut(TeacherDocumentOut):
    """Generator response: the persisted document plus cited sources."""

    sources: list[SourceRef] = []


class NoteSourceRef(BaseModel):
    """Bounded pointer to what a saved note came from.

    Replaces an unbounded ``dict[str, Any]`` so a client cannot persist
    arbitrary JSON through the notes API (AUD-0052 / API-01). Only the
    known reference keys are accepted.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, max_length=64)
    chapter: str | None = Field(default=None, max_length=64)
    class_level: int | None = Field(default=None, ge=1, le=12)
    message_id: int | None = Field(default=None, ge=1)

    @model_serializer(mode="wrap")
    def _drop_unset(self, handler: Any) -> dict:
        """Serialize only the keys the client actually set.

        Keeps the previous wire shape (echo back exactly the reference that was
        stored) instead of padding it with nulls.
        """
        data = cast("dict[str, Any]", handler(self))
        return {k: v for k, v in data.items() if v is not None}


class SavedNoteIn(StrictIn):
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    source: Literal["tutor", "chapter", "other"] = "other"
    source_ref: NoteSourceRef | None = None


class SavedNoteOut(BaseModel):
    id: int
    title: str
    body: str
    source: str
    source_ref: NoteSourceRef | None = None
    created_at: datetime | None = None


class NotificationOut(BaseModel):
    id: int
    kind: str
    # i18n code resolved client-side (never final copy), e.g. notif_quiz_assigned
    code: str
    params: dict[str, Any] = {}
    link: str | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


AI_JOB_KINDS: tuple[str, ...] = ("worksheet", "answer_key", "homework", "rubric", "lesson_plan")


class AiJobIn(StrictIn):
    """Kind is NOT whitelisted at the door: unknown kinds are accepted into a
    queued job and fail in the runner (visible ``failed`` state + error is
    better product behavior than a bare 422 on a long-running API)."""

    kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    payload: dict[str, Any] = Field(default_factory=dict)


class AiJobOut(BaseModel):
    id: str
    kind: str
    status: str  # queued | generating | validating | ready | failed
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkloadOut(BaseModel):
    """Artifact counts x documented planning constants -- an ESTIMATE built
    from real row counts only (nothing is fabricated)."""

    counts: dict[str, int]
    minutes_saved: dict[str, int]
    total_minutes_saved: int
    estimate: bool
    methodology: str


class StudentPrefsOut(BaseModel):
    memory_enabled: bool
    learning_prefs: dict[str, Any] = {}


class StudentPrefsPatch(StrictIn):
    """Partial update; learning_prefs keys are whitelisted in the route
    (explanation_style in EXPLANATION_STYLES, subject_focus a 1-60 character
    string, or null to clear it)."""

    memory_enabled: bool | None = None
    learning_prefs: dict[str, Any] | None = None


class MemoryFactsOut(BaseModel):
    """Derived facts. When memory_enabled is false the facts are STILL
    returned to the owner (flagged enabled:false) but the tutor excludes
    the personalized context block."""

    memory_enabled: bool
    facts: dict[str, Any] = {}
    # i18n code explaining what disabling does (client renders the copy).
    on_disable_note_code: str = "memory_on_disable_note"
