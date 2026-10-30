"""The education-context block every AI call carries (split from common.py, F-077).

One concern: turn stored learning state into the prompt-side ``memory:`` line
and the logged request context, honouring the student's memory opt-out. Shared
by the tutor routes and the document generators; independent of any route.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AnswerLog, QuizAttempt, Student, User
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.schemas import EXPLANATION_STYLES
from bangla_gpt_api.services import atrisk, weakness
from bangla_gpt_api.services.context import (
    RequestContext,
    history_summary,
    snapshot_mastery,
)

logger = logging.getLogger(__name__)


# --- minimal honest personalization --------------------------------------
# The ONLY personalized blocks the tutor is allowed to receive: which chapters
# the student is demonstrably weak in (from graded attempts) and the requested
# explanation style. Both are gated on the per-student memory opt-out: when
# memory_enabled is False the builder returns "" and the prompt stays exactly
# as impersonal as it was before
EXPLANATION_STYLE_DIRECTIVES: dict[str, str] = {
    "simple": "সবচাইতে সহজ শব্দে ছোট করে বল।",
    "standard": "স্বাভাবিক ধারাবাহিক বিবরণ দাও।",
    "detailed": "প্রয়োজনীয় সব ধাপ ও উদাহরণসহ বিস্তারিত বল।",
}


def build_personalization_block(
    *,
    memory_enabled: bool,
    weak_chapters: list[str],
    explanation_style: str | None,
) -> str:
    """Compose the ``memory:`` line for RequestContext ("" = no personalization)."""
    if not memory_enabled:
        return ""
    parts: list[str] = []
    if weak_chapters:
        parts.append("weak_chapters=" + ",".join(weak_chapters[:3]))
    directive = EXPLANATION_STYLE_DIRECTIVES.get(explanation_style or "")
    if directive:
        parts.append(f"explanation_style={explanation_style}: {directive}")
    return " ".join(parts)


def _request_context(
    db: Session,
    user: User,
    *,
    class_level: int,
    subject: str | None = None,
    chapter: str | None = None,
    goal: str = "question",
    history: list | None = None,
    strategy: str | None = None,
) -> RequestContext:
    """the ONE construction point of the education context that
    accompanies every AI call (tutor ask/stream + the three generators).

    Also logs it (event ``ai_request_context``) for eval/cost attribution:
    log_fields carries counts and ids only -- never message content.

    memory opt-out: with ``Student.memory_enabled`` false NEITHER
    the mastery snapshot nor the personalization line is computed, so the
    prompt carries nothing learned about this student (honest, not
    cosmetic -- the derivation itself is skipped).
    """
    mastery: dict[str, float] = {}
    memory_block = ""
    student = db.execute(select(Student).where(Student.user_id == user.id)).scalar_one_or_none()
    memory_enabled = student is None or bool(student.memory_enabled)
    if student is not None and memory_enabled:
        # DB-side GROUP BY instead of full scan + Python aggregation
        # Intermediate step (O(1) rows instead of O(N)); snapshot projection DEFERRED per docs
        from sqlalchemy import Integer
        from sqlalchemy import cast as _cast

        rows = db.execute(
            select(
                AnswerLog.chapter,
                func.count().label("asked"),
                func.sum(_cast(AnswerLog.is_correct, Integer)).label("correct"),
            )
            .join(QuizAttempt, AnswerLog.attempt_id == QuizAttempt.id)
            .where(QuizAttempt.student_id == student.id)
            .group_by(AnswerLog.chapter)
        ).all()
        stats: dict[str, tuple[int, int]] = {
            chapter: (asked, int(correct or 0)) for chapter, asked, correct in rows
        }
        mastery = snapshot_mastery(
            {c: atrisk.cell_accuracy(asked, correct) for c, (asked, correct) in stats.items()}
        )
        prefs = student.learning_prefs if isinstance(student.learning_prefs, dict) else {}
        style = prefs.get("explanation_style")
        memory_block = build_personalization_block(
            memory_enabled=True,
            # the ONE weakness verdict (services.weakness): an inline
            # percentage here made the tutor personalise on a chapter the
            # Home screen does not call weak.
            weak_chapters=weakness.weak_names(db, student.id),
            explanation_style=style if style in EXPLANATION_STYLES else None,
        )
    ctx = RequestContext(
        role=user.role,
        class_level=class_level,
        subject=subject,
        chapter_id=chapter,
        goal=goal,
        history_summary=history_summary(len(history or []), strategy),
        mastery_snapshot=mastery,
        memory_block=memory_block,
    )
    json_log(logger, logging.INFO, "ai_request_context", **ctx.log_fields())
    return ctx
