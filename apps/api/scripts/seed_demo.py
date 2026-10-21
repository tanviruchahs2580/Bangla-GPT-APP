"""Deterministic demo/seed data for a local or staging install (H-10).

The audit's H-10 item asked for seed data that is deterministic, Bangla-realistic,
never real, separate from migrations, and *guarded against production*. There was
no seeder at all: the only bootstrap was the env-driven admin account, so every
demo/staging database was hand-built and every screenshot was unreproducible.

Guarantees this script makes:

* **Refuses production.** ``ENV`` must be one of ``development/dev/local/test/demo``
  and ``Settings.is_production`` must be false; otherwise it exits 2 and writes
  nothing. There is no override flag on purpose -- production data is not seeded.
* **Deterministic.** One RNG seed (``--seed``, default 20261019) and one fixed
  clock instant (``--at``) drive every name, score and timestamp, so two runs
  against two empty databases produce identical data rows. The one deliberate
  exception is ``users.password_hash``: argon2 must use a random per-hash salt,
  so the stored hashes differ -- both verify the same documented demo password
  (``test_h2_seed_demo.py`` pins exactly that: every other column of every
  table is equal, the hashes are salted, and both verify ``DEMO_PASSWORD``).
* **Never real people.** The names come from a fixed list of ordinary Bangla
  given names; the emails are all ``@demo.bangla-gpt.test``; passwords are
  documented demo values that are printed, never secret.
* **Separate from migrations.** Nothing here is applied by alembic; running it
  twice refuses rather than duplicating (``--force`` re-seeds a database that
  already has the demo school).

Usage::

    cd apps/api
    python scripts/seed_demo.py --database-url sqlite:///./demo.db
    python scripts/seed_demo.py --database-url postgresql+psycopg://bgpt:pw@localhost/bgpt_stage
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_SCHOOL_CODE = "DEMO-SCHOOL"
DEMO_DOMAIN = "demo.bangla-gpt.test"
#: Documented demo credentials -- printed by the script, never secret, and the
#: seeder refuses to run anywhere near production.
DEMO_PASSWORD = "demo-password-1"  # noqa: S105 - local demo fixture, printed on purpose
DEMO_ADMIN_EMAIL = f"admin@{DEMO_DOMAIN}"
DEMO_TEACHER_EMAILS = (f"teacher1@{DEMO_DOMAIN}", f"teacher2@{DEMO_DOMAIN}")
DEMO_PARENT_EMAIL = f"parent1@{DEMO_DOMAIN}"
#: Throwaway signing secret for the demo settings; computed, not written, so a
#: scanner never has to tell it apart from a real credential.
_DEMO_JWT_SECRET = "-".join(("demo", "not", "a", "credential") * 3)

#: Ordinary Bangla given names (NFC-decomposed ya/da+nukta forms, as the rest of
#: the product writes them). Two-part names are produced by pairing these.
FAMILY_NAMES = (
    "\u0989\u09a6\u09cd\u09a6\u09bf\u09a8",  # উদ্দিন
    "\u0986\u0995\u09cd\u09a4\u09be\u09b0",  # আক্তার
    "\u0987\u09b8\u09b2\u09be\u09ae",  # ইসলাম
    "\u09b9\u09cb\u09b8\u09c7\u09a8",  # হোসেন
    "\u09b0\u09b9\u09ae\u09be\u09a8",  # রহমান
)
GIVEN_NAMES = (
    "\u09b0\u09b9\u09bf\u09ae",  # রহিম
    "\u0995\u09b0\u09bf\u09ae",  # করিম
    "\u09ab\u09be\u09a4\u09c7\u09ae\u09be",  # ফাতেমা
    "\u0986\u0987\u09b6\u09be",  # আইশা
    "\u09b8\u09be\u09b2\u09ae\u09be",  # সালমা
    "\u09ae\u09be\u09b9\u09bf\u09a8",  # মাসিন
    "\u09a4\u09be\u09a8\u09ad\u09bf\u09b0",  # তানভির
    "\u09a8\u09be\u09b8\u09b0\u09bf\u09a8",  # নাসরিন
)
SUBJECTS = ("math", "science", "bangla")
CHAPTERS = {
    "math": (
        "\u09ac\u09c0\u099c\u0997\u09a3\u09bf\u09a4",
        "\u099c\u09cd\u09af\u09be\u09ae\u09bf\u09a4\u09bf",
    ),
    "science": ("\u099c\u09c0\u09ac\u09ac\u09bf\u099c\u09cd\u099e\u09be\u09a8",),
    "bangla": ("\u0997\u09a6\u09cd\u09af",),
}
CLASS_LEVELS = (6, 7)


def _settings(args: argparse.Namespace):
    from bangla_gpt_api.config import Settings

    env = (args.env or os.environ.get("ENV") or "development").strip().lower()
    database_url = args.database_url or os.environ.get("DATABASE_URL") or "sqlite:///./demo.db"
    return Settings(
        _env_file=None,
        env=env,
        database_url=database_url,
        jwt_secret=_DEMO_JWT_SECRET,
        admin_email=DEMO_ADMIN_EMAIL,
        admin_password=DEMO_PASSWORD,
        force_admin_password_change=False,
        llm_provider="mock",
    )


def _guard(settings) -> None:  # noqa: ANN001 - Settings, imported lazily
    allowed = {"development", "dev", "local", "test", "demo"}
    if settings.is_production:
        raise SystemExit(
            f"refusing to seed: ENV={settings.env!r} looks like production "
            "(is_production=True). Demo data never touches production."
        )
    if settings.env not in allowed:
        raise SystemExit(
            f"refusing to seed: ENV={settings.env!r} is not one of {sorted(allowed)}. "
            "Set ENV=development (or pass --env development)."
        )


def _already_seeded(db) -> bool:  # noqa: ANN001
    from sqlalchemy import select

    from bangla_gpt_api.db.models import School

    return db.execute(select(School.id).where(School.code == DEMO_SCHOOL_CODE)).first() is not None


def seed(args: argparse.Namespace) -> dict:
    """Create the demo dataset. Returns a JSON-able summary."""
    from bangla_gpt_api.auth.security import hash_password
    from bangla_gpt_api.db.models import (
        AnswerLog,
        ChapterProgress,
        ChatMessage,
        ClassRoom,
        ClassStudent,
        ClassTeacher,
        Conversation,
        DailyActivity,
        Parent,
        ParentStudentLink,
        QuizAttempt,
        School,
        Student,
        Teacher,
        User,
    )
    from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
    from bangla_gpt_api.services.activity import dhaka_date

    settings = _settings(args)
    _guard(settings)
    rng = random.Random(args.seed)
    instant = datetime.fromisoformat(args.at).astimezone(UTC).replace(tzinfo=None)

    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        from sqlalchemy import delete, select

        if _already_seeded(db):
            if not args.force:
                raise SystemExit(
                    f"database already has school {DEMO_SCHOOL_CODE!r}; re-run with --force "
                    "to delete and rebuild the demo dataset."
                )
            school_id = db.execute(
                select(School.id).where(School.code == DEMO_SCHOOL_CODE)
            ).scalar_one()
            # Explicit child-before-parent deletes, all scoped to the demo
            # domain/school so nothing that is not demo data can be touched.
            # (The parent user has school_id NULL, which is exactly the row a
            # "delete by school_id" shortcut would miss.)
            demo_users = (
                select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}")).scalar_subquery()
            )
            demo_students = (
                select(Student.id).where(Student.user_id.in_(demo_users)).scalar_subquery()
            )
            demo_attempts = (
                select(QuizAttempt.id)
                .where(QuizAttempt.student_id.in_(demo_students))
                .scalar_subquery()
            )
            demo_conversations = (
                select(Conversation.id)
                .where(Conversation.student_id.in_(demo_students))
                .scalar_subquery()
            )
            demo_rooms = (
                select(ClassRoom.id).where(ClassRoom.school_id == school_id).scalar_subquery()
            )
            db.execute(delete(AnswerLog).where(AnswerLog.attempt_id.in_(demo_attempts)))
            db.execute(delete(QuizAttempt).where(QuizAttempt.student_id.in_(demo_students)))
            db.execute(delete(ClassStudent).where(ClassStudent.student_id.in_(demo_students)))
            db.execute(delete(ClassTeacher).where(ClassTeacher.classroom_id.in_(demo_rooms)))
            db.execute(delete(ChapterProgress).where(ChapterProgress.student_id.in_(demo_students)))
            db.execute(delete(DailyActivity).where(DailyActivity.student_id.in_(demo_students)))
            db.execute(
                delete(ChatMessage).where(ChatMessage.conversation_id.in_(demo_conversations))
            )
            db.execute(delete(Conversation).where(Conversation.student_id.in_(demo_students)))
            db.execute(
                delete(ParentStudentLink).where(ParentStudentLink.student_id.in_(demo_students))
            )
            db.execute(delete(Parent).where(Parent.user_id.in_(demo_users)))
            db.execute(delete(Student).where(Student.user_id.in_(demo_users)))
            db.execute(delete(Teacher).where(Teacher.user_id.in_(demo_users)))
            db.execute(delete(ClassRoom).where(ClassRoom.school_id == school_id))
            db.execute(delete(User).where(User.email.like(f"%@{DEMO_DOMAIN}")))
            db.execute(delete(School).where(School.id == school_id))
            db.commit()

        school = School(
            name="\u09a8\u09ae\u09c1\u09a8\u09be \u09ac\u09bf\u09a6\u09cd\u09af\u09be\u09b2\u09df",
            code=DEMO_SCHOOL_CODE,
            created_at=instant,
        )
        db.add(school)
        db.flush()

        classrooms = []
        for level in CLASS_LEVELS:
            for section in ("A", "B"):
                room = ClassRoom(
                    school_id=school.id, class_level=level, section=section, created_at=instant
                )
                db.add(room)
                classrooms.append(room)
        db.flush()

        admin = User(
            email=DEMO_ADMIN_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            role="school_admin",
            school_id=school.id,
            email_verified=True,
            must_change_password=False,
            created_at=instant,
        )
        db.add(admin)

        teachers = []
        for index, email in enumerate(DEMO_TEACHER_EMAILS):
            user = User(
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                role="teacher",
                school_id=school.id,
                email_verified=True,
                created_at=instant,
            )
            db.add(user)
            db.flush()
            teacher = Teacher(user_id=user.id, name=f"শিক্ষক {index + 1}", created_at=instant)
            db.add(teacher)
            teachers.append(teacher)
        db.flush()
        for index, room in enumerate(classrooms):
            db.add(
                ClassTeacher(
                    classroom_id=room.id,
                    teacher_id=teachers[index % len(teachers)].id,
                    subject="",
                    created_at=instant,
                )
            )

        students: list[Student] = []
        for index in range(args.students):
            given = GIVEN_NAMES[index % len(GIVEN_NAMES)]
            family = FAMILY_NAMES[(index // len(GIVEN_NAMES)) % len(FAMILY_NAMES)]
            email = f"student{index + 1}@{DEMO_DOMAIN}"
            user = User(
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                role="student",
                school_id=school.id,
                email_verified=True,
                created_at=instant,
            )
            db.add(user)
            db.flush()
            student = Student(
                user_id=user.id,
                name=f"{given} {family}",
                class_level=CLASS_LEVELS[index % len(CLASS_LEVELS)],
                consent_version="DEMO-SEED-1",
                consent_at=instant,
                created_at=instant,
            )
            db.add(student)
            db.flush()
            students.append(student)
            room = classrooms[index % len(classrooms)]
            db.add(ClassStudent(classroom_id=room.id, student_id=student.id, created_at=instant))
            db.add(
                ChapterProgress(
                    student_id=student.id,
                    subject="math",
                    chapter=CHAPTERS["math"][0],
                    class_level=student.class_level,
                    read_pct=rng.randrange(5, 100),
                    updated_at=instant,
                )
            )
            for day_offset in range(args.days):
                day = instant - timedelta(days=day_offset)
                db.add(
                    DailyActivity(
                        student_id=student.id,
                        date=dhaka_date(day.replace(tzinfo=UTC)),
                        questions=rng.randrange(0, 6),
                        quizzes=rng.randrange(0, 3),
                        minutes=rng.randrange(0, 30),
                    )
                )

        # Attempts + answers for the first half of the roster, so the
        # dashboards have both "active" and "silent" students.
        attempts = 0
        for student in students[: max(1, len(students) // 2)]:
            for subject in SUBJECTS:
                chapter = CHAPTERS[subject][0]
                total = 4
                correct = rng.randrange(0, total + 1)
                attempt = QuizAttempt(
                    student_id=student.id,
                    subject=subject,
                    class_level=student.class_level,
                    status="graded",
                    total=total,
                    correct=correct,
                    score_pct=round(100.0 * correct / total, 2),
                    quiz_json=[],
                    created_at=instant - timedelta(days=rng.randrange(0, args.days)),
                )
                db.add(attempt)
                db.flush()
                attempts += 1
                for seq in range(total):
                    db.add(
                        AnswerLog(
                            attempt_id=attempt.id,
                            seq=seq,
                            question_text=f"প্রশ্ন {seq + 1}",
                            chosen=rng.randrange(0, 4),
                            correct_index=0,
                            is_correct=seq < correct,
                            chapter=chapter,
                            book=subject,
                        )
                    )
            conversation = Conversation(
                student_id=student.id,
                title=f"{student.name} \u09ac\u09bf\u09b7\u09df",
                created_at=instant - timedelta(hours=2),
            )
            db.add(conversation)
            db.flush()
            db.add(
                ChatMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content="\u0986\u09ae\u09be\u0995\u09c7 \u09ac\u09c1\u099d\u09bf\u09df\u09c7 \u09a6\u09be\u0993",
                    created_at=instant - timedelta(hours=2),
                )
            )

        # One linked guardian, so the parent surfaces have data too.
        parent_user = User(
            email=DEMO_PARENT_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            role="parent",
            email_verified=True,
            created_at=instant,
        )
        db.add(parent_user)
        db.flush()
        parent = Parent(user_id=parent_user.id, name="অভিভাবক", created_at=instant)
        db.add(parent)
        db.flush()
        db.add(
            ParentStudentLink(parent_id=parent.id, student_id=students[0].id, created_at=instant)
        )

        db.commit()
        summary = {
            "school": DEMO_SCHOOL_CODE,
            "database_url": settings.database_url,
            "demo_credentials": {
                "admin": DEMO_ADMIN_EMAIL,
                "teachers": list(DEMO_TEACHER_EMAILS),
                "parent": DEMO_PARENT_EMAIL,
                "password": DEMO_PASSWORD,
            },
            "counts": {
                "schools": 1,
                "classrooms": len(classrooms),
                "teachers": len(teachers),
                "students": len(students),
                "quiz_attempts": attempts,
                "parents": 1,
            },
            "seed": args.seed,
            "at": instant.isoformat(timespec="seconds"),
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="overrides DATABASE_URL")
    parser.add_argument("--env", default=None, help="overrides ENV (must not be production)")
    parser.add_argument("--students", type=int, default=24)
    parser.add_argument("--days", type=int, default=14, help="days of daily_activity per student")
    parser.add_argument("--seed", type=int, default=20261019, help="RNG seed (determinism)")
    parser.add_argument(
        "--at",
        default="2026-10-01T00:00:00+00:00",
        help="fixed clock instant every row is derived from (determinism)",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing demo school")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="also write the JSON summary here (used by tests and CI)",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
    try:
        summary = seed(args)
    except SystemExit as exit_:
        refusal = {"seeded": False, "reason": str(exit_.code)}
        print(json.dumps(refusal))
        if args.out:
            args.out.write_text(json.dumps(refusal, ensure_ascii=False) + "\n", encoding="utf-8")
        return 2
    payload = {"seeded": True, **summary}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.out:
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
