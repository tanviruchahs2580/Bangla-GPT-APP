import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    WithJsonSchema,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticCustomError


def _utc_iso_z(value: datetime) -> str:
    """ISO-8601 UTC with a ``Z`` suffix; a naive value is read as UTC.

    Columns are naive UTC (SQLite has no timezone type) but the write path
    keeps the tz-aware in-memory default (``expire_on_commit=False``), so the
    same row used to serialise as ``...Z`` on create and ``...`` on re-read.
    ECMAScript parses an offset-less date-time as LOCAL time, shifting every
    displayed timestamp by the viewer's offset, so one serialiser now
    normalises both paths (F-063).
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


#: Wire type for every datetime an API response carries. The serializer runs
#: in JSON mode only, so python-mode dumps and ORM comparisons keep real
#: datetimes; the explicit schema keeps ``format: date-time`` in the served
#: OpenAPI document (a bare PlainSerializer would degrade it to a string).
UtcDateTime = Annotated[
    datetime,
    PlainSerializer(_utc_iso_z, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]

# --- explicit explanation strategies -----------------------------------

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

# The most questions any generation path can put in front of a student, and so
# the ceiling for the answers they must be able to send back. Assignments take
# the largest set (25; quizzes and short tests cap at 10).
#
# One constant on purpose. This used to be two independent literals --
# AssignmentIn allowed 25 questions while QuizSubmitRequest.answers allowed 20
# items -- so a teacher could create a 21-question assignment that no student
# could ever submit: FastAPI rejected the body with 422 before the handler ran,
# the attempt stayed open forever, and nothing deletes an assignment. Tying
# both bounds to one name is what stops them drifting apart again.
MAX_QUIZ_QUESTIONS = 25


# --- identity-text hygiene (F-005 / API-04) ------------------------------
# Two classes are rejected, and only these two:
#   * U+0000 -- not storable by PostgreSQL at all, so accepting one here is a
#     500 on the production engine;
#   * the bidi embedding/override/isolate controls (U+202A-U+202E,
#     U+2066-U+2069) -- they let a value render as a different string in
#     rosters, reports and generated PDFs.
# Other C0/C1 characters stay allowed on purpose: PostgreSQL stores them, and
# legacy rows and fixtures carry mis-encoded bytes that a blanket control-char
# ban would start refusing (tests/test_auth_teacher.py registers such names).
# Applied to identity/profile fields (names, emails, phones, invite codes,
# school names). Free-text bodies -- chat turns, notes, feedback comments --
# deliberately keep the whole range: bidirectional text is legitimate inside
# prose and those surfaces quote content instead of rendering it as an
# identity. Rejection is a 422 whose error type carries the stable code
# ``invalid_characters``.
_FORBIDDEN_IDENTITY_CHARS_RE = re.compile("[\u0000\u202a-\u202e\u2066-\u2069]")


def reject_control_characters(value: str) -> str:
    """Reject control and bidi-formatting characters in an identity field."""
    if _FORBIDDEN_IDENTITY_CHARS_RE.search(value):
        raise PydanticCustomError(
            "invalid_characters",
            "must not contain control or bidirectional formatting characters",
        )
    return value


#: A user-identity string: name, email, phone or invite code.
IdentityText = Annotated[str, AfterValidator(reject_control_characters)]


class QuizExplainContext(BaseModel):
    """quiz review context handed to the tutor for a wrong item."""

    question: str = Field(min_length=3, max_length=500)
    options: list[str] = Field(min_length=2, max_length=8)
    correct_index: int = Field(ge=0)
    user_answer: int = Field(ge=-1)
    chapter: str | None = Field(default=None, max_length=200)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    class_level: int = Field(ge=1, le=12)
    # Bounded to the columns these are written to (subject VARCHAR(60),
    # chapter VARCHAR(200)) and to what is sensible to interpolate into the
    # provider prompt. Unbounded, a long value was a 500 on PostgreSQL
    # (StringDataRightTruncation on the INSERT) and a free prompt-bloat
    # channel on the AI routes.
    subject: str | None = Field(default=None, max_length=60)
    # optional chapter context from the unified workspace "জিজ্ঞাসা" tab.
    chapter: str | None = Field(default=None, max_length=200)
    # 'বুঝিয়ে দাও' — structured context of a wrong quiz answer.
    explain: QuizExplainContext | None = None
    # low-data mode — request a short answer to cut payload size.
    # StrictBool: the served contract declares a JSON boolean, while
    # Pydantic's lax bool would also accept 0/1 (API-02 drift).
    low_data: StrictBool = False


class SourceRef(BaseModel):
    book: str
    chapter: str
    section: str | None = None
    page: int | None = None
    score: float
    # sanitized evidence excerpt shown in the source → evidence modal.
    excerpt: str | None = None


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    sources: list[SourceRef] = []
    # Machine-readable refusal category ('unsafe_content' | 'insufficient_evidence').
    refused_reason: str | None = None
    # Soft post-generation signal that the answer leans on the cited evidence.
    citation_verified: bool | None = None
    # honest numeric confidence (formula in services/safety).
    confidence: float | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ConversationUpdate(BaseModel):
    """rename a conversation."""

    title: str = Field(min_length=1, max_length=120)


class MessageSearchHit(BaseModel):
    """one message matching the history search query."""

    conversation_id: int
    conversation_title: str | None
    message_id: int
    role: str
    snippet: str
    created_at: UtcDateTime


class ConversationOut(BaseModel):
    id: int
    title: str | None
    # last explanation strategy (drives the 'আমি বুঝিন' re-teach cycle).
    last_strategy: str | None = None
    created_at: UtcDateTime
    message_count: int = 0


class ChatSendRequest(BaseModel):
    message: str = Field(min_length=3, max_length=1000)
    class_level: int | None = Field(default=None, ge=1, le=12)
    subject: str | None = Field(default=None, max_length=60)
    # optional chapter context chip.
    chapter: str | None = Field(default=None, max_length=200)
    # 'আমি বুঝিন' — force the next re-teach strategy for this turn.
    reteach: bool = False
    # low-data mode — request a short answer to cut payload size.
    # StrictBool: the served contract declares a JSON boolean, while
    # Pydantic's lax bool would also accept 0/1 (API-02 drift).
    low_data: StrictBool = False
    # explicit strategy -- overrides the reteach rotation for this
    # turn and persists as Conversation.last_strategy. Literal typing makes
    # an invalid value a 422 without any route code.
    strategy: ChatStrategy | None = None
    # vision contract: optional inline image (validated in route).
    image: "ChatImageIn | None" = None


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    grounded: bool | None = None
    refused_reason: str | None = None
    sources: list[SourceRef] = []
    rating: int | None = None
    created_at: UtcDateTime
    # honest numeric confidence (formula documented in
    # main._answer_confidence). None for user turns / pre-wave answers read
    # before this field existed is impossible -- it is always computed.
    confidence: float | None = None


class FeedbackRequest(BaseModel):
    # -1 = down, +1 = up, 0 = no verdict. 0 stays valid deliberately: the field
    # is required, so it is the only way to send a comment with no thumbs
    # answer, and an aggregate that counts only -1/+1 is then correct rather
    # than incomplete. Tightening this to Literal[-1, 1] removes comment-only
    # feedback and breaks the coded 400 that a body with no target must get.
    rating: int = Field(ge=-1, le=1)
    message_id: int | None = None
    attempt_id: int | None = None
    comment: str | None = Field(default=None, max_length=500)


class FeedbackOut(BaseModel):
    """Explicit success body for POST /feedback (AUD-0052: served contract
    must match behaviour; the handler used to return an untyped dict)."""

    status: Literal["recorded"]


class AnalyticsEvent(BaseModel):
    """Privacy-safe product event; logged as structured JSON, never PII."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.]+$")
    props: dict[str, str | int | bool] = {}


_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    email: IdentityText = Field(min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    name: IdentityText = Field(min_length=2, max_length=120)
    role: Literal["student", "teacher", "parent"]
    class_level: int | None = Field(default=None, ge=1, le=12)
    # Parental/guardian consent is mandatory for student accounts (minors).
    # Both this and class_level are REQUIRED for role="student", but the
    # coupling cannot be expressed in the OpenAPI schema; the route enforces
    # it as a documented 409 (AUD-0053 / API-02) instead of a model-validator
    # ValueError, which surfaced as an undocumented 422.
    guardian_consent: bool = False
    # optional guardian phone (parent role); stored encrypted when
    # PII_ENC_KEY is configured.
    phone: IdentityText | None = Field(default=None, max_length=32)


class RegisterResponse(BaseModel):
    user_id: int
    role: str
    profile_id: int


class LoginRequest(BaseModel):
    email: IdentityText = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - an obvious placeholder or a fixture name, not a credential
    must_change_password: bool = False


class ForgotPasswordRequest(BaseModel):
    email: IdentityText = Field(min_length=5, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    """Verification code only — no password fields (V1 fix)."""

    token: str = Field(min_length=16, max_length=256)


class ResendVerificationRequest(BaseModel):
    """Unauthenticated resend for users stuck at login with email_unverified.

    The login endpoint issues no token for unverified accounts, so the
    previous authed-only resend was unreachable exactly when needed.
    Email is optional so already-authed callers can omit it (server uses
    their identity); unauthenticated callers must supply it. The endpoint
    always answers 202 with a generic body to avoid account enumeration.
    """

    email: IdentityText | None = Field(default=None, min_length=5, max_length=255)


# --- pagination contract (M-08) ---------------------------------------------
# ONE place defines the list-endpoint limits so they cannot drift silently
# per endpoint again (the audit found defaults 20/50/100/200 and caps
# 50/1000 across 135 operations). Three tiers, all offset-based:
#   * SMALL — progress/detail feeds (default 20, cap 50)
#   * STANDARD — interactive lists, the default for NEW paginated endpoints
#     (default 100, cap 200)
#   * ROSTER — school roster pages (default 50, cap 200)
# Fixed-window endpoints (message search 25, conversations 100) are capped
# lists by design, not pages; their values live here too so the whole
# surface is greppable from one module. Envelope: every endpoint that
# paginates MUST return total/limit/offset (see the *Page models below);
# bare capped arrays are allowed only for fixed windows.
SMALL_PAGE_DEFAULT_LIMIT = 20
SMALL_PAGE_MAX_LIMIT = 50
STANDARD_PAGE_DEFAULT_LIMIT = 100
STANDARD_PAGE_MAX_LIMIT = 200
ROSTER_PAGE_DEFAULT_LIMIT = 50
ROSTER_PAGE_MAX_LIMIT = 200
MESSAGE_SEARCH_WINDOW = 25
CONVERSATIONS_WINDOW = 100


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AccountDeleteConfirm(BaseModel):
    """F-142: irreversible self-service erasure re-authenticates the caller.

    A bearer token alone used to be enough to destroy an account (and, for
    a student, their entire learning history) permanently — a stolen
    60-minute token was a one-shot erasure weapon. The current password is
    required, exactly like /auth/mfa/disable.
    """

    password: str = Field(min_length=1, max_length=128)


# --- AUTH-001: TOTP multi-factor authentication -------------------------------
class MfaEnrollOut(BaseModel):
    """Fresh (unstored) secret + authenticator URI. Nothing is enabled yet."""

    secret: str
    otpauth_uri: str


class MfaVerifyIn(BaseModel):
    secret: str = Field(min_length=16, max_length=64)
    code: str = Field(min_length=6, max_length=6)
    # F-142 discipline, same contract as /auth/mfa/disable and DELETE
    # /users/me: binding a factor to the account is a security-state change,
    # so a bearer token alone (possibly a stolen 60-minute one) is not
    # enough — the current password must be re-supplied.
    password: str = Field(min_length=1, max_length=128)


class MfaDisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class MfaChallengeIn(BaseModel):
    mfa_token: str = Field(min_length=16, max_length=2048)
    code: str = Field(min_length=6, max_length=6)


class DataExportResponse(BaseModel):
    """Self-service GDPR-style export of everything we store about the user.

    F-063: this used to carry the profile, the quiz attempts and the guardian
    links and nothing else. For a student that omitted every conversation and
    every chat message -- the single largest body of personal data the product
    holds about a child, and the data most likely to be subject to a subject
    access request or a parental request. A portability response that silently
    stops at quiz scores is not a portability response.
    """

    user: dict
    profile: dict | None
    quiz_attempts: list[dict]
    parent_links: list[dict]
    conversations: list[dict] = []
    chat_messages: list[dict] = []
    learning_activity: list[dict] = []


class MeResponse(BaseModel):
    user_id: int
    email: str
    role: str
    profile_id: int | None
    name: str | None
    class_level: int | None
    phone: str | None = None  # decrypted guardian phone, owner only


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


class RevisionReviewIn(BaseModel):
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
    accepted_at: UtcDateTime | None
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
    subject: str | None = Field(default=None, max_length=60)
    # chapter preselect for the workspace "অনুশীলন" tab.
    chapter: str | None = Field(default=None, max_length=200)
    num_questions: int = Field(default=5, ge=1, le=10)


class QuizQuestionPublic(BaseModel):
    id: str
    question_text: str
    options: list[str]


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


class QuizSubmitRequest(BaseModel):
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


class RoleUpdateRequest(BaseModel):
    # school_admin is a real role value now (plain string column, so
    # the migration stays green -- value round-trip is covered by tests).
    role: Literal["student", "teacher", "parent", "admin", "school_admin"]


class UserPublic(BaseModel):
    id: int
    email: str
    role: str
    created_at: UtcDateTime


class AuditRowOut(BaseModel):
    """one audit_log row as seen by admins. detail never contains
    message content or PII -- only ids and outcome metadata."""

    id: int
    created_at: UtcDateTime
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
    """feedback triage queue transition (admin-only).

    Note is free text written BY the admin, so its length is bounded and
    the endpoint records who set it; it never enters user-facing payloads.
    """

    triaged: bool
    note: str | None = Field(default=None, max_length=500)


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
    triaged_at: UtcDateTime | None
    note: str | None
    created_at: UtcDateTime


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
    checked_at: UtcDateTime


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
    """refusal audit: aggregate counts only, never message content."""

    days: int
    total_refusals: int
    by_reason: dict[str, int]
    by_class: dict[str, int]
    last_refusal_at: UtcDateTime | None = None


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
    updated_at: UtcDateTime | None = None


class ClassRoomOut(BaseModel):
    """one classroom the teacher can manage."""

    id: int
    class_level: int
    section: str
    student_count: int


class ClassRoomCreateIn(BaseModel):
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


class ClassImportIn(BaseModel):
    """pasted CSV text ('name,email' header) for bulk enrollment."""

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
    """the seven generated sections of one chapter."""

    summary: str = Field(min_length=1, max_length=4000)
    notes: str = Field(min_length=1, max_length=12000)
    key_points: list[str] = Field(min_length=1, max_length=20)
    examples: list[str] = Field(min_length=1, max_length=20)
    practice_qs: list[str] = Field(min_length=1, max_length=20)
    homework: list[str] = Field(min_length=1, max_length=20)
    exam_tips: list[str] = Field(min_length=1, max_length=20)


class ChapterContentKey(BaseModel):
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
    sources: list[SourceRef] = []


class ChapterContentVersionOut(ChapterContentKey):
    version: int
    source: str
    created_at: UtcDateTime | None = None
    created_by: int | None = None


class DifficultySplit(BaseModel):
    """target share of easy/medium/hard questions; must sum to 100."""

    easy: int = Field(ge=0, le=100)
    medium: int = Field(ge=0, le=100)
    hard: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _check_total(self) -> "DifficultySplit":
        if self.easy + self.medium + self.hard != 100:
            raise ValueError("difficulty percentages must sum to 100")
        return self


class QPDraftIn(BaseModel):
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
    reviewed_at: UtcDateTime | None = None
    finalized_at: UtcDateTime | None = None
    created_at: UtcDateTime | None = None


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


# --- short tests (class + chapter ultra-fast classroom-wide test) -----


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
    created_at: UtcDateTime | None = None


class ShortTestMineOut(BaseModel):
    id: int
    classroom_id: int
    attempt_id: int | None = None
    subject: str
    chapter: str
    num_questions: int
    duration_min: int
    questions: list[QuizQuestionPublic]
    created_at: UtcDateTime | None = None
    expires_at: UtcDateTime | None = None
    expired: bool = False


# --- lesson plan copilot (8-section editable/printable plan) -----------


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
    # (additive): the plan is now also persisted as a TeacherDocument;
    # the id is exposed here without changing any existing field.
    document_id: int | None = None


# --- weak heatmap + at-risk detection + support plan --------------------


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
    #: single-source weakness rollup (weakest first); empty = no weak concept
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
    created_at: UtcDateTime | None = None


class AssignmentIn(BaseModel):
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
    due_at: UtcDateTime
    questions: list[QuizQuestionPublic]
    attempts: list[dict[str, int]]
    created_at: UtcDateTime | None = None


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
    due_at: UtcDateTime
    overdue: bool
    done: bool


# --- school onboarding (admin -> school code -> staff invite) ---------


class SchoolCreateIn(BaseModel):
    name: IdentityText = Field(min_length=2, max_length=200)


class SchoolOut(BaseModel):
    id: int
    name: str
    code: str
    created_at: UtcDateTime


class SchoolInviteIn(BaseModel):
    role: Literal["teacher", "school_admin"] = "teacher"


class SchoolInviteOut(BaseModel):
    id: int
    school_id: int
    role: str
    code: str  # plaintext, returned exactly once
    created_at: UtcDateTime
    expires_at: UtcDateTime


class SchoolJoinIn(BaseModel):
    """Redeem a school invite code to create the staff account."""

    invite_code: IdentityText = Field(min_length=4, max_length=64)
    email: IdentityText = Field(min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    name: IdentityText = Field(min_length=2, max_length=120)


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


# --- admin center (per-school stats, content versions, invite admin) ---


class AdminSchoolStatsOut(BaseModel):
    """One row of the admin school list with learning-health counts."""

    id: int
    name: str
    code: str
    created_at: UtcDateTime
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
    updated_at: UtcDateTime | None = None
    updated_by_email: str | None = None


class SchoolInviteAdminOut(BaseModel):
    """Invite row for admin management; codes/hashes are never returned."""

    id: int
    school_id: int
    role: str
    used: bool
    created_at: UtcDateTime
    used_at: UtcDateTime | None = None
    expires_at: UtcDateTime | None = None


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


# --- teacher documents (generic generators) --------------------------

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
    created_at: UtcDateTime | None = None


class GenerateDocumentOut(TeacherDocumentOut):
    """Generator response: the persisted document plus cited sources."""

    sources: list[SourceRef] = []


# --- saved notes ------------------------------------------------------


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


class SavedNoteIn(BaseModel):
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
    created_at: UtcDateTime | None = None


# --- notification feed -------------------------------------------------


class NotificationOut(BaseModel):
    id: int
    kind: str
    # i18n code resolved client-side (never final copy), e.g. notif_quiz_assigned
    code: str
    params: dict[str, Any] = {}
    link: str | None = None
    read_at: UtcDateTime | None = None
    created_at: UtcDateTime | None = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


# --- async generation jobs (spec section 37) ---------------------------

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
    created_at: UtcDateTime | None = None
    updated_at: UtcDateTime | None = None


# --- teacher workload metric ------------------------------------------


class WorkloadOut(BaseModel):
    """Artifact counts x documented planning constants -- an ESTIMATE built
    from real row counts only (nothing is fabricated)."""

    counts: dict[str, int]
    minutes_saved: dict[str, int]
    total_minutes_saved: int
    estimate: bool
    methodology: str


# --- vision contract ----------------------------------------------------
# (CHAT_STRATEGIES / ChatStrategy / EXPLANATION_STYLES live at the TOP of this
# module because ChatSendRequest, defined much earlier, references them.)


class ChatImageIn(BaseModel):
    """Optional inline image on a chat turn. Validated in the route:
    mime must be in _IMAGE_MIME_ALLOWED, the base64 payload must decode and
    the decoded bytes must stay <= _IMAGE_MAX_BYTES; violations answer with
    422 {"code": "image_invalid"}."""

    mime_type: str = Field(min_length=1, max_length=64)
    data_base64: str = Field(min_length=1)


# --- school section (school_admin own school; admin platform-wide) ------


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


# --- parent activity + period report ------------------------------------


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


# --- admin AI quality -----------------------------------------------------


class AdminAiQualityOut(BaseModel):
    """Counts only, never message content."""

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


# --- student memory / learning preferences --------------------------------


class StudentPrefsOut(BaseModel):
    memory_enabled: bool
    learning_prefs: dict[str, Any] = {}


class StudentPrefsPatch(BaseModel):
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


# Resolve the forward reference in ChatSendRequest.image (ChatImageIn is
# defined further down in this module).
ChatSendRequest.model_rebuild()
