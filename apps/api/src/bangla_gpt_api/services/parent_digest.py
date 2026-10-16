"""parent weekly digest v1.5 -- summary-only aggregates.

Hard privacy rule: the digest is assembled exclusively from aggregates
(session counts, graded-attempt counts, score averages, the at-risk
flag and chapter labels). Conversation titles and messages are NEVER
read here; the PASS-WHEN test seeds a sentinel message and asserts it
cannot appear in the digest.

Bengali strings use \\u escapes so the source stays ASCII-safe byte-wise.

* ``digest_due`` -- pure scheduler decision (Sunday 22:00 Dhaka, once
                           per ISO week; deduped by week key).
* ``collect_digest`` -- DB -> WeeklyDigest aggregates for one parent.
* ``build_body`` -- WeeklyDigest -> email text (pure, unit-testable).
* ``run_weekly_digest`` -- one pass over all linked parents; sends via the
                           mailer (or the injected sender in tests).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    Conversation,
    Parent,
    ParentStudentLink,
    QuizAttempt,
    Student,
    User,
)
from bangla_gpt_api.services import atrisk, mailer, weakness

# "Saptahik Pita-Mata Digest" (Bengali) / Weekly parent digest
DIGEST_SUBJECT = "সাপ্তাহিক অভিভাবক সারসংক্ষেপ / Weekly parent digest"
GREETING = "প্রিয় "
HEADER = "অভিভাবক সাপ্তাহিক সারসংক্ষেপ"
WEEK_SECONDS = 7 * 24 * 3600
DIGEST_WEEKDAY = 6  # Sunday
DIGEST_HOUR_UTC = 16  # 16:00 UTC = 22:00 Dhaka
WEAK_CHAPTER_LIMIT = 3

# Parent-facing copy for the weekly digest, in one place. The recipient is a
# Bangladeshi parent, so the digest is Bengali like the rest of the product.
STATUS_OK = "ভালো এগোচ্ছে"
STATUS_SUPPORT = "সহায়তা প্রয়োজন"
CLASS_LABEL = "শ্রেণি"
SESSIONS_SUFFIX = "টি পড়ার সেশন"
ATTEMPTS_SUFFIX = "টি মূল্যায়িত পরীক্ষা"
AVG_LABEL = "গড়"
WEAK_CHAPTERS_LABEL = "অনুশীলন দরকার এমন অধ্যায়:"
NO_ACTIVITY_LINE = "এ সপ্তাহে কোনো কার্যক্রম নেই — প্রতিদিন অল্প সময়ের রুটিন কাজে দেয়।"
PRIVACY_LINE_1 = "এই সারসংক্ষেপে শুধু পরিসংখ্যান আছে। আপনার সন্তানের ব্যক্তিগত টিউটর আলাপ"
PRIVACY_LINE_2 = "কখনোই এতে যোগ করা হয় না বা শেয়ার করা হয় না।"


def week_key(dt: datetime) -> str:
    return dt.strftime("%G-W%V")


def digest_due(now: datetime, last_key: str) -> tuple[bool, str]:
    """True once per ISO week, from Sunday DIGEST_HOUR_UTC onwards."""
    if now.weekday() != DIGEST_WEEKDAY or now.hour < DIGEST_HOUR_UTC:
        return False, last_key
    key = week_key(now)
    if key == last_key:
        return False, last_key
    return True, key


@dataclass(frozen=True)
class ChildSummary:
    name: str
    class_level: int
    sessions: int
    attempts_graded: int
    avg_score_pct: float | None
    at_risk: bool
    weak_chapters: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WeeklyDigest:
    parent_name: str
    week_label: str
    children: list[ChildSummary]


def build_body(digest: WeeklyDigest) -> str:
    """Render the email body. Aggregates and chapter labels ONLY.

    Bengali, like every other parent-facing surface in the product: the
    recipient is a Bangladeshi parent, and an English summary under a
    Bengali heading is not a digest they can read.
    """
    lines = [
        f"{GREETING}{digest.parent_name},",
        "",
        f"{HEADER} ({digest.week_label})",
        "আপনার সন্তানের এ সপ্তাহের সারসংক্ষেপ নিচে দেওয়া হলো।",
        "",
    ]
    for child in digest.children:
        avg = f"{child.avg_score_pct:.1f}%" if child.avg_score_pct is not None else "—"
        status = STATUS_SUPPORT if child.at_risk else STATUS_OK
        lines.append(
            f"- {child.name} ({CLASS_LABEL} {child.class_level}): "
            f"{child.sessions}{SESSIONS_SUFFIX}, {child.attempts_graded}{ATTEMPTS_SUFFIX}, "
            f"{AVG_LABEL} {avg} — {status}।"
        )
        if child.weak_chapters:
            lines.append(
                f"  {WEAK_CHAPTERS_LABEL} " + ", ".join(child.weak_chapters[:WEAK_CHAPTER_LIMIT])
            )
        if child.sessions == 0 and child.attempts_graded == 0:
            lines.append("  " + NO_ACTIVITY_LINE)
    lines += [
        "",
        PRIVACY_LINE_1,
        PRIVACY_LINE_2,
        "",
        "বাংলা GPT",
    ]
    return "\n".join(lines)


def collect_digest(
    db: Session, parent_id: int, since: datetime, now: datetime
) -> WeeklyDigest | None:
    """Aggregates for one parent's linked children over [since, now]."""
    parent = db.get(Parent, parent_id)
    if parent is None:
        return None
    links = (
        db.execute(
            select(ParentStudentLink.student_id).where(ParentStudentLink.parent_id == parent_id)
        )
        .scalars()
        .all()
    )
    if not links:
        return None
    children: list[ChildSummary] = []
    for student_id in links:
        student = db.get(Student, student_id)
        if student is None:
            continue
        sessions = int(
            db.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.student_id == student_id,
                    Conversation.created_at >= since,
                    Conversation.created_at <= now,
                )
            ).scalar_one()
        )
        attempts = (
            db.execute(
                select(QuizAttempt).where(
                    QuizAttempt.student_id == student_id,
                    QuizAttempt.created_at >= since,
                    QuizAttempt.created_at <= now,
                )
            )
            .scalars()
            .all()
        )
        graded = [a for a in attempts if a.status == "graded" and a.score_pct is not None]
        percents = [float(a.score_pct or 0.0) for a in graded]
        avg = atrisk.avg_pct(percents)
        trend = atrisk.score_trend(percents)
        # weakness comes from the single-source rollup (lifetime mastery,
        # knowledge.MIN_ATTEMPTS / WEAK_THRESHOLD_PCT) -- no private rule here,
        # so the digest line always matches Home and the teacher matrix.
        weak_chapters = [w.concept for w in weakness.weak_concepts(db, student_id)][
            :WEAK_CHAPTER_LIMIT
        ]
        children.append(
            ChildSummary(
                name=student.name,
                class_level=student.class_level,
                sessions=sessions,
                attempts_graded=len(graded),
                avg_score_pct=avg,
                at_risk=atrisk.is_at_risk(avg, trend),
                weak_chapters=weak_chapters,
            )
        )
    if not children:
        return None
    start = since.strftime("%d %b")
    end = (now - timedelta(seconds=1)).strftime("%d %b")
    return WeeklyDigest(
        parent_name=parent.name, week_label=f"{start} \u2013 {end}", children=children
    )


@dataclass
class DigestRunStats:
    families: int = 0
    delivered: int = 0
    undelivered: int = 0
    skipped: str | None = None


def run_weekly_digest(
    settings: Settings,
    db: Session,
    *,
    sender: Callable[..., bool] | None = None,
    now: datetime | None = None,
) -> DigestRunStats:
    """Send the weekly summary to every linked parent. Aggregate-only bodies."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    since = now - timedelta(seconds=WEEK_SECONDS)
    send = sender or mailer.send_mail
    stats = DigestRunStats()
    if sender is None and not mailer.smtp_configured(settings):
        stats.skipped = "smtp_not_configured"
        return stats
    parents = db.execute(select(Parent)).scalars().all()
    for parent in parents:
        user = db.get(User, parent.user_id)
        if user is None:
            continue
        digest = collect_digest(db, parent.id, since, now)
        if digest is None:
            continue
        stats.families += 1
        ok = send(settings, to=user.email, subject=DIGEST_SUBJECT, body=build_body(digest))
        if ok:
            stats.delivered += 1
        else:
            stats.undelivered += 1
    return stats
