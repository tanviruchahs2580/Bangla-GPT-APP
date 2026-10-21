"""parent weekly digest v1.6 -- summary-only aggregates, bn + en.

Hard privacy rule: the digest is assembled exclusively from aggregates
(session counts, graded-attempt counts, score averages, the at-risk
flag and chapter labels). Conversation titles and messages are NEVER
read here; the PASS-WHEN test seeds a sentinel message and asserts it
cannot appear in the digest.

H-11 additions (AUD-HI-17):

* the wrapper copy (greeting, heading, privacy note, signature) and the
  subject come from ``services.mailer.EMAIL_TEMPLATES`` in the language the
  guardian chose (``parents.digest_language``: ``bn`` or ``en``);
* a guardian with ``parents.digest_opt_out`` set is skipped before the send
  and counted as ``opted_out`` (never silently dropped);
* sends go through ``mailer.send_mail_checked``, so a hard-bounced address
  stops receiving bulk mail while transactional mail stays unaffected.

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
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.clock import utcnow
from bangla_gpt_api.db.models import (
    Conversation,
    Parent,
    ParentStudentLink,
    QuizAttempt,
    Student,
    User,
)
from bangla_gpt_api.services import atrisk, mailer, weakness

WEEK_SECONDS = 7 * 24 * 3600
DIGEST_WEEKDAY = 6  # Sunday
DIGEST_HOUR_UTC = 16  # 16:00 UTC = 22:00 Dhaka
WEAK_CHAPTER_LIMIT = 3

#: Per-language copy for the dynamic child lines. Everything fixed (greeting,
#: heading, privacy note, signature) lives in the mailer template; this dict
#: holds only what depends on the collected aggregates.
COPY: dict[str, dict[str, str]] = {
    "bn": {
        "status_ok": "\u09ad\u09be\u09b2\u09cb \u098f\u0997\u09cb\u099a\u09cd\u099b\u09c7",
        "status_support": "\u09b8\u09b9\u09be\u09af\u09bc\u09a4\u09be "
        "\u09aa\u09cd\u09b0\u09af\u09bc\u09cb\u099c\u09a8",
        "class_label": "\u09b6\u09cd\u09b0\u09c7\u09a3\u09bf",
        "sessions_suffix": "\u099f\u09bf \u09aa\u09a1\u09bc\u09be\u09b0 \u09b8\u09c7\u09b6\u09a8",
        "attempts_suffix": "\u099f\u09bf "
        "\u09ae\u09c2\u09b2\u09cd\u09af\u09be\u09af\u09bc\u09bf\u09a4 "
        "\u09aa\u09b0\u09c0\u0995\u09cd\u09b7\u09be",
        "avg_label": "\u0997\u09a1\u09bc",
        "weak_label": "\u0985\u09a8\u09c1\u09b6\u09c0\u09b2\u09a8 "
        "\u09a6\u09b0\u0995\u09be\u09b0 \u098f\u09ae\u09a8 "
        "\u0985\u09a7\u09cd\u09af\u09be\u09af\u09bc:",
        "no_activity": "\u098f "
        "\u09b8\u09aa\u09cd\u09a4\u09be\u09b9\u09c7 \u0995\u09cb\u09a8\u09cb "
        "\u0995\u09be\u09b0\u09cd\u09af\u0995\u09cd\u09b0\u09ae \u09a8\u09c7\u0987 "
        "\u2014 \u09aa\u09cd\u09b0\u09a4\u09bf\u09a6\u09bf\u09a8 "
        "\u0985\u09b2\u09cd\u09aa \u09b8\u09ae\u09af\u09bc\u09c7\u09b0 "
        "\u09b0\u09c1\u099f\u09bf\u09a8 \u0995\u09be\u099c\u09c7 "
        "\u09a6\u09c7\u09af\u09bc\u0964",
        "line": "- {name} ({class_label} {class_level}): "
        "{sessions}{sessions_suffix}, {attempts}{attempts_suffix}, {avg_label} {avg} "
        "\u2014 {status}\u0964",
    },
    "en": {
        "status_ok": "on track",
        "status_support": "needs support",
        "class_label": "Class",
        "sessions_suffix": " study sessions",
        "attempts_suffix": " graded tests",
        "avg_label": "average",
        "weak_label": "Chapters to practise:",
        "no_activity": "No activity this week \u2014 a short daily routine helps.",
        "line": "- {name} ({class_label} {class_level}): "
        "{sessions}{sessions_suffix}, {attempts}{attempts_suffix}, {avg_label} {avg} "
        "\u2014 {status}.",
    },
}


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


def build_body(digest: WeeklyDigest, language: str = "bn") -> str:
    """Render the email body for ``language``. Aggregates and labels ONLY.

    Bengali is the default and the product's parent-facing voice; the English
    wrapper exists for guardians whose preference is ``en``.
    """
    lang = mailer.normalize_language(language)
    copy = COPY[lang]
    lines: list[str] = []
    for child in digest.children:
        avg = f"{child.avg_score_pct:.1f}%" if child.avg_score_pct is not None else "\u2014"
        status = copy["status_support"] if child.at_risk else copy["status_ok"]
        lines.append(
            copy["line"].format(
                name=child.name,
                class_label=copy["class_label"],
                class_level=child.class_level,
                sessions=child.sessions,
                sessions_suffix=copy["sessions_suffix"],
                attempts=child.attempts_graded,
                attempts_suffix=copy["attempts_suffix"],
                avg_label=copy["avg_label"],
                avg=avg,
                status=status,
            )
        )
        if child.weak_chapters:
            lines.append(
                f"  {copy['weak_label']} " + ", ".join(child.weak_chapters[:WEAK_CHAPTER_LIMIT])
            )
        if child.sessions == 0 and child.attempts_graded == 0:
            lines.append("  " + copy["no_activity"])
    _subject, wrapper = mailer.render(
        "parent_digest",
        lang,
        parent_name=digest.parent_name,
        week_label=digest.week_label,
        children="\n".join(lines),
    )
    return wrapper


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
    #: Guardians who turned the digest off in their preferences (H-11).
    opted_out: int = 0
    #: Bulk sends refused because the address hard-bounced earlier (H-11).
    suppressed: int = 0
    skipped: str | None = None


def run_weekly_digest(
    settings: Settings,
    db: Session,
    *,
    sender: Callable[..., bool] | None = None,
    now: datetime | None = None,
) -> DigestRunStats:
    """Send the weekly summary to every linked, subscribed parent.

    Aggregate-only bodies; language and opt-out are read per parent, and bulk
    sends are checked against the bounce ledger (a suppressed address is
    refused by ``send_mail_checked`` and lands in ``undelivered``).
    """
    now = now or utcnow()
    since = now - timedelta(seconds=WEEK_SECONDS)
    send = sender or (
        lambda settings_, *, to, subject, body: mailer.send_mail_checked(
            db, settings_, to=to, subject=subject, body=body
        )
    )
    stats = DigestRunStats()
    if sender is None and not mailer.smtp_configured(settings):
        stats.skipped = "smtp_not_configured"
        return stats
    parents = db.execute(select(Parent)).scalars().all()
    for parent in parents:
        if parent.digest_opt_out:
            stats.opted_out += 1
            continue
        user = db.get(User, parent.user_id)
        if user is None:
            continue
        digest = collect_digest(db, parent.id, since, now)
        if digest is None:
            continue
        stats.families += 1
        language = mailer.normalize_language(parent.digest_language)
        ok = send(
            settings,
            to=user.email,
            subject=mailer.subject("parent_digest", language),
            body=build_body(digest, language),
        )
        if ok:
            stats.delivered += 1
        else:
            stats.undelivered += 1
    return stats
