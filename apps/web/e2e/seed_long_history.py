"""Seed one long tutor conversation for the CPU-throttled performance traces.

AUD-G-19 / G-19 asks for the chat under a 4-6x CPU throttle *with a long chat
history*, which no UI flow can produce inside a test run (each message would
need a full mocked answer round-trip). This script writes the history directly
into the database the API under test is serving -- the same seeding shortcut
Section 10.2 of the master prompt allows -- and it is idempotent: the previous
"E2E long history" conversation for the seeded student is replaced on every
run, so the trace always starts from the same 120-message transcript.

Usage (DATABASE_URL must point at the API's database)::

    .venv/Scripts/python.exe apps/web/e2e/seed_long_history.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "api" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import delete, select  # noqa: E402

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.db.models import ChatMessage, Conversation, Student, User  # noqa: E402
from bangla_gpt_api.db.session import (  # noqa: E402
    init_db,
    make_engine,
    make_session_factory,
)

STUDENT_EMAIL = "student1@e2e.test"
TITLE = "E2E long history"
MESSAGES = 120

#: Realistic lengths: an answer the tutor would actually produce (four short
#: sections plus an evidence line), not "lorem ipsum" padding. Recycled with a
#: counter so every message differs.
USER_TURN = "কোষের গঠন ব্যাখ্যা করো? ({n})"
ASSISTANT_TURN = (
    "সহজ ব্যাখ্যা ({n}): কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যকরী একক। "
    "প্রতিটি কোষ একটি ঝিল্লি দিয়ে ঘেরা থাকে, ভেতরে নিউক্লিয়াস ও সাইটোপ্লাজম থাকে। "
    "ধাপে ধাপে: প্রথমে ঝিল্লির ভেতরে প্রবেশ, তারপর নিউক্লিয়াসে তথ্য পড়া, শেষে প্রোটিন তৈরি। "
    "উদাহরণ: গাছের কোষে ক্লোরোপ্লাস্ট থাকে, তাই পাতা সবুজ দেখায়। "
    "পাঠ্যবইয়ের ব্যাখ্যা অনুযায়ী কোষের তিনটি প্রধান অংশ—ঝিল্লি, নিউক্লিয়াস ও সাইটোপ্লাজম।"
)


def seed() -> None:
    settings = Settings()
    engine = make_engine(settings)
    init_db(engine)
    db = make_session_factory(engine)()
    try:
        user = db.execute(select(User).where(User.email == STUDENT_EMAIL)).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"{STUDENT_EMAIL} is not seeded; run seed_e2e_users.py first")
        student = db.execute(
            select(Student).where(Student.user_id == user.id)
        ).scalar_one_or_none()
        if student is None:
            raise SystemExit(f"{STUDENT_EMAIL} has no student profile")

        previous = (
            db.execute(
                select(Conversation).where(
                    Conversation.student_id == student.id, Conversation.title == TITLE
                )
            )
            .scalars()
            .all()
        )
        for conversation in previous:
            db.execute(
                delete(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
            )
            db.delete(conversation)
        db.flush()

        conversation = Conversation(student_id=student.id, title=TITLE)
        db.add(conversation)
        db.flush()
        for index in range(MESSAGES):
            if index % 2 == 0:
                db.add(
                    ChatMessage(
                        conversation_id=conversation.id,
                        role="user",
                        content=USER_TURN.format(n=index // 2 + 1),
                    )
                )
            else:
                db.add(
                    ChatMessage(
                        conversation_id=conversation.id,
                        role="assistant",
                        content=ASSISTANT_TURN.format(n=index // 2 + 1),
                        grounded=True,
                        sources_json=[
                            {
                                "book": "বিজ্ঞান",
                                "chapter": "অধ্যায় ২",
                                "section": "কোষ",
                                "page": 21,
                                "score": 0.82,
                                "excerpt": "কোষ হলো জীবদেহের গঠনগত ও কার্যকরী একক।",
                            }
                        ],
                    )
                )
        db.commit()
        print(
            f"seeded conversation '{TITLE}' id={conversation.id} "
            f"with {MESSAGES} messages for {STUDENT_EMAIL} "
            f"(DATABASE_URL={os.environ.get('DATABASE_URL', settings.database_url)})"
        )
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    seed()
