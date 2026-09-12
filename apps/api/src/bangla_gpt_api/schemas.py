from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# --- Wave 2: explicit explanation strategies -----------------------------------

# Set accepted by ChatSendRequest.strategy. Deliberately independent of the
# reteach rotation cycle (services/teach_strategy.STRATEGIES): an explicit
# student choice overrides the rotation for that turn and persists as
# Conversation.last_strategy. Invalid values are rejected with 422 by the
# Literal typing itself.
CHAT_STRATEGIES: tuple[str, ...] = ("simple", "example", "book_language", "steps", "analogy")
ChatStrategy = Literal["simple", "example", "book_language", "steps", "analogy"]

# Whitelisted learning-preference keys (PATCH /students/me/prefs).
EXPLANATION_STYLES: tuple[str, ...] = ("simple", "standard", "detailed")
ExplanationStyle = Literal["simple", "standard", "detailed"]


class QuizExplainContext(BaseModel):
    """S1.7: quiz review context handed to the tutor for a wrong item."""

    question: str = Field(min_length=3, max_length=500)
    options: list[str] = Field(min_length=2, max_length=8)
    correct_index: int = Field(ge=0)
    user_answer: int = Field(ge=-1)
    chapter: str | None = Field(default=None, max_length=200)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    class_level: int = Field(ge=1, le=12)
    subject: str | None = None
    # S1.3: optional chapter context from the unified workspace "জিজ্ঞাসা" tab.
    chapter: str | None = None
    # S1.7: 'বুঝিয়ে দাও' — structured context of a wrong quiz answer.
    explain: QuizExplainContext | None = None
    # S1.13: low-data mode — request a short answer to cut payload size.
    low_data: bool = False


class SourceRef(BaseModel):
    book: str
    chapter: str
    section: str | None = None
    page: int | None = None
    score: float
    # S1.6: sanitized evidence excerpt shown in the source → evidence modal.
    excerpt: str | None = None


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    sources: list[SourceRef] = []
    # Machine-readable refusal category ('unsafe_content' | 'insufficient_evidence').
    refused_reason: str | None = None
    # Soft post-generation signal that the answer leans on the cited evidence.
    citation_verified: bool | None = None
    # Wave 2: honest numeric confidence (formula in services/safety).
    confidence: float | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ConversationUpdate(BaseModel):
    """S1.8: rename a conversation."""

    title: str = Field(min_length=1, max_length=120)


class MessageSearchHit(BaseModel):
    """S1.8: one message matching the history search query."""

    conversation_id: int
    conversation_title: str | None
    message_id: int
    role: str
    snippet: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    title: str | None
    # S1.5: last explanation strategy (drives the 'আমি বুঝিন' re-teach cycle).
    last_strategy: str | None = None
    created_at: datetime
    message_count: int = 0


class ChatSendRequest(BaseModel):
    message: str = Field(min_length=3, max_length=1000)
    class_level: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = None
    # S1.3: optional chapter context chip.
    chapter: str | None = None
    # S1.5: 'আমি বুঝিন' — force the next re-teach strategy for this turn.
    reteach: bool = False
    # S1.13: low-data mode — request a short answer to cut payload size.
    low_data: bool = False
    # Wave 2: explicit strategy -- overrides the reteach rotation for this
    # turn and persists as Conversation.last_strategy. Literal typing makes
    # an invalid value a 422 without any route code.
    strategy: ChatStrategy | None = None
    # Wave 2 vision contract: optional inline image (validated in route).
    image: "ChatImageIn | None" = None


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    grounded: bool | None = None
    refused_reason: str | None = None
    sources: list[SourceRef] = []
    rating: int | None = None
    created_at: datetime
    # Wave 2: honest numeric confidence (formula documented in
    # main._answer_confidence). None for user turns / pre-wave answers read
    # before this field existed is impossible -- it is always computed.
    confidence: float | None = None


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
    # S5.6: optional guardian phone (parent role); stored encrypted when
    # PII_ENC_KEY is configured.
    phone: str | None = Field(default=None, max_length=32)

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


# --- AUTH-001: TOTP multi-factor authentication -------------------------------
class MfaEnrollOut(BaseModel):
    """Fresh (unstored) secret + authenticator URI. Nothing is enabled yet."""

    secret: str
    otpauth_uri: str


class MfaVerifyIn(BaseModel):
    secret: str = Field(min_length=16, max_length=64)
    code: str = Field(min_length=6, max_length=6)


class MfaDisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class MfaChallengeIn(BaseModel):
    mfa_token: str = Field(min_length=16, max_length=2048)
    code: str = Field(min_length=6, max_length=6)


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
    phone: str | None = None  # S5.6: decrypted guardian phone, owner only


class ActivityDay(BaseModel):
    """S1.9: one heatmap cell (date is ISO in Asia/Dhaka)."""

    date: str
    questions: int
    quizzes: int
    minutes: int


class ActivitySummary(BaseModel):
    """S1.9: streak + heatmap window for a student."""

    streak: int
    today: str
    days: list[ActivityDay]


class ChapterStat(BaseModel):
    chapter: str
    asked: int
    correct: int
    accuracy: float


class RevisionReviewIn(BaseModel):
    """S1.10: one revision attempt; -1 means 'I did not answer'."""

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
    """S1.11: one search result. kind drives the icon + landing route."""

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
    """S5.8 consent re-confirm flow (guardian consent for minors)."""

    student_id: int
    current_version: str
    accepted_version: str | None
    accepted_at: datetime | None
    needs_reconfirm: bool


class ConsentReconfirmIn(BaseModel):
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


class QuizStartRequest(BaseModel):
    student_id: int
    class_level: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = None
    # S1.3: chapter preselect for the workspace "অনুশীলন" tab.
    chapter: str | None = None
    num_questions: int = Field(default=5, ge=1, le=10)


class QuizQuestionPublic(BaseModel):
    id: str
    question_text: str
    options: list[str]


class ReteachCardOut(BaseModel):
    """S4.5: grounded re-teach card -- a surfaced KG gap paired with the
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
    reteach: list[ReteachCardOut] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    # S3.1: school_admin is a real role value now (plain string column, so
    # the migration stays green -- value round-trip is covered by tests).
    role: Literal["student", "teacher", "parent", "admin", "school_admin"]


class UserPublic(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime


class AuditRowOut(BaseModel):
    """S5.6: one audit_log row as seen by admins. detail never contains
    message content or PII -- only ids and outcome metadata."""

    id: int
    created_at: datetime
    actor_user_id: int | None
    actor_role: str
    action: str
    target: str | None
    detail: dict


class AdminAuditPage(BaseModel):
    rows: list[AuditRowOut]
    total: int
    limit: int
    offset: int


class ImpersonateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


class ImpersonateOut(BaseModel):
    access_token: str
    user_id: int
    role: str
    expires_in_min: int


class TriageUpdate(BaseModel):
    """S5.10 feedback triage queue transition (admin-only).

    Note is free text written BY the admin, so its length is bounded and
    the endpoint records who set it; it never enters user-facing payloads.
    """

    triaged: bool
    note: str | None = Field(default=None, max_length=500)


class FeedbackAdminRow(BaseModel):
    """One queue item. Deliberately omits the reporter's identity beyond the
    id (R11: triage needs the complaint, not the child's email)."""

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
    """Public service status page payload (S5.10).

    Counts and booleans only -- never user data, never error strings from
    dependencies (which could leak hostnames or SQL).
    """

    status: str  # ok | degraded
    components: list[StatusComponent]
    checked_at: datetime


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


class RefusalAuditOut(BaseModel):
    """S4.8 refusal audit: aggregate counts only, never message content (R11)."""

    days: int
    total_refusals: int
    by_reason: dict[str, int]
    by_class: dict[str, int]
    last_refusal_at: datetime | None = None


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


class ChapterProgressIn(BaseModel):
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


class ClassRoomOut(BaseModel):
    """S2.2: one classroom the teacher can manage."""

    id: int
    class_level: int
    section: str
    student_count: int


class ClassRoomCreateIn(BaseModel):
    class_level: int = Field(ge=1, le=12)
    section: str = Field(default="GEN", min_length=1, max_length=8)


class RosterEntryOut(BaseModel):
    """S2.2: roster row; email/invite are present for CSV-created accounts."""

    student_id: int
    name: str
    class_level: int
    email: str | None = None
    invite_pending: bool = False
    attempts_graded: int = 0
    avg_score_pct: float | None = None


class ClassImportIn(BaseModel):
    """S2.2: pasted CSV text ('name,email' header) for bulk enrollment."""

    csv_text: str = Field(min_length=1, max_length=20000)


class ClassImportRowOut(BaseModel):
    name: str
    email: str
    status: str  # created | duplicate_email | invalid
    invite_code: str | None = None


class ClassImportOut(BaseModel):
    created: int
    failed: int
    rows: list[ClassImportRowOut]


class ChapterSections(BaseModel):
    """S2.3: the seven generated sections of one chapter."""

    summary: str = Field(min_length=1, max_length=4000)
    notes: str = Field(min_length=1, max_length=12000)
    key_points: list[str] = Field(min_length=1, max_length=20)
    examples: list[str] = Field(min_length=1, max_length=20)
    practice_qs: list[str] = Field(min_length=1, max_length=20)
    homework: list[str] = Field(min_length=1, max_length=20)
    exam_tips: list[str] = Field(min_length=1, max_length=20)


class ChapterContentKey(BaseModel):
    """S2.3: identifies one chapter across the version chain."""

    class_level: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)


class ChapterContentEditIn(ChapterContentKey):
    sections: ChapterSections


class TeacherContentOut(ChapterContentKey):
    version: int
    source: str  # ai | teacher
    sections: ChapterSections
    sources: list[SourceRef] = []


class ChapterContentVersionOut(ChapterContentKey):
    version: int
    source: str
    created_at: datetime | None = None
    created_by: int | None = None


class DifficultySplit(BaseModel):
    """S2.4: target share of easy/medium/hard questions; must sum to 100."""

    easy: int = Field(ge=0, le=100)
    medium: int = Field(ge=0, le=100)
    hard: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _check_total(self) -> "DifficultySplit":
        if self.easy + self.medium + self.hard != 100:
            raise ValueError("difficulty percentages must sum to 100")
        return self


class QPDraftIn(BaseModel):
    """S2.4: teacher request for a question-paper draft."""

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


class QPReviewDecision(BaseModel):
    ref: str
    action: Literal["accept", "edit"]
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    options: list[str] | None = Field(default=None, min_length=4, max_length=4)
    answer_index: int | None = Field(default=None, ge=0, le=3)

    @model_validator(mode="after")
    def _edit_needs_text(self) -> "QPReviewDecision":
        if self.action == "edit" and self.text is None:
            raise ValueError("edit decision must provide replacement text")
        return self


class QPReviewIn(BaseModel):
    decisions: list[QPReviewDecision] = Field(min_length=1)


class QPReplaceIn(BaseModel):
    ref: str
    chapter: str | None = Field(default=None, min_length=1, max_length=200)
    difficulty: Literal["easy", "medium", "hard"] | None = None


# --- S2.5: short tests (class + chapter ultra-fast classroom-wide test) -----


class ShortTestIn(BaseModel):
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


# --- S2.6: lesson plan copilot (8-section editable/printable plan) -----------


class LessonPlanIn(BaseModel):
    class_level: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)
    minutes: int = Field(default=35, ge=5, le=180)
    level: Literal["beginner", "average", "advanced"] = "average"


class LessonPlanOut(BaseModel):
    sections: dict[str, str]
    sources: list[SourceRef] = []
    class_level: int
    subject: str
    chapter: str
    minutes: int
    level: str
    # Wave 1 (additive): the plan is now also persisted as a TeacherDocument;
    # the id is exposed here without changing any existing field.
    document_id: int | None = None


# --- S2.7: weak heatmap + at-risk detection + support plan --------------------


class WeakCell(BaseModel):
    asked: int
    correct: int
    accuracy: float | None = None
    read: bool = False  # tutor/reading signal from chapter progress


class WeakStudent(BaseModel):
    student_id: int
    name: str
    avg_score_pct: float | None = None
    attempts_graded: int
    trend: str  # down | up | flat
    at_risk: bool
    #: S4.6 single-source weakness rollup (weakest first); empty = no weak concept
    weak_concepts: list[str] = []
    cells: dict[str, WeakCell]


class WeakMatrixOut(BaseModel):
    class_level: int
    concepts: list[str]
    students: list[WeakStudent]


class SupportPlanIn(BaseModel):
    student_id: int


class SupportPlanOut(BaseModel):
    id: int
    student_id: int
    teacher_id: int
    class_level: int
    focus_concepts: list[str]
    plan: dict[str, object]
    created_at: datetime | None = None


class AssignmentIn(BaseModel):
    """S2.8: pick students (single class), one shared quiz, a due date."""

    student_ids: list[int] = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=60)
    chapter: str = Field(min_length=1, max_length=200)
    num_questions: int = Field(default=5, ge=1, le=25)
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


# --- S3.1: school onboarding (admin -> school code -> staff invite) ---------


class SchoolCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class SchoolOut(BaseModel):
    id: int
    name: str
    code: str
    created_at: datetime


class SchoolInviteIn(BaseModel):
    role: Literal["teacher", "school_admin"] = "teacher"


class SchoolInviteOut(BaseModel):
    id: int
    school_id: int
    role: str
    code: str  # plaintext, returned exactly once
    created_at: datetime


class SchoolJoinIn(BaseModel):
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
    """Cross-class at-risk student (S3.2 school dashboard)."""

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
    # Wave 2: capacity info. The schools table has NO capacity column today,
    # so this is honestly None until one exists (no fabricated numbers).
    capacity: int | None = None


class CoverageCell(BaseModel):
    """One class-subject cell of the S3.3 curriculum coverage grid."""

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


# --- S3.5: admin center (per-school stats, content versions, invite admin) ---


class AdminSchoolStatsOut(BaseModel):
    """One row of the admin school list with learning-health counts."""

    id: int
    name: str
    code: str
    created_at: datetime
    teachers: int
    classrooms: int
    students: int
    sessions_7d: int


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


class SchoolInviteAdminOut(BaseModel):
    """Invite row for admin management; codes/hashes are never returned."""

    id: int
    school_id: int
    role: str
    used: bool
    created_at: datetime
    used_at: datetime | None = None


class KgGapOut(BaseModel):
    """S4.4: one surfaced learning gap (weak concept -> missing prereq)."""

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


# --- Wave 1: teacher documents (generic generators) --------------------------

# Kinds accepted by POST /teacher/generate/{kind}. lesson_plan documents are
# persisted by POST /teacher/lesson-plans and are NOT generatable here.
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
    def _questions_source(self) -> "AnswerKeyIn":
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
    payload: dict[str, Any] = {}
    created_at: datetime | None = None


class GenerateDocumentOut(TeacherDocumentOut):
    """Generator response: the persisted document plus cited sources."""

    sources: list[SourceRef] = []


# --- Wave 1: saved notes ------------------------------------------------------


class SavedNoteIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    source: Literal["tutor", "chapter", "other"] = "other"
    source_ref: dict[str, Any] | None = None


class SavedNoteOut(BaseModel):
    id: int
    title: str
    body: str
    source: str
    source_ref: dict[str, Any] | None = None
    created_at: datetime | None = None


# --- Wave 1: notification feed -------------------------------------------------


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


# --- Wave 1: async generation jobs (spec section 37) ---------------------------

# All five generator kinds can run as a background job.
AI_JOB_KINDS: tuple[str, ...] = ("worksheet", "answer_key", "homework", "rubric", "lesson_plan")


class AiJobIn(BaseModel):
    """Kind is NOT whitelisted at the door: unknown kinds are accepted into a
    queued job and fail in the runner (visible ``failed`` state + error is
    better product behavior than a bare 422 on a long-running API)."""

    kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    payload: dict[str, Any] = {}


class AiJobOut(BaseModel):
    id: str
    kind: str
    status: str  # queued | generating | validating | ready | failed
    payload: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- Wave 1: teacher workload metric ------------------------------------------


class WorkloadOut(BaseModel):
    """Artifact counts x documented planning constants -- an ESTIMATE built
    from real row counts only (nothing is fabricated)."""

    counts: dict[str, int]
    minutes_saved: dict[str, int]
    total_minutes_saved: int
    estimate: bool
    methodology: str


# --- Wave 2: vision contract ----------------------------------------------------
# (CHAT_STRATEGIES / ChatStrategy / EXPLANATION_STYLES live at the TOP of this
# module because ChatSendRequest, defined much earlier, references them.)


class ChatImageIn(BaseModel):
    """Optional inline image on a chat turn. Validated in the route:
    mime must be in _IMAGE_MIME_ALLOWED, the base64 payload must decode and
    the decoded bytes must stay <= _IMAGE_MAX_BYTES; violations answer with
    422 {"code": "image_invalid"}."""

    mime_type: str = Field(min_length=1, max_length=64)
    data_base64: str = Field(min_length=1)


# --- Wave 2: school section (school_admin own school; admin platform-wide) ------


class SchoolStudentRow(BaseModel):
    """One roster row for the school-section list. Minimal PII: name only --
    never email/phone (R11 child-data minimization)."""

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
    """K-anonymity-safe aggregate counts only (R11): never per-student rows,
    never message content."""

    days: int
    active_by_date: list[SchoolActiveDay] = []
    daily_active_avg: float = 0.0
    questions_asked: int = 0
    quiz_attempts: int = 0
    attempts_graded: int = 0
    avg_quiz_score_pct: float | None = None


# --- Wave 2: parent activity + period report ------------------------------------


class ParentReportOut(BaseModel):
    """JSON report for one linked child over a window. Server returns
    suggestion CODES + params only; the client renders the copy (i18n)."""

    student_id: int
    name: str
    class_level: int
    period: str  # weekly | monthly
    window_start: str
    window_end: str
    quizzes_taken: int
    quizzes_graded: int
    avg_score_pct: float | None = None
    chapters_read: int
    chapters_completed: int
    questions_asked: int
    weak_chapters: list[str] = []  # same source as the weekly digest (<60%)
    strengths: list[str] = []  # chapter accuracy >= 85 in the window
    suggestion_code: str
    suggestion_params: dict[str, Any] = {}


# --- Wave 2: admin AI quality -----------------------------------------------------


class AdminAiQualityOut(BaseModel):
    """Counts only, never message content (R11)."""

    days: int
    answers_total: int
    grounded_count: int
    ungrounded_count: int
    refusals_total: int
    refusals_by_reason: dict[str, int] = {}
    thumbs_up: int = 0
    thumbs_down: int = 0
    # confidence < 0.5 under the documented formula (see main._answer_confidence)
    low_confidence_count: int = 0
    # ChatMessage carries no model column -> always empty today (audit finding).
    by_model: dict[str, int] = {}
    # AI-002: estimated LLM spend (USD) over the same window, from ai_usage.
    cost_usd_total: float = 0.0
    cost_usd_by_model: dict[str, float] = {}


# --- Wave 2: student memory / learning preferences --------------------------------


class StudentPrefsOut(BaseModel):
    memory_enabled: bool
    learning_prefs: dict[str, Any] = {}


class StudentPrefsPatch(BaseModel):
    """Partial update; learning_prefs keys are whitelisted in the route
    (explanation_style in EXPLANATION_STYLES, subject_focus 1-60 chars)."""

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


# Resolve the forward reference in ChatSendRequest.image (ChatImageIn is
# defined further down in this module).
ChatSendRequest.model_rebuild()
