"""Workspace Routes — split from the main.py god-module.

Behavior-identical extraction: same paths, validation, status codes.
Shared context/auth via:mod:`.deps`, shared helpers via:mod:`.common`.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select

from bangla_gpt_api import ai_jobs, tracing
from bangla_gpt_api.db.models import (
    AiJob,
    ChapterContent,
    Notification,
    QuestionPaper,
    SavedNote,
    ShortTest,
    TeacherDocument,
    User,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.metrics import AI_JOBS_TOTAL
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.routers._pagination import ArchivePage
from bangla_gpt_api.schemas import (
    AiJobIn,
    AiJobOut,
    NoteSourceRef,
    NotificationListOut,
    NotificationOut,
    SavedNoteIn,
    SavedNoteOut,
    WorkloadOut,
)

from .common import (
    _doc_in_for,
    _generate_document,
    _persist_document,
    _record_analytics,
)
from .deps import (
    Ctx,
    CurrentUser,
    DbSession,
    TeacherOrAdminUser,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)


# --- teacher workload metric ------------------------------------------
# PLANNING ESTIMATES -- minutes a teacher typically spends producing each
# artifact by hand, documented here so the workload endpoint stays auditable.
# They are NOT measured; response always carries estimate=true.
_MINUTES_SAVED_PER_ARTIFACT: dict[str, int] = {
    "question_paper": 180,
    "short_test": 40,
    "lesson_plan": 60,
    "worksheet": 45,
    "study_material": 90,
    "answer_key": 30,
    "homework": 20,
    "rubric": 40,
}

logger = logging.getLogger(__name__)


def _note_out(note: SavedNote) -> SavedNoteOut:
    # Rows written before NoteSourceRef existed may carry unknown keys; project
    # onto the known fields so reading them cannot break the response contract.
    ref = None
    if note.source_ref:
        known = {k: v for k, v in note.source_ref.items() if k in NoteSourceRef.model_fields}
        ref = NoteSourceRef.model_validate(known)
    return SavedNoteOut(
        id=note.id,
        title=note.title,
        body=note.body,
        source=note.source,
        source_ref=ref,
        created_at=note.created_at,
    )


@router.post("/notes", response_model=SavedNoteOut, status_code=201)
def create_note(payload: SavedNoteIn, db: DbSession, user: CurrentUser) -> SavedNoteOut:
    title = (payload.title or payload.body.strip()[:80] or "Note")[:200]
    note = SavedNote(
        user_id=user.id,
        title=title,
        body=payload.body,
        source=payload.source,
        source_ref=payload.source_ref.model_dump(exclude_none=True) if payload.source_ref else None,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _note_out(note)


@router.get("/notes", response_model=list[SavedNoteOut])
def list_notes(db: DbSession, user: CurrentUser, page: ArchivePage) -> list[SavedNoteOut]:
    rows = (
        db.execute(
            select(SavedNote)
            .where(SavedNote.user_id == user.id)
            .order_by(SavedNote.created_at.desc(), SavedNote.id.desc())
            .offset(page.offset)
            .limit(page.limit)
        )
        .scalars()
        .all()
    )
    return [_note_out(r) for r in rows]


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: DbSession, user: CurrentUser) -> Response:
    note = db.get(SavedNote, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="note not found")
    db.delete(note)
    db.commit()
    return Response(status_code=204)


# --- in-app notification feed ----------------------------------------


def _notification_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        kind=row.kind,
        code=row.code,
        params=dict(row.params or {}),
        link=row.link,
        read_at=row.read_at,
        created_at=row.created_at,
    )


@router.get("/notifications", response_model=NotificationListOut)
def notifications_list(db: DbSession, user: CurrentUser) -> NotificationListOut:
    """The 50 newest notifications of THIS account + unread count."""
    rows = list(
        db.execute(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    ).scalar_one()
    return NotificationListOut(items=[_notification_out(r) for r in rows], unread_count=int(unread))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def notification_mark_read(
    notification_id: int, db: DbSession, user: CurrentUser
) -> NotificationOut:
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="notification not found")
    if row.read_at is None:  # idempotent: re-marking keeps the first timestamp
        row.read_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(row)
    return _notification_out(row)


# --- background generation jobs (AiJob) --------------------------------


def dispatch_ai_job(app_ctx: Ctx, job_id: str) -> asyncio.Task[None]:
    """Start the durable runner for one job and keep a strong reference.

    The handle lives on ``AppContext.ai_job_tasks`` so asyncio cannot
    garbage-collect a running job and the lifespan drain can await it. Used by
    the queue route and by the recovery sweep in the lifespan, so both entry
    points share one runner.
    """
    task = asyncio.create_task(_execute_ai_job(app_ctx, job_id))
    app_ctx.ai_job_tasks.add(task)
    task.add_done_callback(app_ctx.ai_job_tasks.discard)
    return task


async def _execute_ai_job(app_ctx: Ctx, job_id: str) -> None:
    """Run one AiJob inside an ``ai_job.run`` span (I-03), then the attempt.

    This is the worker half of the trace: the job runs detached from its
    request (``asyncio.create_task`` / the ARQ dispatcher), so without a span
    of its own the background half of the Create hub is invisible in traces.
    A no-op unless TRACING_ENABLED is set (``tracing.span``).
    """
    with tracing.span("ai_job.run"):
        await _execute_ai_job_body(app_ctx, job_id)


async def _execute_ai_job_body(app_ctx: Ctx, job_id: str) -> None:
    """Run one AiJob attempt. Durable version of the fire-and-forget runner:

    * the row is claimed with an atomic conditional UPDATE (C-08), so two
      replicas -- or the recovery sweep and a route dispatch -- cannot both run
      the same job;
    * every status write goes through the ``ai_jobs`` state machine (C-04), so
      an out-of-order transition raises instead of being persisted;
    * a failure is handed to ``ai_jobs.record_ai_job_failure``: input-shaped
      errors fail, transient ones are retried with backoff, and a job that
      keeps failing is dead-lettered -- never silently stranded.

    Runs detached from the request, so it opens its OWN session
    (``session_factory``) and never touches the request session.
    """
    db = app_ctx.session_factory()
    try:
        job = db.get(AiJob, job_id)
        if job is None:  # deleted between queue and run
            return
        actor = db.get(User, job.user_id)
        if actor is None:
            # No owner: nothing can complete this job, so fail it VISIBLY
            # instead of leaving a row that looks permanently in-progress.
            ai_jobs.abandon_ai_job(db, job_id, "owner account no longer exists")
            return
        if not ai_jobs.claim_ai_job(db, job_id):
            # Someone else owns it (another replica claimed it first, or the
            # row is terminal). Running it anyway would duplicate output.
            json_log(logger, logging.INFO, "ai_job_claim_lost", job_id=job_id)
            return
        job = db.get(AiJob, job_id)
        if job is None:  # pragma: no cover - deleted inside the claim window
            return
        try:
            gen_in = _doc_in_for(job.kind, dict(job.payload or {}))
            doc_payload, _sources, chapter = await _generate_document(
                app_ctx, db, actor, job.kind, gen_in
            )
            # Fencing: the lease may have expired while the provider was
            # thinking (the sweep would have re-queued the row). Persisting a
            # result we no longer own would duplicate the document.
            if not ai_jobs.ai_job_still_ours(db, job_id):
                json_log(logger, logging.WARNING, "ai_job_lease_lost", job_id=job_id)
                return
            ai_jobs.transition_ai_job(job, ai_jobs.AI_JOB_VALIDATING)
            db.commit()
            doc = _persist_document(
                db,
                user_id=job.user_id,
                kind=job.kind,
                class_level=gen_in.class_level,
                subject=gen_in.subject,
                chapter=chapter,
                payload=doc_payload,
            )
            ai_jobs.transition_ai_job(job, ai_jobs.AI_JOB_READY)
            job.result = {"document_id": doc.id}
            job.error = None
            # job lifecycle as sanitized product analytics.
            _record_analytics(
                db,
                job.user_id,
                actor.role,
                "ai_job_ready",
                {"kind": job.kind, "document_id": doc.id},
            )
            db.commit()
            json_log(logger, logging.INFO, "ai_job_ready", job_id=job_id, kind=job.kind)
            AI_JOBS_TOTAL.labels(kind=job.kind, status="ready").inc()
        except Exception as exc:
            db.rollback()
            try:
                status = ai_jobs.record_ai_job_failure(db, job_id, exc)
            except ai_jobs.IllegalAiJobTransition:
                # The row already reached a terminal state, so the failure came
                # from post-success bookkeeping: re-recording it would be an
                # out-of-order transition and the job itself did not fail.
                db.rollback()
                json_log(
                    logger,
                    logging.WARNING,
                    "ai_job_failure_after_terminal",
                    job_id=job_id,
                    error_type=type(exc).__name__,
                )
                return
            if status != "gone":
                _record_analytics(
                    db,
                    actor.id,
                    actor.role,
                    "ai_job_failed" if status == ai_jobs.AI_JOB_FAILED else "ai_job_retrying",
                    {"kind": job.kind, "state": status},
                )
                db.commit()
            json_log(
                logger,
                logging.WARNING,
                "ai_job_failed",
                job_id=job_id,
                kind=job.kind,
                error_type=type(exc).__name__,
                job_status=status,
            )
            # The counter keeps its original meaning: terminal outcomes only
            # (ready/failed). A scheduled retry is in-flight, not a failure --
            # counting it would quietly deflate the failure-rate alert
            # (AIJobFailureRateHigh) and the SLO ratio that reads this metric.
            if status == ai_jobs.AI_JOB_FAILED:
                AI_JOBS_TOTAL.labels(kind=job.kind, status=ai_jobs.AI_JOB_FAILED).inc()
    finally:
        db.close()


def _job_out(job: AiJob) -> AiJobOut:
    return AiJobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        payload=dict(job.payload or {}),
        result=dict(job.result) if job.result is not None else None,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/teacher/jobs", response_model=AiJobOut, status_code=202)
async def teacher_job_create(
    app_ctx: Ctx, payload: AiJobIn, db: DbSession, teacher: TeacherOrAdminUser
) -> AiJobOut:
    """Queue a generation as an AiJob: queued -> generating -> validating
    -> ready (or failed/retrying/dead_letter + error). Kind is intentionally
    not whitelisted at the door: an unsupported kind becomes a VISIBLE failed
    job, which beats a bare 422 on a long-running API."""
    job = AiJob(user_id=teacher.id, kind=payload.kind[:40], payload=dict(payload.payload))
    db.add(job)
    db.commit()
    db.refresh(job)
    dispatch_ai_job(app_ctx, job.id)
    json_log(
        logger, logging.INFO, "ai_job_queued", job_id=job.id, kind=job.kind, user_id=teacher.id
    )
    return _job_out(job)


@router.get("/teacher/jobs", response_model=list[AiJobOut])
def teacher_jobs_list(db: DbSession, teacher: TeacherOrAdminUser) -> list[AiJobOut]:
    rows = (
        db.execute(
            select(AiJob)
            .where(AiJob.user_id == teacher.id)
            .order_by(AiJob.created_at.desc(), AiJob.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return [_job_out(r) for r in rows]


@router.get("/teacher/jobs/{job_id}", response_model=AiJobOut)
def teacher_job_get(job_id: str, db: DbSession, teacher: TeacherOrAdminUser) -> AiJobOut:
    job = db.get(AiJob, job_id)
    if job is None or (job.user_id != teacher.id and teacher.role != "admin"):
        raise HTTPException(status_code=404, detail="job not found")
    return _job_out(job)


# --- teacher workload metric -------------------------------------------


@router.get("/teacher/workload", response_model=WorkloadOut)
def teacher_workload(db: DbSession, teacher: TeacherOrAdminUser) -> WorkloadOut:
    """Real per-artifact row counts from THIS account multiplied by the
    documented planning constants in _MINUTES_SAVED_PER_ARTIFACT. Only
    stored rows are counted; the minutes are estimates, never measured."""

    def count_artifact(model: Any, column: Any, kind: str | None = None) -> int:
        q = select(func.count()).select_from(model).where(column == teacher.id)
        if kind is not None:
            q = q.where(model.kind == kind)
        return int(db.execute(q).scalar_one())

    doc_counts = {
        kind: count_artifact(TeacherDocument, TeacherDocument.teacher_id, kind)
        for kind in ("lesson_plan", "worksheet", "answer_key", "homework", "rubric")
    }
    counts = {
        "question_paper": count_artifact(QuestionPaper, QuestionPaper.teacher_id),
        "short_test": count_artifact(ShortTest, ShortTest.teacher_id),
        # study material = chapters this account authored (content engine)
        "study_material": count_artifact(ChapterContent, ChapterContent.created_by),
        **doc_counts,
    }
    minutes_saved = {k: counts[k] * _MINUTES_SAVED_PER_ARTIFACT[k] for k in counts}
    return WorkloadOut(
        counts=counts,
        minutes_saved=minutes_saved,
        total_minutes_saved=sum(minutes_saved.values()),
        estimate=True,
        methodology=(
            "Counts of artifacts this account generated through the app "
            "(real DB rows) multiplied by documented planning constants: "
            f"{_MINUTES_SAVED_PER_ARTIFACT} minutes typically spent "
            "producing each artifact manually. Planning estimate only -- "
            "not a measured time saving."
        ),
    )


# --- short tests (class+chapter ultra-fast, whole classroom) ------
