"""C-04: the AiJob lifecycle is an explicit state machine, not a convention.

AUD-CD-18 found ``status`` written inline at every call site
(``workspace.py`` set generating/validating/ready/failed directly) with no
allowed-transition table and no test that an out-of-order write is refused.
``ai_jobs.AI_JOB_ALLOWED_TRANSITIONS`` is now the single writer, and this module
pins it exhaustively:

* every state in the table is a real status and every state is reachable from
  ``queued`` (a state nobody can enter is a bug, not a state);
* the terminal states have no outgoing edge;
* every *legal* edge applies, every *illegal* pair raises and leaves the row
  untouched -- generated from the table itself, so adding an edge to the code
  without thinking about the machine fails here;
* the durable claim respects the same table.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from sqlalchemy import select

from bangla_gpt_api import ai_jobs
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiJob, User
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory

ALL_PAIRS = sorted(itertools.product(sorted(ai_jobs.AI_JOB_STATUSES), repeat=2))
LEGAL_PAIRS = sorted(
    (source, target)
    for source, targets in ai_jobs.AI_JOB_ALLOWED_TRANSITIONS.items()
    for target in targets
)
ILLEGAL_PAIRS = [pair for pair in ALL_PAIRS if pair not in set(LEGAL_PAIRS)]


@pytest.fixture
def factory(tmp_path: Path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/lifecycle.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    engine = make_engine(settings)
    init_db(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def temp_job(factory):
    """One AiJob row that each test may start from any status."""
    db = factory()
    try:
        user = User(email="lifecycle@test.example", password_hash="x", role="teacher")
        db.add(user)
        db.flush()
        job = AiJob(user_id=user.id, kind="worksheet", payload={}, status=ai_jobs.AI_JOB_QUEUED)
        db.add(job)
        db.commit()
        yield db, job
    finally:
        db.close()


# ------------------------------------------------------------- the table --


def test_every_state_is_a_real_status() -> None:
    assert set(ai_jobs.AI_JOB_ALLOWED_TRANSITIONS) == set(ai_jobs.AI_JOB_STATUSES)
    # Exactly the five values the ck_ai_jobs_status CHECK constraint allows:
    # a sixth status must not be invented here without a migration.
    assert (
        frozenset({"queued", "generating", "validating", "ready", "failed"})
        == ai_jobs.AI_JOB_STATUSES
    )


def test_terminal_states_have_no_outgoing_edges() -> None:
    for status in ai_jobs.AI_JOB_TERMINAL_STATUSES:
        assert ai_jobs.AI_JOB_ALLOWED_TRANSITIONS[status] == frozenset()


def test_every_state_is_reachable_from_queued() -> None:
    reached = {ai_jobs.AI_JOB_QUEUED}
    frontier = [ai_jobs.AI_JOB_QUEUED]
    while frontier:
        source = frontier.pop()
        for target in ai_jobs.AI_JOB_ALLOWED_TRANSITIONS[source]:
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    assert reached == set(ai_jobs.AI_JOB_STATUSES)


def test_non_terminal_states_have_a_way_out() -> None:
    for status in ai_jobs.AI_JOB_STATUSES - ai_jobs.AI_JOB_TERMINAL_STATUSES:
        assert ai_jobs.AI_JOB_ALLOWED_TRANSITIONS[status], f"{status} is a dead end"


def test_every_edge_targets_a_declared_status() -> None:
    for source, targets in ai_jobs.AI_JOB_ALLOWED_TRANSITIONS.items():
        assert targets <= ai_jobs.AI_JOB_STATUSES, source


# ------------------------------------------------------- applying edges --


def test_every_legal_edge_applies(temp_job) -> None:
    db, job = temp_job
    for source, target in LEGAL_PAIRS:
        job.status = source
        ai_jobs.transition_ai_job(job, target)
        assert job.status == target
    db.rollback()


def test_every_illegal_pair_is_rejected(temp_job) -> None:
    """Exhaustive over the complement of the table (the audit's "no guard")."""
    _db, job = temp_job
    assert ILLEGAL_PAIRS, "the table must forbid something or it is not a table"
    for source, target in ILLEGAL_PAIRS:
        job.status = source
        with pytest.raises(ai_jobs.IllegalAiJobTransition) as excinfo:
            ai_jobs.transition_ai_job(job, target)
        assert (excinfo.value.current, excinfo.value.target) == (source, target)
        assert job.status == source, "a rejected transition must not mutate the row"


def test_unknown_status_is_rejected(temp_job) -> None:
    _db, job = temp_job
    with pytest.raises(ai_jobs.IllegalAiJobTransition):
        ai_jobs.transition_ai_job(job, "banana")


def test_queued_cannot_jump_straight_to_ready(temp_job) -> None:
    """The exact out-of-order write the row is about: no validation step."""
    _db, job = temp_job
    assert job.status == ai_jobs.AI_JOB_QUEUED
    with pytest.raises(ai_jobs.IllegalAiJobTransition):
        ai_jobs.transition_ai_job(job, ai_jobs.AI_JOB_READY)


def test_ready_is_final(temp_job) -> None:
    _db, job = temp_job
    job.status = ai_jobs.AI_JOB_READY
    for target in (ai_jobs.AI_JOB_VALIDATING, ai_jobs.AI_JOB_QUEUED, ai_jobs.AI_JOB_FAILED):
        with pytest.raises(ai_jobs.IllegalAiJobTransition):
            ai_jobs.transition_ai_job(job, target)


def test_dead_letter_classification_is_terminal_failure() -> None:
    """The dead-letter case is a terminal ``failed`` carrying the marker."""
    job = AiJob(user_id=1, kind="worksheet", payload={}, status=ai_jobs.AI_JOB_FAILED)
    job.error = ai_jobs._attempt_error(3, "ProviderError", dead_lettered=True)
    assert ai_jobs.is_dead_lettered(job) is True
    # an input-shaped failure is NOT a dead letter: it never retried
    job.error = ai_jobs._attempt_error(1, "ValidationError")
    assert ai_jobs.is_dead_lettered(job) is False
    # a still-running job is not dead-lettered either
    job.status = ai_jobs.AI_JOB_GENERATING
    job.error = ai_jobs._attempt_error(1, "ProviderError", dead_lettered=True)
    assert ai_jobs.is_dead_lettered(job) is False


def test_can_transition_matches_the_table(temp_job) -> None:
    _db, job = temp_job
    for source, target in ALL_PAIRS:
        job.status = source
        assert ai_jobs.can_transition(source, target) is (
            target in ai_jobs.AI_JOB_ALLOWED_TRANSITIONS[source]
        )


# ------------------------------------------------------ the claim table --


def test_claim_sources_come_from_the_transition_table(factory) -> None:
    """The claim may only move rows whose edge to ``generating`` is legal."""
    db = factory()
    try:
        assert all(
            ai_jobs.can_transition(status, ai_jobs.AI_JOB_GENERATING)
            for status in ai_jobs.AI_JOB_CLAIMABLE_STATUSES
        )
        assert frozenset({ai_jobs.AI_JOB_QUEUED}) == ai_jobs.AI_JOB_CLAIMABLE_STATUSES, (
            "a retry re-queues into the same claimable state the queue route uses"
        )
    finally:
        db.close()


@pytest.mark.parametrize(
    "status", sorted(ai_jobs.AI_JOB_TERMINAL_STATUSES | {ai_jobs.AI_JOB_VALIDATING})
)
def test_claim_refuses_rows_that_are_not_claimable(factory, status) -> None:
    db = factory()
    try:
        user = User(email=f"{status}@test.example", password_hash="x", role="teacher")
        db.add(user)
        db.flush()
        job = AiJob(user_id=user.id, kind="worksheet", payload={}, status=status)
        db.add(job)
        db.commit()

        assert ai_jobs.claim_ai_job(db, job.id) is False
        assert db.execute(select(AiJob.status).where(AiJob.id == job.id)).scalar_one() == status
    finally:
        db.close()


def test_claim_takes_a_queued_row(factory) -> None:
    db = factory()
    try:
        user = User(email="claim@test.example", password_hash="x", role="teacher")
        db.add(user)
        db.flush()
        job = AiJob(user_id=user.id, kind="worksheet", payload={}, status=ai_jobs.AI_JOB_QUEUED)
        db.add(job)
        db.commit()

        assert ai_jobs.claim_ai_job(db, job.id) is True
        assert db.execute(select(AiJob.status).where(AiJob.id == job.id)).scalar_one() == (
            ai_jobs.AI_JOB_GENERATING
        )
        # and a second claim of the same row is refused (already generating)
        assert ai_jobs.claim_ai_job(db, job.id) is False
    finally:
        db.close()
