"""Pydantic models: school (split out of schemas.py, C-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)

from bangla_gpt_api.schemas.base import (
    _EMAIL_PATTERN as _EMAIL_PATTERN,
)
from bangla_gpt_api.schemas.base import (  # noqa: F401
    StrictIn as StrictIn,
)


class SchoolCreateIn(StrictIn):
    name: str = Field(min_length=2, max_length=200)


class SchoolOut(BaseModel):
    id: int
    name: str
    code: str
    created_at: datetime


class SchoolInviteIn(StrictIn):
    role: Literal["teacher", "school_admin"] = "teacher"


class SchoolInviteOut(BaseModel):
    id: int
    school_id: int
    role: str
    code: str  # plaintext, returned exactly once
    created_at: datetime
    expires_at: datetime


class SchoolJoinIn(StrictIn):
    """Redeem a school invite code to create the staff account."""

    invite_code: str = Field(min_length=4, max_length=64)
    email: str = Field(min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=120)


class SchoolStaffOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    classroom_count: int


class SchoolOverviewOut(BaseModel):
    school_id: int
    name: str
    code: str
    students: int
    teachers: int
    classrooms: int
    staff: list[SchoolStaffOut]


class SchoolAtRiskRow(BaseModel):
    """Cross-class at-risk student (school dashboard)."""

    student_id: int
    name: str
    class_level: int
    section: str
    attempts_graded: int
    avg_score_pct: float | None = None
    trend: str  # down | up | flat


class SchoolHealthOut(BaseModel):
    """Learning-health aggregate for a whole school (summary buckets only)."""

    school_id: int
    name: str
    code: str
    students: int
    teachers: int
    classrooms: int
    sessions_7d: int
    strong: int
    support: int
    risk: int
    ungraded: int
    strong_pct: float
    support_pct: float
    risk_pct: float
    at_risk: list[SchoolAtRiskRow]
    # capacity info. The schools table has NO capacity column today,
    # so this is honestly None until one exists (no fabricated numbers).
    capacity: int | None = None


class SchoolInviteAdminOut(BaseModel):
    """Invite row for admin management; codes/hashes are never returned."""

    id: int
    school_id: int
    role: str
    used: bool
    created_at: datetime
    used_at: datetime | None = None
    expires_at: datetime | None = None


class SchoolStudentRow(BaseModel):
    """One roster row for the school-section list. Minimal PII: name only --
    never email/phone (child-data minimization)."""

    student_id: int
    name: str
    class_level: int
    section: str
    last_active: str | None = None  # ISO date (Dhaka) or None = no signal
    quiz_attempts: int = 0


class SchoolStudentPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SchoolStudentRow]


class SchoolTeacherRow(BaseModel):
    teacher_id: int
    name: str
    # '' rows in ClassTeacher mean 'all subjects' -- surfaced as the literal
    # string 'all' so clients never have to special-case the empty string.
    subjects: list[str] = []
    classrooms: int = 0


class SchoolClassRow(BaseModel):
    classroom_id: int
    class_level: int
    section: str
    students: int
    quiz_attempts: int
    attempts_graded: int
    avg_quiz_accuracy: float | None = None


class SchoolCoverageRow(BaseModel):
    """Per class_level: content coverage vs the subjects the school's
    students actually practice, plus chapter read coverage. Honest empty
    values -- an empty list means NO signal, not 'covered'."""

    class_level: int
    content_subjects: list[str] = []  # subjects with chapter_content rows
    asked_subjects: list[str] = []  # subjects seen in quiz attempts (proxy:
    # chat messages do not persist a subject column -- documented deviation)
    uncovered_subjects: list[str] = []
    chapters_available: int = 0
    chapters_read: int = 0
    chapters_completed: int = 0


class SchoolCoverageOut(BaseModel):
    rows: list[SchoolCoverageRow]


class SchoolActiveDay(BaseModel):
    date: str
    students: int


class SchoolAnalyticsOut(BaseModel):
    """K-anonymity-safe aggregate counts only: never per-student rows,
    never message content."""

    days: int
    active_by_date: list[SchoolActiveDay] = []
    daily_active_avg: float = 0.0
    questions_asked: int = 0
    quiz_attempts: int = 0
    attempts_graded: int = 0
    avg_quiz_score_pct: float | None = None
