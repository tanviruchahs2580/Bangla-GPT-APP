"""Seed the four role accounts the Playwright smoke suite signs in with.

AUD-EF-02 (issue #38). The suite drives the real web app against a real API
with the deterministic ``mock`` LLM provider; only the *accounts* are seeded,
because there is no product flow that lets an anonymous visitor create a
teacher, a parent or an admin (that is the point of those roles' provisioning).
Everything else in the journeys -- registering nothing, logging in, asking,
linking a parent via an invite code, reading the dashboards -- goes through the
real UI and the real API.

Idempotent: re-running updates the password of the same four rows and leaves
any other data alone. Usage::

    .venv/Scripts/python.exe apps/web/e2e/seed_e2e_users.py

Honours ``DATABASE_URL`` exactly like the API does, so the seeded rows always
land in the database the API under test is serving. Refuses to run unless
``ENV`` names a development/CI lane: the shared password below must never
exist on a production database (F-015).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Run from a checkout without the package installed (`python apps/web/e2e/...`)
#: src/ is the layout the API itself uses.
_SRC = Path(__file__).resolve().parents[2] / "api" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bangla_gpt_api.auth.security import hash_password
from bangla_gpt_api.config import NON_PRODUCTION_ENVS, Settings
from bangla_gpt_api.db.models import Parent, School, Student, Teacher, User
from bangla_gpt_api.db.session import (
    init_db,
    make_engine,
    make_session_factory,
)
from sqlalchemy import select

#: Shared password for every seeded account. Test-only, never used elsewhere.
PASSWORD = "E2ePass!2345"

ACCOUNTS = {
    "student": "student1@e2e.test",
    "teacher": "teacher1@e2e.test",
    "parent": "parent1@e2e.test",
    "admin": "admin1@e2e.test",
    "school_admin": "schooladmin1@e2e.test",
}

#: AUD-G-07/G-10: the visual and axe suites need accounts whose screens are
#: still in their seed state -- student1 and teacher1 accumulate
#: conversations, classrooms and roster rows from the journey, keyboard and
#: load runs, and a screenshot taken after those runs would record the side
#: effect rather than the UI. These two accounts are never written to by a
#: test, so their dashboards stay deterministic.
READONLY_ACCOUNTS = {
    "student": "student2@e2e.test",
    "teacher": "teacher2@e2e.test",
}

#: The school the seeded school_admin belongs to (AUD-G-10 audits /school).
SCHOOL_CODE = "E2E-SCHOOL"


def _upsert_user(db, email: str, role: str) -> User:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            role=role,
            password_hash=hash_password(PASSWORD),
            email_verified=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
    else:
        user.role = role
        user.password_hash = hash_password(PASSWORD)
        user.email_verified = True
        user.must_change_password = False
    return user


def _refuse_outside_test_envs(settings: Settings) -> None:
    """Refuse to seed unless ENV explicitly names a development/CI lane (F-015).

    This script upserts five accounts -- including a platform admin and a
    school_admin bound to ``E2E-SCHOOL`` -- with the shared literal password
    below, against whatever ``DATABASE_URL`` the shell exports, exactly like
    the API. It was written for CI, where that URL is always ephemeral; run
    once from a shell holding a production .env, it publishes a privileged
    account with a known password on the live system. The app-side convention
    (``NON_PRODUCTION_ENVS``) is used rather than ``is_production`` so an
    unrecognized or misspelled ENV also fails closed.
    """
    if settings.env.strip().lower() in NON_PRODUCTION_ENVS:
        return
    raise SystemExit(
        f"Refusing to seed e2e accounts: ENV={settings.env!r} is not a "
        f"development/CI lane ({', '.join(sorted(NON_PRODUCTION_ENVS))}). "
        "The seeded accounts share a published password; point this at a "
        "disposable database instead, e.g. "
        "ENV=test DATABASE_URL=sqlite:///./e2e.db."
    )


def seed() -> None:
    settings = Settings()  # reads DATABASE_URL like the API under test
    _refuse_outside_test_envs(settings)
    engine = make_engine(settings)
    init_db(engine)
    db = make_session_factory(engine)()
    try:
        student_user = _upsert_user(db, ACCOUNTS["student"], "student")
        if (
            db.execute(
                select(Student).where(Student.user_id == student_user.id)
            ).scalar_one_or_none()
            is None
        ):
            db.add(
                Student(
                    user_id=student_user.id,
                    name="E2E Student",
                    class_level=6,
                    consent_ip="127.0.0.1",
                    consent_version="e2e",
                )
            )

        teacher_user = _upsert_user(db, ACCOUNTS["teacher"], "teacher")
        if (
            db.execute(
                select(Teacher).where(Teacher.user_id == teacher_user.id)
            ).scalar_one_or_none()
            is None
        ):
            db.add(Teacher(user_id=teacher_user.id, name="E2E Teacher"))

        parent_user = _upsert_user(db, ACCOUNTS["parent"], "parent")
        if (
            db.execute(select(Parent).where(Parent.user_id == parent_user.id)).scalar_one_or_none()
            is None
        ):
            # F-115: a matra-heavy BD-convention name, so the real parent
            # screens render one. The student/teacher names stay Latin because
            # committed e2e assertions pin them ("E2E Student" in the smoke,
            # qa and w2 flow specs) and the visual baselines record them; the
            # varied name fixture set for unit tests lives in
            # apps/web/src/test/banglaNames.ts.
            db.add(
                Parent(
                    user_id=parent_user.id,
                    name="মোছাম্মৎ নূরজাহান বেগম",
                )
            )

        _upsert_user(db, ACCOUNTS["admin"], "admin")

        # school_admin needs a school; the dashboard 404s a provisioned admin
        # without one (routers/school.py: "No school linked to this account").
        school = db.execute(select(School).where(School.code == SCHOOL_CODE)).scalar_one_or_none()
        if school is None:
            school = School(name="E2E School", code=SCHOOL_CODE)
            db.add(school)
            db.flush()
        school_admin = _upsert_user(db, ACCOUNTS["school_admin"], "school_admin")
        school_admin.school_id = school.id

        for role, email in READONLY_ACCOUNTS.items():
            user = _upsert_user(db, email, role)
            if role == "student":
                if (
                    db.execute(
                        select(Student).where(Student.user_id == user.id)
                    ).scalar_one_or_none()
                    is None
                ):
                    db.add(
                        Student(
                            user_id=user.id,
                            name="E2E Visual Student",
                            class_level=6,
                            consent_ip="127.0.0.1",
                            consent_version="e2e",
                        )
                    )
            elif (
                db.execute(select(Teacher).where(Teacher.user_id == user.id)).scalar_one_or_none()
                is None
            ):
                db.add(Teacher(user_id=user.id, name="E2E Visual Teacher"))

        db.commit()
    finally:
        db.close()
        engine.dispose()
    print(
        "seeded roles "
        + ", ".join(f"{role}={email}" for role, email in {**ACCOUNTS, **READONLY_ACCOUNTS}.items())
        + f" (school={SCHOOL_CODE})"
        + f" (DATABASE_URL={os.environ.get('DATABASE_URL', settings.database_url)})"
    )


if __name__ == "__main__":
    seed()
