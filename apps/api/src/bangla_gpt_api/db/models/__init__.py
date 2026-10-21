"""Model surface, re-exported by domain (C-03).

The 978-line module was split by domain; every name it exported stays
importable from `bangla_gpt_api.db.models`, so no call site changes.
"""

from __future__ import annotations

# The pre-split module imported Base at top level, so `db.models.Base` resolved
# and call sites (tests build their own tables) still reach for it here.
from bangla_gpt_api.db.base import Base as Base
from bangla_gpt_api.db.models.base import (
    _utcnow,
)
from bangla_gpt_api.db.models.content import (
    ChapterContent,
    Notification,
    QuestionBankEntry,
    QuestionPaper,
    SavedNote,
    ShortTest,
    TeacherDocument,
)
from bangla_gpt_api.db.models.identity import (
    AuditLog,
    EmailBounce,
    EmailVerification,
    PasswordReset,
    User,
)
from bangla_gpt_api.db.models.learning import (
    AnswerLog,
    Assignment,
    ChapterProgress,
    Concept,
    ConceptMastery,
    ConceptPrerequisite,
    DailyActivity,
    PracticeItem,
    QuizAttempt,
    RevisionItem,
    StudentAbility,
    SupportPlan,
)
from bangla_gpt_api.db.models.people import (
    Parent,
    ParentInvite,
    ParentStudentLink,
    SchoolInvite,
    Student,
    StudentInvite,
    Teacher,
)
from bangla_gpt_api.db.models.platform import (
    AiJob,
    AiUsage,
    AnalyticsEventRow,
    ChatMessage,
    Conversation,
    Feedback,
    JobRun,
)
from bangla_gpt_api.db.models.school import (
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    School,
)

__all__ = [
    "AiJob",
    "AiUsage",
    "AnalyticsEventRow",
    "AnswerLog",
    "Assignment",
    "AuditLog",
    "Base",
    "ChapterContent",
    "ChapterProgress",
    "ChatMessage",
    "ClassRoom",
    "ClassStudent",
    "ClassTeacher",
    "Concept",
    "ConceptMastery",
    "ConceptPrerequisite",
    "Conversation",
    "DailyActivity",
    "EmailBounce",
    "EmailVerification",
    "Feedback",
    "JobRun",
    "Notification",
    "Parent",
    "ParentInvite",
    "ParentStudentLink",
    "PasswordReset",
    "PracticeItem",
    "QuestionBankEntry",
    "QuestionPaper",
    "QuizAttempt",
    "RevisionItem",
    "SavedNote",
    "School",
    "SchoolInvite",
    "ShortTest",
    "Student",
    "StudentAbility",
    "StudentInvite",
    "SupportPlan",
    "Teacher",
    "TeacherDocument",
    "User",
    "_utcnow",
]
