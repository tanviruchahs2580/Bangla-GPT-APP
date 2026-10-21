"""Teacher content routes, split by resource (C-03): chapter content,
question papers, and the generated documents.

_content — C-03 split of ``routers/teacher_content.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    ChapterContent,
    User,
)
from bangla_gpt_api.providers import (
    ProviderError,
)
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES, coded
from bangla_gpt_api.schemas import (
    ChapterContentEditIn,
    ChapterContentKey,
    ChapterContentVersionOut,
    ChapterSections,
    SourceRef,
    TeacherContentOut,
)
from bangla_gpt_api.services.generators import (
    generate_chapter_content,
)

from ..common import (
    _request_context,
)
from ..deps import (
    AIGenerationUser,
    Ctx,
    DbSession,
    TeacherOrAdminUser,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)


def _content_next_version(db: Session, subject: str, class_level: int, chapter: str) -> int:
    current = db.execute(
        select(func.max(ChapterContent.version)).where(
            ChapterContent.subject == subject,
            ChapterContent.class_level == class_level,
            ChapterContent.chapter == chapter,
        )
    ).scalar_one_or_none()
    return (current or 0) + 1


def _content_current(
    db: Session, subject: str, class_level: int, chapter: str
) -> ChapterContent | None:
    return db.execute(
        select(ChapterContent)
        .where(
            ChapterContent.subject == subject,
            ChapterContent.class_level == class_level,
            ChapterContent.chapter == chapter,
        )
        .order_by(ChapterContent.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def _assert_content_writable(db: Session, row: ChapterContent, actor: User) -> None:
    """S-007: shared library for READS, school-scoped for WRITES.

    The chapter-content library is deliberately global (every school reads the
    same current version) but the append-only write path had no ownership
    check at all: any teacher could append the new "current" version of
    material another school authored, and every school then read the
    overwrite (proved in the QA audit, ``probe_content_xschool``).

    A write is allowed only when the current version was authored inside the
    actor's own tenancy, matched on ``User.school_id``:

    * same school id -> writable (school-less legacy accounts match
      school-less authors, preserving pre-school-layer behaviour);
    * another school -> 403 ``content_read_only``;
    * author deleted or ``created_by`` NULL (platform/system seed) -> 403,
      because there is no tenancy to match;
    * admins keep platform-wide write access, like every other admin surface.
    """
    if actor.role == "admin":
        return
    if row.created_by is not None:
        author = db.get(User, row.created_by)
        if author is not None and author.school_id == actor.school_id:
            return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "content_read_only",
            "message": "This chapter content was authored by another school and is read-only",
        },
    )


def _content_out(row: ChapterContent, sources: list[SourceRef] | None = None) -> TeacherContentOut:
    return TeacherContentOut(
        class_level=row.class_level,
        subject=row.subject,
        chapter=row.chapter,
        version=row.version,
        source=row.source,
        sections=ChapterSections.model_validate(row.payload),
        sources=sources or [],
    )


@router.post(
    "/teacher/content/generate",
    response_model=TeacherContentOut,
    responses=coded(403),
)
async def teacher_content_generate(
    app_ctx: Ctx, payload: ChapterContentKey, db: DbSession, teacher: AIGenerationUser
) -> TeacherContentOut:
    """one retrieval + one AI call fills all seven sections."""
    if app_ctx.tutor is None:
        raise HTTPException(status_code=503, detail="provider not configured")
    # S-007: generating when content already exists appends the new "current"
    # version, i.e. it is a write like PUT. Refuse it across the tenancy wall
    # BEFORE spending the provider call.
    current = _content_current(db, payload.subject, payload.class_level, payload.chapter)
    if current is not None:
        _assert_content_writable(db, current, teacher)
    try:
        sections, sources = await generate_chapter_content(
            app_ctx.tutor.index,
            app_ctx.tutor.provider,
            class_level=payload.class_level,
            subject=payload.subject,
            chapter=payload.chapter,
            context=_request_context(
                db,
                teacher,
                class_level=payload.class_level,
                subject=payload.subject,
                chapter=payload.chapter,
                goal="chapter_content",
            ),
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail="content generation failed") from exc
    version = _content_next_version(db, payload.subject, payload.class_level, payload.chapter)
    row = ChapterContent(
        subject=payload.subject,
        class_level=payload.class_level,
        chapter=payload.chapter,
        version=version,
        source="ai",
        payload=sections,
        created_by=teacher.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent generation for the same chapter: take the next slot.
        db.rollback()
        row.version = _content_next_version(
            db, payload.subject, payload.class_level, payload.chapter
        )
        db.add(row)
        db.commit()
    db.refresh(row)
    return _content_out(row, sources)


@router.get("/teacher/content/history", response_model=list[ChapterContentVersionOut])
def teacher_content_history(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    class_level: int,
    subject: str,
    chapter: str,
) -> list[ChapterContentVersionOut]:
    rows = (
        db.execute(
            select(ChapterContent)
            .where(
                ChapterContent.subject == subject,
                ChapterContent.class_level == class_level,
                ChapterContent.chapter == chapter,
            )
            .order_by(ChapterContent.version.desc())
        )
        .scalars()
        .all()
    )
    return [
        ChapterContentVersionOut(
            class_level=r.class_level,
            subject=r.subject,
            chapter=r.chapter,
            version=r.version,
            source=r.source,
            created_at=r.created_at,
            created_by=r.created_by,
        )
        for r in rows
    ]


@router.get("/teacher/content", response_model=TeacherContentOut)
def teacher_content_get(
    db: DbSession,
    teacher: TeacherOrAdminUser,
    class_level: int,
    subject: str,
    chapter: str,
) -> TeacherContentOut:
    row = _content_current(db, subject, class_level, chapter)
    if row is None:
        raise HTTPException(status_code=404, detail="content not found")
    return _content_out(row)


@router.put("/teacher/content", response_model=TeacherContentOut, responses=coded(403))
def teacher_content_edit(
    payload: ChapterContentEditIn, db: DbSession, teacher: TeacherOrAdminUser
) -> TeacherContentOut:
    """teacher edits append a new version (append-only chain).

    S-007: the teacher must own the tenancy the current version was authored
    in; content authored by another school (or seeded by the platform) is
    read-only for them (403 ``content_read_only``) even though it stays
    readable for every school.
    """
    current = _content_current(db, payload.subject, payload.class_level, payload.chapter)
    if current is None:
        raise HTTPException(status_code=404, detail="content not found")
    _assert_content_writable(db, current, teacher)
    row = ChapterContent(
        subject=payload.subject,
        class_level=payload.class_level,
        chapter=payload.chapter,
        version=_content_next_version(db, payload.subject, payload.class_level, payload.chapter),
        source="teacher",
        payload=payload.sections.model_dump(),
        created_by=teacher.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _content_out(row)
