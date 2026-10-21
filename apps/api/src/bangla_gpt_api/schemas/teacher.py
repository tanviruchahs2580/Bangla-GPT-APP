"""Pydantic models: teacher (split out of schemas.py, C-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)

from bangla_gpt_api.schemas.base import (  # noqa: F401
    QuizQuestionPublic as QuizQuestionPublic,
)
from bangla_gpt_api.schemas.base import (
    SourceRef as SourceRef,
)
from bangla_gpt_api.schemas.base import (
    StrictIn as StrictIn,
)

CLASS_IMPORT_MAX_CHARS = 20_000


class ClassRoomOut(BaseModel):
    """one classroom the teacher can manage."""

    id: int
    class_level: int
    section: str
    student_count: int


class ClassRoomCreateIn(StrictIn):
    class_level: int = Field(ge=1, le=12)
    section: str = Field(default="GEN", min_length=1, max_length=8)


class RosterEntryOut(BaseModel):
    """roster row; email/invite are present for CSV-created accounts."""

    student_id: int
    name: str
    class_level: int
    email: str | None = None
    invite_pending: bool = False
    attempts_graded: int = 0
    avg_score_pct: float | None = None


class ClassImportIn(StrictIn):
    """pasted CSV text ('name,email' header) for bulk enrollment."""

    csv_text: str = Field(min_length=1, max_length=CLASS_IMPORT_MAX_CHARS)


class ClassImportRowOut(BaseModel):
    name: str
    email: str
    status: str  # created | duplicate_email | invalid
    invite_code: str | None = None


class ClassImportOut(BaseModel):
    created: int
    failed: int
    rows: list[ClassImportRowOut]


class ChapterSections(StrictIn):
    """the seven generated sections of one chapter."""

    summary: str = Field(min_length=1, max_length=4000)
    notes: str = Field(min_length=1, max_length=12000)
    key_points: list[str] = Field(min_length=1, max_length=20)
    examples: list[str] = Field(min_length=1, max_length=20)
    practice_qs: list[str] = Field(min_length=1, max_length=20)
    homework: list[str] = Field(min_length=1, max_length=20)
    exam_tips: list[str] = Field(min_length=1, max_length=20)


class ChapterContentKey(StrictIn):
    """identifies one chapter across the version chain."""

    class_level: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)


class ChapterContentEditIn(ChapterContentKey):
    sections: ChapterSections


class TeacherContentOut(ChapterContentKey):
    version: int
    source: str  # ai | teacher
    sections: ChapterSections
    sources: list[SourceRef] = Field(default_factory=list)


class ChapterContentVersionOut(ChapterContentKey):
    version: int
    source: str
    created_at: datetime | None = None
    created_by: int | None = None


class DifficultySplit(StrictIn):
    """target share of easy/medium/hard questions; must sum to 100."""

    easy: int = Field(ge=0, le=100)
    medium: int = Field(ge=0, le=100)
    hard: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _check_total(self) -> DifficultySplit:
        if self.easy + self.medium + self.hard != 100:
            raise ValueError("difficulty percentages must sum to 100")
        return self


class QPDraftIn(StrictIn):
    """teacher request for a question-paper draft."""

    class_level: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=60)
    chapters: list[str] = Field(min_length=1, max_length=8)
    exam_type: str = Field(min_length=1, max_length=40)
    marks: int = Field(ge=5, le=100)
    duration_min: int = Field(ge=5, le=300)
    difficulty: DifficultySplit = DifficultySplit(easy=30, medium=50, hard=20)


class QPQuestion(BaseModel):
    ref: str
    text: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    marks: int = Field(ge=1, le=20)
    difficulty: str
    chapter: str
    reviewed: bool = False


class QPOut(BaseModel):
    id: int
    class_level: int
    subject: str
    exam_type: str
    marks: int
    duration_min: int
    difficulty: dict[str, int]
    chapters: list[str]
    status: str  # draft | final
    questions: list[QPQuestion]
    meta: dict[str, object] = {}
    reviewed_at: datetime | None = None
    finalized_at: datetime | None = None
    created_at: datetime | None = None


class QPReviewDecision(StrictIn):
    ref: str
    action: Literal["accept", "edit"]
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    options: list[str] | None = Field(default=None, min_length=4, max_length=4)
    answer_index: int | None = Field(default=None, ge=0, le=3)

    @model_validator(mode="after")
    def _edit_needs_text(self) -> QPReviewDecision:
        if self.action == "edit" and self.text is None:
            raise ValueError("edit decision must provide replacement text")
        return self


class QPReviewIn(StrictIn):
    decisions: list[QPReviewDecision] = Field(min_length=1)


class QPReplaceIn(StrictIn):
    ref: str
    chapter: str | None = Field(default=None, min_length=1, max_length=200)
    difficulty: Literal["easy", "medium", "hard"] | None = None


class ShortTestIn(StrictIn):
    classroom_id: int
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)
    num_questions: int = Field(default=5, ge=1, le=10)
    duration_min: int = Field(default=10, ge=1, le=60)


class ShortTestOut(BaseModel):
    id: int
    classroom_id: int
    teacher_id: int
    subject: str
    chapter: str
    num_questions: int
    duration_min: int
    questions: list[QuizQuestionPublic]
    attempts: list[dict[str, int]]
    created_at: datetime | None = None


class ShortTestMineOut(BaseModel):
    id: int
    classroom_id: int
    attempt_id: int | None = None
    subject: str
    chapter: str
    num_questions: int
    duration_min: int
    questions: list[QuizQuestionPublic]
    created_at: datetime | None = None
    expires_at: datetime | None = None
    expired: bool = False


class LessonPlanIn(StrictIn):
    class_level: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)
    minutes: int = Field(default=35, ge=5, le=180)
    level: Literal["beginner", "average", "advanced"] = "average"


class LessonPlanOut(BaseModel):
    sections: dict[str, str]
    sources: list[SourceRef] = Field(default_factory=list)
    class_level: int
    subject: str
    chapter: str
    minutes: int
    level: str
    # (additive): the plan is now also persisted as a TeacherDocument;
    # the id is exposed here without changing any existing field.
    document_id: int | None = None
