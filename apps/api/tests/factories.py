"""Bangla-realistic row factories and sample text for Domain-E tests (E-16).

Why a shared module instead of per-file helpers: the low-coverage work
(``test_e2_coverage_gaps.py``), the fault-injection suite
(``test_e2_fault_injection.py``) and the property tests all need the same
objects, and three private copies would drift. Every factory takes an open
``Session`` and returns the committed row, so callers never repeat PK
juggling.

Two rules this file follows:

* **ASCII source.** All Bengali appears as ``\\uXXXX`` escapes (repo rule for
  new files: typing Bengali through an editor/transcript corrupts combining
  marks). ``tests/test_e2_factories.py`` asserts each constant decodes to the
  intended word by checking it against a second, independently written
  spelling, and ``BN`` words that exist in the shipped corpus are checked
  against the corpus itself.
* **Uniqueness by default.** Emails/codes are suffixed with a uuid4 fragment
  unless the caller passes one, so the same factory works against the
  persistent PostgreSQL test database (where rows survive a test) -- the
  reason ``test_single_use_tokens.py`` had to hand-roll ``uuid4().hex``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from bangla_gpt_api.auth.security import hash_password
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.db.models import (
    ChatMessage,
    ClassRoom,
    ClassStudent,
    Conversation,
    EmailVerification,
    PasswordReset,
    School,
    Student,
    StudentInvite,
    Teacher,
    User,
)

#: Demo password used across the suite (never a real credential).
PASSWORD = "Str0ngPassw0rd!"


# ── Bangla sample vocabulary (escapes only) ────────────────────────────────
# Each entry: logical name -> the escape sequence for the Bengali word. The
# comments give the transliteration so a reviewer can check the codepoints
# without an editor that renders Bengali.
BN: dict[str, str] = {
    "name": "\u09a8\u09be\u09ae",  # nam (name)
    "rahim": "\u09b0\u09b9\u09bf\u09ae",  # Rahim
    "karim": "\u0995\u09b0\u09bf\u09ae",  # Karim
    "student": "\u09b6\u09bf\u0995\u09cd\u09b7\u09be\u09b0\u09cd\u09a5\u09c0",  # shikkharthi
    "teacher": "\u09b6\u09bf\u0995\u09cd\u09b7\u0995",  # shikkhok
    # বিধ্যালয় is spelled with decomposed ya+nukta (U+09AF U+09BC): U+09DF is
    # composition-excluded, so NFC keeps the pair apart. The naive U+09DF
    # spelling is NOT NFC and is a different string to `in`/`==` -- the
    # vocabulary test in test_e2_factories.py caught exactly that.
    "school": "\u09ac\u09bf\u09a6\u09cd\u09af\u09be\u09b2\u09af\u09bc",  # biddaloy (school)
    # অধ্যায় ends in decomposed ya+nukta (U+09AF U+09BC), which is what NFC
    # keeps -- and what the shipped corpus actually contains (227 occurrences
    # of the pair, zero of U+09DF).
    "chapter": "\u0985\u09a7\u09cd\u09af\u09be\u09af\u09bc",  # odhyay (chapter)
    "science": "\u09ac\u09bf\u099c\u09cd\u099e\u09be\u09a8",  # biggan
    "math": "\u0997\u09a3\u09bf\u09a4",  # gonit
    "bangla": "\u09ac\u09be\u0982\u09b2\u09be",  # Bangla
    "photosynthesis": "\u09b8\u09be\u09b2\u09cb\u0995\u09b8\u0982\u09b6\u09cd\u09b2\u09c7\u09b7\u09a3",  # salok-songsleshon
    "plant": "\u0989\u09a6\u09cd\u09ad\u09bf\u09a6",  # udbhid
    "chlorophyll": "\u0995\u09cd\u09b2\u09cb\u09b0\u09cb\u09ab\u09bf\u09b2",  # chlorophyll
    "sunlight": "\u09b8\u09c2\u09b0\u09cd\u09af\u09c7\u09b0 \u0986\u09b2\u09cb",  # surjer alo
    "question": "\u09aa\u09cd\u09b0\u09b6\u09cd\u09a8",  # proshno
    "answer": "\u0989\u09a4\u09cd\u09a4\u09b0",  # uttor
    "cell": "\u0995\u09cb\u09b7",  # kosh (cell) -- a section heading in the sample corpus
    "what": "\u0995\u09c0",  # ki (what)
    "danda": "\u0964",  # the Bengali full stop
}

#: The class-6 science sentence from the shipped sample corpus
#: (``data/sample_nctb/class6_science.md``) -- real NCERT/NCTB-register
#: prose, not invented text. ``test_e2_factories.py`` asserts it is a
#: verbatim substring of that file, so this constant cannot drift.
BN_SENTENCE = (
    "\u09b8\u09ac\u09c1\u099c \u0989\u09a6\u09cd\u09ad\u09bf\u09a6 \u09b8\u09c2\u09b0\u09cd\u09af\u09c7\u09b0 "
    "\u0986\u09b2\u09cb\u09b0 \u0989\u09aa\u09b8\u09cd\u09a5\u09bf\u09a4\u09bf\u09a4\u09c7 \u0995\u09be\u09b0\u09cd\u09ac\u09a8 "
    "\u09a1\u09be\u0987-\u0985\u0995\u09cd\u09b8\u09be\u0987\u09a1 \u0993 \u09aa\u09be\u09a8\u09bf \u09a5\u09c7\u0995\u09c7 "
    "\u0995\u09cd\u09b2\u09cb\u09b0\u09cb\u09ab\u09bf\u09b2\u09c7\u09b0 \u09b8\u09be\u09b9\u09be\u09af\u09cd\u09af\u09c7 "
    "\u09a8\u09bf\u099c\u09c7\u09b0 \u0996\u09be\u09a6\u09cd\u09af \u09a4\u09c8\u09b0\u09bf \u0995\u09b0\u09c7"
    + BN["danda"]
)

#: A student's question about that sentence (what the tutor is asked).
BN_QUESTION = (
    f"{BN['photosynthesis']} \u0995\u09c0 \u098f\u09ac\u0982 \u0995\u09c0\u09ad\u09be\u09ac\u09c7 "
    f"\u0998\u099f\u09c7{BN['danda']}"
)

#: A question the shipped sample corpus grounds verbatim ("## কোষ কী" is a
#: section heading in ``class6_science.md``), so routes reach the provider
#: instead of refusing at the retrieval gate.
BN_GROUNDED_QUESTION = f"{BN['cell']} {BN['what']}?"

#: Bangla-nationality mobile number in the +8801XXXXXXXXX form the PII
#: scrubber recognises (kept fake: 017 prefix + zeros/sequence).
BN_PHONE = "01712345678"


def unique_email(prefix: str = "student") -> str:
    """A fresh ``prefix-<uuid>@example.test`` address (Postgres-safe)."""
    return f"{prefix}-{uuid4().hex[:12]}@example.test"


def unique_code() -> str:
    """A fresh 64-hex-char stand-in for a stored token/code hash."""
    return uuid4().hex + uuid4().hex


def utcnow() -> datetime:
    """Naive UTC 'now' -- the convention every ``UtcDateTime`` column uses."""
    return datetime.now(UTC).replace(tzinfo=None)


def make_user(
    db: Session,
    *,
    role: str = "student",
    email: str | None = None,
    password: str = PASSWORD,
    school_id: int | None = None,
    email_verified: bool = True,
    **overrides: Any,
) -> User:
    """Insert a ``User`` row and return it (committed)."""
    user = User(
        email=email or unique_email(role),
        password_hash=hash_password(password),
        role=role,
        school_id=school_id,
        email_verified=email_verified,
        **overrides,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_student(
    db: Session,
    *,
    user: User | None = None,
    name: str | None = None,
    class_level: int = 6,
    **overrides: Any,
) -> Student:
    """Insert a ``Student`` profile, creating its ``User`` when omitted."""
    student = Student(
        user_id=(user or make_user(db, role="student")).id,
        name=name or f"{BN['rahim']} {BN['karim']}",
        class_level=class_level,
        **overrides,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def make_teacher(db: Session, *, user: User | None = None, name: str | None = None) -> Teacher:
    """Insert a ``Teacher`` profile, creating its ``User`` when omitted."""
    teacher = Teacher(
        user_id=(user or make_user(db, role="teacher")).id,
        name=name or f"{BN['teacher']} {BN['rahim']}",
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return teacher


def make_school(db: Session, *, name: str | None = None, code: str | None = None) -> School:
    """Insert a tenancy root."""
    school = School(
        name=name or f"{BN['school']} {uuid4().hex[:6]}",
        code=code or f"BN-{uuid4().hex[:8].upper()}",
    )
    db.add(school)
    db.commit()
    db.refresh(school)
    return school


def make_classroom(
    db: Session, *, school: School, class_level: int = 6, section: str = "A"
) -> ClassRoom:
    """Insert a classroom inside ``school``."""
    room = ClassRoom(school_id=school.id, class_level=class_level, section=section)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def enroll(db: Session, *, classroom: ClassRoom, student: Student) -> ClassStudent:
    """Enroll ``student`` in ``classroom``."""
    link = ClassStudent(classroom_id=classroom.id, student_id=student.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def make_verification(
    db: Session,
    *,
    user: User,
    token_hash: str | None = None,
    expires_in_minutes: int = 30,
) -> EmailVerification:
    """Insert an email-verification row."""
    row = EmailVerification(
        user_id=user.id,
        token_hash=token_hash or unique_code(),
        expires_at=utcnow() + timedelta(minutes=expires_in_minutes),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_password_reset(
    db: Session,
    *,
    user: User,
    token_hash: str | None = None,
    expires_in_minutes: int = 30,
) -> PasswordReset:
    """Insert a password-reset row."""
    row = PasswordReset(
        user_id=user.id,
        token_hash=token_hash or unique_code(),
        expires_at=utcnow() + timedelta(minutes=expires_in_minutes),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_student_invite(
    db: Session,
    *,
    classroom: ClassRoom,
    student: Student,
    email: str | None = None,
    code_hash: str | None = None,
    expires_in_minutes: int = 1440,
) -> StudentInvite:
    """Insert a class-import claim code row."""
    row = StudentInvite(
        code_hash=code_hash or unique_code(),
        email=email or unique_email("invitee"),
        classroom_id=classroom.id,
        student_id=student.id,
        expires_at=utcnow() + timedelta(minutes=expires_in_minutes),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_conversation(
    db: Session, *, student: Student, title: str | None = None, **overrides: Any
) -> Conversation:
    """Insert a chat conversation owned by ``student``.

    ``created_at`` can be overridden so retention/cutoff tests can place a
    conversation in the past without sleeping or patching the model default.
    """
    row = Conversation(student_id=student.id, title=title or BN_QUESTION[:40], **overrides)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_chat_message(
    db: Session,
    *,
    conversation: Conversation,
    role: str = "user",
    content: str | None = None,
    **overrides: Any,
) -> ChatMessage:
    """Insert one chat message."""
    row = ChatMessage(
        conversation_id=conversation.id,
        role=role,
        content=content or (BN_QUESTION if role == "user" else BN_SENTENCE),
        **overrides,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_chunk(
    *,
    text: str | None = None,
    chunk_id: str | None = None,
    class_level: int = 6,
    subject: str | None = None,
    chapter: str | None = None,
    section: str | None = None,
    page: int | None = 12,
) -> Chunk:
    """Build an in-memory curriculum chunk (no database involved)."""
    return Chunk(
        id=chunk_id or f"c-{uuid4().hex[:10]}",
        text=text or BN_SENTENCE,
        meta=CurriculumMeta(
            curriculum_year=2024,
            class_level=class_level,
            subject=subject or BN["science"],
            book=f"{BN['science']} {class_level}",
            source="factory",
            chapter=chapter or f"{BN['chapter']} 1",
            section=section,
            page=page,
        ),
    )


def make_corpus(size: int = 4, **kwargs: Any) -> list[Chunk]:
    """A small deterministic corpus of distinct chunks."""
    return [
        make_chunk(
            chunk_id=f"factory-{i}",
            text=f"{BN_SENTENCE} ({i})",
            chapter=f"{BN['chapter']} {i + 1}",
            **kwargs,
        )
        for i in range(size)
    ]
